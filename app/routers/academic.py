# -*- coding: utf-8 -*-
"""
academic.py - งานวิชาการ
เฟส 1: ห้องเรียน/ครูประจำชั้น + รายวิชา + ผลการเรียน + ปพ.5 / ปพ.6 (สมุดพก)

ความสัมพันธ์กับทะเบียนกลาง: ดึงรายชื่อจาก Student แล้วเก็บ "สำเนารายปี" (AcadStudent)
เหมือนงานภาวะโภชนาการ - ผลการเรียนของปีเก่าจึงไม่ขยับเมื่อนักเรียนเลื่อนชั้น
ครูทั้งหมดมาจากทะเบียนบุคลากรกลาง (Person) ไม่มีการสร้างทะเบียนครูซ้ำ
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Student, Person, AcadClass, AcadStudent, AcadSubject,
                        AcadTeaching, AcadScore, AcadEval,
                        AcadAssignment, AcadAssignmentScore, AcadIndicatorResult,
                        AcadCharEval, AcadReadEval, AcadAttendance, AcadClassMonth,
                        AcadCalendar, AcadHoliday, AcadYearSetting,
                        AcadActivity, AcadActivityResult, AcadOnet)
from app.thai_utils import (SCHOOL_LEVELS, GRADUATED, current_academic_year, current_term,
                            is_secondary, level_rank)
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated
from app.services.academic import (grade_of, subject_preset, term_choices, term_label,
                                   GRADE_CHOICES, QUALITY_LEVELS, PASS_FAIL, SUBJECT_KINDS,
                                   CHAR_ITEMS, CHAR_FIELDS, READ_DOMAINS, TH_MONTHS,
                                   TH_MONTH_FULL, quality_of_avg, char_avg, read_avg,
                                   effective_eval, MARK_STATES, MARK_CHARS, MARK_BLANK,
                                   TH_WEEKDAYS, month_weekdays, default_open_days,
                                   parse_days_csv, parse_marks, build_marks, count_marks,
                                   seed_fixed_holidays, holiday_map, in_term, auto_open_days,
                                   LUNAR_HOLIDAY_NAMES, activity_preset, activities_for,
                                   activity_summary, ONET_SUBJECTS, is_exit_level, onet_for,
                                   TERM_MONTHS)
from app.thai_utils import parse_be_date, be_date_input
from app.services.curriculum import indicators_for, has_indicators, selected_indicators

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _years(db, cur: int) -> list:
    """ปีการศึกษาที่มีข้อมูล + ปีปัจจุบัน (เรียงใหม่->เก่า)"""
    ys = {r[0] for r in db.query(AcadClass.year).distinct() if r[0]}
    ys |= {r[0] for r in db.query(AcadSubject.year).distinct() if r[0]}
    ys.add(cur)
    return sorted(ys, reverse=True)


def _class_label(c) -> str:
    return f"{c.level}/{c.room}" if (c.room or "").strip() else (c.level or "")


def _sorted_classes(rows) -> list:
    return sorted(rows, key=lambda c: (level_rank(c.level), c.room or ""))


# ลำดับเดือนตามปีการศึกษา (พ.ค. มาก่อน ม.ค.) - ใช้เรียงตารางวันหยุด
TH_MONTH_ORDER = {m: i for i, (m, _) in enumerate(TH_MONTHS)}


# ---------------- สิทธิ์ครู (row-level: เห็น/แก้ได้เฉพาะวิชา-ห้องตัวเอง) ----------------
class _Scope:
    """ขอบเขตสิทธิ์งานวิชาการของผู้ใช้ปัจจุบัน
    - is_teacher=False -> เจ้าหน้าที่/เจ้าของ: เห็น/แก้ได้ทุกอย่าง (ทุก can_* คืน True)
    - is_teacher=True  -> ครู (บัญชีผูกกับ Person): จำกัดตามที่สอน/ประจำชั้น
        teach_pairs = {(class_id, subject_id)} วิชา×ห้องที่สอน
        homeroom_ids = ห้องที่เป็นครูประจำชั้น/คู่ชั้น
        class_ids    = ห้องที่แตะได้ (สอน + ประจำชั้น)"""
    def __init__(self, pid, db):
        self.pid = pid
        self.is_teacher = pid is not None
        if not self.is_teacher:
            self.teach_pairs = self.subject_ids = None
            self.teach_class_ids = self.homeroom_ids = self.class_ids = None
            return
        teach = db.query(AcadTeaching).filter_by(teacher_id=pid).all()
        self.teach_pairs = {(t.class_id, t.subject_id) for t in teach}
        self.subject_ids = {t.subject_id for t in teach}
        self.teach_class_ids = {t.class_id for t in teach}
        self.homeroom_ids = {c.id for c in db.query(AcadClass).filter(
            (AcadClass.homeroom_id == pid) | (AcadClass.co_homeroom_id == pid)).all()}
        self.class_ids = self.teach_class_ids | self.homeroom_ids

    def can_class(self, cid) -> bool:
        return (not self.is_teacher) or (cid in self.class_ids)

    def can_homeroom(self, cid) -> bool:
        return (not self.is_teacher) or (cid in self.homeroom_ids)

    def can_teach(self, cid, sid) -> bool:
        return (not self.is_teacher) or ((cid, sid) in self.teach_pairs)

    def can_subject(self, sid) -> bool:
        return (not self.is_teacher) or (sid in self.subject_ids)


def _scope(request, db) -> _Scope:
    sess = request.session
    if sess.get("owner"):
        return _Scope(None, db)
    pid = sess.get("person_id")
    return _Scope(int(pid) if pid else None, db)


def _deny():
    """ครูพยายามเข้าถึงของคนอื่น/ฟังก์ชันเจ้าหน้าที่ -> เด้งกลับหน้าหลัก"""
    return RedirectResponse("/academic", status_code=303)


def _resolve_teacher(db, name):
    """ชื่อครู (พิมพ์/เลือกจาก datalist) -> Person.id · ไม่พบ = None"""
    name = (name or "").strip()
    if not name:
        return None
    p = (db.query(Person).filter(Person.active == True, Person.name == name).first()
         or db.query(Person).filter(Person.name == name).first())
    return p.id if p else None


def _assign_subject_teacher(db, subj, teacher_id):
    """ตั้งครูผู้สอนของวิชานี้ให้ทุกห้องของชั้นเดียวกัน (เชื่อมกับหน้าห้องเรียน)
    ใช้ตอนตั้งครูจากหน้ารายวิชา - แก้รายห้องได้ละเอียดกว่าที่หน้าห้องเรียน"""
    classes = db.query(AcadClass).filter_by(year=subj.year, level=subj.level).all()
    for c in classes:
        row = db.query(AcadTeaching).filter_by(class_id=c.id, subject_id=subj.id).first()
        if row:
            row.teacher_id = teacher_id
        elif teacher_id:
            db.add(AcadTeaching(class_id=c.id, subject_id=subj.id, teacher_id=teacher_id))


def _subject_teacher_names(db, subjects):
    """map subject_id -> ชื่อครู (โชว์ในช่องรายวิชา) · ถ้าหลายห้องคนละครู = เว้นว่าง (ไปแก้รายห้อง)"""
    ids = [s.id for s in subjects]
    if not ids:
        return {}
    from collections import defaultdict
    names = defaultdict(set)
    q = (db.query(AcadTeaching.subject_id, Person.name)
         .join(Person, AcadTeaching.teacher_id == Person.id)
         .filter(AcadTeaching.subject_id.in_(ids)))
    for sid, nm in q.all():
        names[sid].add(nm)
    return {sid: (next(iter(ns)) if len(ns) == 1 else "") for sid, ns in names.items()}


def _current_month() -> int:
    """เดือนปัจจุบันสำหรับเช็กชื่อ - นอกเทอม (เม.ย.) ใช้เดือนแรกของภาคปัจจุบัน"""
    m = datetime.now().month
    if m in (TERM_MONTHS[1] | TERM_MONTHS[2]):
        return m
    return 5 if current_term() == 1 else 11


def _att_ok(sc, cid, mode, sid) -> bool:
    """สิทธิ์เช็กเวลาเรียน: โหมดรายวิชา = วิชาที่สอน · โหมดโดยรวม = ห้องที่ประจำชั้น"""
    if not sc.is_teacher:
        return True
    if mode == "subject":
        return sc.can_teach(cid, sid)
    return sc.can_homeroom(cid)


# ---------------- หน้าหลัก ----------------
@router.get("/academic", response_class=HTMLResponse)
def academic_home(request: Request, db: Session = Depends(get_db),
                  year: int | None = None, term: int | None = None):
    y = year or current_academic_year()
    t = term if term in (1, 2) else current_term()
    sc = _scope(request, db)
    classes = db.query(AcadClass).filter_by(year=y).all()
    if sc.is_teacher:
        classes = [c for c in classes if c.id in sc.class_ids]
    n_students = sum(len(c.students) for c in classes)
    progress = [(_class_label(c), c, _class_progress(c, db, t)) for c in _sorted_classes(classes)]
    n_subjects = db.query(AcadSubject).filter_by(year=y).count()
    if sc.is_teacher:
        n_subjects = len(sc.subject_ids)
    return templates.TemplateResponse("academic_home.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "n_classes": len(classes), "n_students": n_students,
        "n_subjects": n_subjects,
        "progress": progress, "is_exit_level": is_exit_level,
        "term": t, "term_label": term_label, "is_teacher": sc.is_teacher,
        "att_mode": ("subject" if (sc.is_teacher and sc.teach_pairs) else "overall"),
    })


def _class_progress(c, db, term):
    """ความคืบหน้าการประเมินของห้อง 1 ห้อง (ภาคเรียน term) - นับวิชาที่กรอก/ประเมินแล้ว
    มัธยม: วิชาของภาคนั้น (subject.term) · ประถม: ทุกวิชา แต่ char/read/คะแนน กรองตามภาคที่กรอก"""
    from app.models import (AcadScore, AcadCharEval, AcadReadEval, AcadIndicatorResult,
                            AcadActivityResult, AcadAttendance, AcadOnet)
    from app.services.curriculum import selected_indicators
    sec = is_secondary(c.level)
    sids = [s.id for s in c.students]
    nst = len(sids)
    subs = db.query(AcadSubject).filter_by(year=c.year, level=c.level).all()
    if sec:
        subs = [x for x in subs if (x.term or 0) == term]     # มัธยม: เฉพาะวิชาภาคนี้
    sub_ids = [x.id for x in subs]
    nsub = len(subs)
    eval_tf = 0 if sec else term      # ตัวกรอง term ของ char/read (มัธยม=0 · ประถม=ภาคที่เลือก)

    def n_subj(model, cond=None, tf=None):
        if not (sub_ids and sids):
            return 0
        q = db.query(model.subject_id).filter(model.subject_id.in_(sub_ids),
                                              model.acad_student_id.in_(sids))
        if tf is not None:
            q = q.filter(model.term == tf)
        if cond is not None:
            q = q.filter(cond)
        return len({r[0] for r in q.distinct().all()})

    grade = n_subj(AcadScore, AcadScore.score.isnot(None), tf=term)
    char = n_subj(AcadCharEval, tf=eval_tf)
    read = n_subj(AcadReadEval, tf=eval_tf)
    ind = n_subj(AcadIndicatorResult)          # ตัวชี้วัดผูกกับวิชา (ไม่มี term ของตัวเอง)
    ind_total = sum(1 for x in subs if selected_indicators(x))
    acts = activities_for(c.year, c.level, db)
    act_done = 0
    if acts and sids:
        act_done = len({r[0] for r in db.query(AcadActivityResult.acad_student_id)
                        .filter(AcadActivityResult.acad_student_id.in_(sids)).distinct().all()})
    att = bool(sids) and db.query(AcadAttendance).filter(
        AcadAttendance.acad_student_id.in_(sids)).first() is not None
    onet = 0
    if is_exit_level(c.level) and sids:
        onet = db.query(AcadOnet).filter(AcadOnet.acad_student_id.in_(sids)).count()
    return {
        "nst": nst, "nsub": nsub,
        "grade": grade, "char": char, "read": read,
        "ind": ind, "ind_total": ind_total,
        "act_done": act_done, "n_acts": len(acts),
        "att": att, "onet": onet, "exit": is_exit_level(c.level),
    }


# ---------------- บัญชีครู (owner สร้าง/ผูกกับ Person -> สิทธิ์เฉพาะวิชา/ห้องตัวเอง) ----------------
@router.get("/academic/teacher-accounts", response_class=HTMLResponse)
def teacher_accounts_page(request: Request, db: Session = Depends(get_db),
                          msg: str = "", err: str = ""):
    if not request.session.get("owner"):
        return RedirectResponse("/academic", status_code=303)
    from app.accounts import list_teacher_accounts, acc_session, Tenant
    tid = request.session.get("tid")
    persons = db.query(Person).filter_by(active=True).order_by(Person.name).all()
    accts = list_teacher_accounts(tid)
    linked = {a["person_id"]: a for a in accts}
    adb = acc_session()
    try:
        tn = adb.query(Tenant).filter_by(id=tid).first()
        school_code = ((tn.slug if tn else "") or f"t{tid}")
    finally:
        adb.close()
    return templates.TemplateResponse("academic_teachers.html", {
        "request": request, "school": get_school(db), "persons": persons,
        "linked": linked, "n_accts": len(accts), "msg": msg, "err": err,
        "school_code": school_code,
    })


@router.post("/academic/teacher-accounts/add")
def teacher_account_add(request: Request, db: Session = Depends(get_db),
                        person_id: str = Form(""), username: str = Form(""),
                        password: str = Form("")):
    if not request.session.get("owner"):
        return RedirectResponse("/academic", status_code=303)
    from app.accounts import add_teacher_account
    tid = request.session.get("tid")
    p = db.get(Person, _to_int(person_id, 0))
    r = add_teacher_account(tid, _to_int(person_id, 0), username, password,
                            display_name=(p.name if p else ""))
    if r.get("error"):
        return RedirectResponse(f"/academic/teacher-accounts?err={r['error']}", status_code=303)
    return RedirectResponse(
        f"/academic/teacher-accounts?msg=สร้างบัญชีครูแล้ว - ไอดีเข้าระบบคือ {r.get('username', username)}",
        status_code=303)


# ---------------- ห้องเรียน ----------------
@router.get("/academic/classes", response_class=HTMLResponse)
def classes_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    y = year or current_academic_year()
    sc = _scope(request, db)
    rows = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        rows = [c for c in rows if c.id in sc.class_ids]
    return templates.TemplateResponse("academic_classes.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "rows": rows, "levels": SCHOOL_LEVELS, "class_label": _class_label,
        "teachers": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
        "is_teacher": sc.is_teacher,
        "homeroom_ids": (sc.homeroom_ids or set()),
    })


@router.post("/academic/classes/add")
def class_add(request: Request, db: Session = Depends(get_db), year: str = Form(""), level: str = Form(""),
              room: str = Form(""), homeroom_id: str = Form(""), co_homeroom_id: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    lv = (level or "").strip()
    rm = (room or "").strip()
    if lv and not db.query(AcadClass).filter_by(year=y, level=lv, room=rm).first():
        db.add(AcadClass(year=y, level=lv, room=rm,
                         homeroom_id=_to_int(homeroom_id, 0) or None,
                         co_homeroom_id=_to_int(co_homeroom_id, 0) or None))
        db.commit()
    return RedirectResponse(f"/academic/classes?year={y}", status_code=303)


@router.post("/academic/classes/{cid}/update")
def class_update(cid: int, request: Request, db: Session = Depends(get_db), level: str = Form(""),
                 room: str = Form(""), homeroom_id: str = Form(""),
                 co_homeroom_id: str = Form(""), note: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    c.level = (level or "").strip() or c.level
    c.room = (room or "").strip()
    c.homeroom_id = _to_int(homeroom_id, 0) or None
    c.co_homeroom_id = _to_int(co_homeroom_id, 0) or None
    c.note = (note or "").strip()
    db.commit()
    return RedirectResponse(f"/academic/classes?year={c.year}", status_code=303)


@router.post("/academic/classes/{cid}/delete")
def class_delete(cid: int, request: Request, db: Session = Depends(get_db)):
    if _scope(request, db).is_teacher:
        return _deny()
    c = db.get(AcadClass, cid)
    y = c.year if c else None
    if c:
        db.delete(c); db.commit()
    return RedirectResponse(f"/academic/classes?year={y or ''}", status_code=303)


@router.get("/academic/classes/{cid}", response_class=HTMLResponse)
def class_detail(request: Request, cid: int, db: Session = Depends(get_db)):
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    sc = _scope(request, db)
    if not sc.can_class(cid):
        return _deny()
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
    subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                .order_by(AcadSubject.seq, AcadSubject.code).all())
    if sc.is_teacher:                      # ครู: เห็น/พิมพ์ ปพ.5 เฉพาะวิชาที่ตัวเองสอนในห้องนี้
        subjects = [x for x in subjects if (cid, x.id) in sc.teach_pairs]
    teach = {t.subject_id: t for t in c.teachings}
    return templates.TemplateResponse("academic_class.html", {
        "request": request, "school": get_school(db), "c": c, "students": students,
        "subjects": subjects, "teach": teach, "class_label": _class_label(c),
        "teachers": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
        "terms": term_choices(c.level), "term_label": term_label,
        "is_sec": is_secondary(c.level),
        "is_teacher": sc.is_teacher, "can_edit_roster": sc.can_homeroom(cid),
    })


@router.post("/academic/classes/{cid}/pull-roster")
def class_pull_roster(cid: int, request: Request, db: Session = Depends(get_db)):
    """ดึงนักเรียนจากทะเบียนกลางเข้าห้องนี้ (จับคู่ด้วยชั้น+ห้อง · ข้ามคนที่ดึงมาแล้ว)"""
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    if not _scope(request, db).can_homeroom(cid):
        return _deny()
    have_ids = {s.student_id for s in c.students if s.student_id}
    have_names = {(s.name or "").strip() for s in c.students}
    q = db.query(Student).filter(Student.level == c.level)
    if (c.room or "").strip():
        q = q.filter(Student.room == c.room)
    seq = max([s.seq or 0 for s in c.students], default=0)
    for st in q.order_by(Student.student_no, Student.name).all():
        if st.id in have_ids or (st.name or "").strip() in have_names:
            continue
        seq += 1
        db.add(AcadStudent(class_id=c.id, student_id=st.id, seq=seq,
                           student_no=st.student_no or "", name=st.name, sex=st.sex or ""))
    db.commit()
    return RedirectResponse(f"/academic/classes/{cid}", status_code=303)


@router.post("/academic/student/{aid}/update")
def acad_student_update(aid: int, request: Request, db: Session = Depends(get_db), seq: str = Form(""),
                        student_no: str = Form(""), name: str = Form(""), sex: str = Form("")):
    s = db.get(AcadStudent, aid)
    if s and not _scope(request, db).can_homeroom(s.class_id):
        return _deny()
    if s:
        s.seq = _to_int(seq, 0)
        s.student_no = (student_no or "").strip()
        s.name = (name or "").strip() or s.name
        s.sex = (sex or "").strip()
        db.commit()
    return RedirectResponse(f"/academic/classes/{s.class_id}" if s else "/academic/classes",
                            status_code=303)


@router.post("/academic/student/{aid}/delete")
def acad_student_delete(aid: int, request: Request, db: Session = Depends(get_db)):
    s = db.get(AcadStudent, aid)
    if s and not _scope(request, db).can_homeroom(s.class_id):
        return _deny()
    cid = s.class_id if s else None
    if s:
        db.delete(s); db.commit()
    return RedirectResponse(f"/academic/classes/{cid}" if cid else "/academic/classes",
                            status_code=303)


@router.post("/academic/classes/{cid}/teaching")
async def teaching_save(cid: int, request: Request, db: Session = Depends(get_db)):
    """กำหนดครูผู้สอนรายวิชาของห้องนี้ (วิชาเดียวกันคนละห้องคนละครูได้)"""
    if _scope(request, db).is_teacher:
        return _deny()
    form = await request.form()
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    cur = {t.subject_id: t for t in c.teachings}
    for key, val in form.items():
        if not key.startswith("teacher_"):
            continue
        sid = _to_int(key[8:], 0)
        if not sid:
            continue
        raw = (val or "").strip()
        if raw == "":
            tid = None                        # ล้างช่อง = เอาครูออก
        else:
            tid = _resolve_teacher(db, raw)
            if tid is None:
                continue                      # พิมพ์ชื่อไม่ตรงใคร = ไม่แตะ (กันลบพลาด)
        if sid in cur:
            if tid:
                cur[sid].teacher_id = tid
            else:
                db.delete(cur[sid])
        elif tid:
            db.add(AcadTeaching(class_id=cid, subject_id=sid, teacher_id=tid))
    db.commit()
    return RedirectResponse(f"/academic/classes/{cid}?saved=1", status_code=303)


# ---------------- รายวิชา ----------------
@router.get("/academic/subjects", response_class=HTMLResponse)
def subjects_page(request: Request, db: Session = Depends(get_db),
                  year: int | None = None, level: str = ""):
    y = year or current_academic_year()
    sc = _scope(request, db)
    q = db.query(AcadSubject).filter_by(year=y)
    if level:
        q = q.filter_by(level=level)
    rows = sorted(q.all(), key=lambda s: (level_rank(s.level), s.seq or 0, s.code or ""))
    if sc.is_teacher:
        rows = [s for s in rows if s.id in sc.subject_ids]
    # กิจกรรมพัฒนาผู้เรียน (การ์ดที่ 2) - แสดงเมื่อเลือกชั้นแล้วเท่านั้น
    activities = activities_for(y, level, db) if (level and not sc.is_teacher) else []
    teachers = (db.query(Person).filter_by(active=True).order_by(Person.name).all()
                if not sc.is_teacher else [])
    subj_teacher = _subject_teacher_names(db, rows) if not sc.is_teacher else {}
    return templates.TemplateResponse("academic_subjects.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "rows": rows, "level": level, "levels": SCHOOL_LEVELS, "kinds": SUBJECT_KINDS,
        "term_label": term_label, "is_secondary": is_secondary, "activities": activities,
        "is_teacher": sc.is_teacher, "teachers": teachers, "subj_teacher": subj_teacher,
    })


@router.post("/academic/subjects/add")
def subject_add(request: Request, db: Session = Depends(get_db), year: str = Form(""), level: str = Form(""),
                code: str = Form(""), name: str = Form(""), learn_group: str = Form(""),
                kind: str = Form("พื้นฐาน"), hours: str = Form(""), credit: str = Form(""),
                term: str = Form("0"), mid_max: str = Form("70"), final_max: str = Form("30"),
                teacher_name: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    nm = (name or "").strip()
    if nm:
        n = db.query(AcadSubject).filter_by(year=y, level=(level or "").strip()).count()
        mm, fm = max(0, _to_int(mid_max, 70)), max(0, _to_int(final_max, 30))
        if (mm + fm) <= 0:            # กันสัดส่วน 0:0 (เกรดจะคิดจากค่าปริยายเงียบ ๆ)
            mm, fm = 70, 30
        subj = AcadSubject(year=y, level=(level or "").strip(), code=(code or "").strip(),
                           name=nm, learn_group=(learn_group or "").strip(),
                           kind=(kind or "พื้นฐาน").strip(), hours=_to_int(hours, 0),
                           credit=_to_float(credit, 0.0), term=_to_int(term, 0), seq=n + 1,
                           mid_max=mm, final_max=fm)
        db.add(subj)
        db.flush()
        tid = _resolve_teacher(db, teacher_name)   # ตั้งครูให้ทุกห้องของชั้นนี้ (เชื่อมกับห้องเรียน)
        if tid:
            _assign_subject_teacher(db, subj, tid)
        db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={level}", status_code=303)


@router.post("/academic/subjects/{sid}/update")
def subject_update(sid: int, request: Request, db: Session = Depends(get_db), code: str = Form(""),
                   name: str = Form(""), learn_group: str = Form(""), kind: str = Form(""),
                   hours: str = Form(""), credit: str = Form(""), term: str = Form("0"),
                   mid_max: str = Form("70"), final_max: str = Form("30"),
                   teacher_name: str = Form(""), flt_level: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    s = db.get(AcadSubject, sid)
    if s:
        s.code = (code or "").strip()
        s.name = (name or "").strip() or s.name
        s.learn_group = (learn_group or "").strip()
        s.kind = (kind or "").strip() or s.kind
        s.hours = _to_int(hours, 0)
        s.credit = _to_float(credit, 0.0)
        s.term = _to_int(term, 0)
        # กันสัดส่วน 0:0 (จะทำให้เกรดคิดจากค่าปริยายเงียบ ๆ จนครูงงว่าทำไมไม่ตรง)
        mm, fm = max(0, _to_int(mid_max, 70)), max(0, _to_int(final_max, 30))
        s.mid_max, s.final_max = (mm, fm) if (mm + fm) > 0 else (70, 30)
        # ครูผู้สอน: กรอกชื่อ = ตั้งให้ทุกห้องของชั้น · เว้นว่าง = ไม่แตะ (ล้างครูทำที่หน้าห้องเรียน)
        tid = _resolve_teacher(db, teacher_name)
        if tid:
            _assign_subject_teacher(db, s, tid)
        db.commit()
    # กลับหน้าเดิม: คงชั้นที่กรองอยู่ + เลื่อนไปแถวที่เพิ่งบันทึก (ไม่เด้งขึ้นบนสุด)
    lv = (flt_level or "").strip()
    return RedirectResponse(f"/academic/subjects?year={s.year if s else ''}&level={lv}#sub-{sid}",
                            status_code=303)


@router.post("/academic/subjects/{sid}/delete")
def subject_delete(sid: int, request: Request, db: Session = Depends(get_db),
                   flt_level: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    s = db.get(AcadSubject, sid)
    y = s.year if s else ""
    if s:
        db.delete(s); db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={(flt_level or '').strip()}",
                            status_code=303)


@router.post("/academic/subjects/preset")
def subjects_preset(request: Request, db: Session = Depends(get_db), year: str = Form(""), level: str = Form("")):
    """สร้างรายวิชาพื้นฐาน 8 กลุ่มสาระของชั้นนี้ในคลิกเดียว (ข้ามวิชาที่มีรหัสซ้ำแล้ว)"""
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    lv = (level or "").strip()
    have = {(s.code or "").strip() for s in db.query(AcadSubject).filter_by(year=y, level=lv).all()}
    n = db.query(AcadSubject).filter_by(year=y, level=lv).count()
    terms = term_choices(lv)
    preset = subject_preset(lv)
    if not preset:
        # อนุบาล/ชั้นนอกระบบ: ไม่มีรหัสวิชามาตรฐาน -> บอกครูว่าทำไมไม่มีอะไรเกิดขึ้น
        return RedirectResponse(f"/academic/subjects?year={y}&level={lv}&preset=none", status_code=303)
    added = 0
    for p in preset:
        if p["code"] in have:
            continue
        n += 1
        added += 1
        # มัธยมตัดสินรายภาค -> สร้างวิชาละ 2 ภาค · ประถมรายปี -> ภาคเดียว (term=0)
        for t in terms:
            db.add(AcadSubject(year=y, level=lv, code=p["code"], name=p["name"],
                               learn_group=p["learn_group"], kind=p["kind"],
                               hours=p["hours"] // len(terms), term=t, seq=n))
    db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={lv}&preset={added}", status_code=303)


# ---------------- กิจกรรมพัฒนาผู้เรียน (ตั้งค่า) ----------------
@router.post("/academic/activities/save")
async def activities_save(request: Request, db: Session = Depends(get_db),
                          year: str = Form(""), level: str = Form("")):
    """บันทึกทั้งชุด: แก้/ลบแถวเดิม (ปุ่มลบส่ง del_<id>) + เพิ่มแถวใหม่จากช่องท้าย"""
    if _scope(request, db).is_teacher:
        return _deny()
    form = await request.form()
    y = _to_int(year, 0) or current_academic_year()
    lv = (level or "").strip()
    for a in db.query(AcadActivity).filter_by(year=y, level=lv).all():
        if form.get(f"del_{a.id}"):
            db.delete(a)
            continue
        a.code = (form.get(f"code_{a.id}", "") or "").strip()
        a.name = (form.get(f"name_{a.id}", "") or "").strip() or a.name
        a.hours = _to_int(form.get(f"hours_{a.id}", ""), None)
    nm = (form.get("new_name", "") or "").strip()
    if nm:
        n = db.query(AcadActivity).filter_by(year=y, level=lv).count()
        db.add(AcadActivity(year=y, level=lv, name=nm,
                            code=(form.get("new_code", "") or "").strip(),
                            hours=_to_int(form.get("new_hours", ""), None), seq=n + 1))
    db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={lv}&asaved=1", status_code=303)


@router.post("/academic/activities/preset")
def activities_preset(request: Request, db: Session = Depends(get_db), year: str = Form(""), level: str = Form("")):
    """สร้างกิจกรรมมาตรฐาน 4 อย่างในคลิกเดียว (ข้ามชื่อที่มีอยู่แล้ว)"""
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    lv = (level or "").strip()
    have = {(a.name or "").strip() for a in db.query(AcadActivity).filter_by(year=y, level=lv).all()}
    n = db.query(AcadActivity).filter_by(year=y, level=lv).count()
    added = 0
    for p in activity_preset(lv):
        if p["name"] in have:
            continue
        n += 1; added += 1
        db.add(AcadActivity(year=y, level=lv, code=p["code"], name=p["name"],
                            hours=p["hours"], seq=n))
    db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={lv}&apreset={added}", status_code=303)


# ---------------- กรอกผลการเรียน ----------------
def _keep_max(subj, assignments) -> float:
    """คะแนนเก็บเต็มที่ใช้จริง: ถ้ามีชิ้นงาน = ผลรวมคะแนนเต็มทุกชิ้น, ไม่งั้นใช้ mid_max ของวิชา"""
    if assignments:
        return round(sum((a.max_score or 0) for a in assignments), 2)
    return float(subj.mid_max if (subj.mid_max or 0) > 0 else 70)


def _recompute_score(row, subj, keep_max):
    """คำนวณคะแนนรวม + เกรด จาก score_mid/score_final ที่มีอยู่ในแถว (เกรดที่แก้มือคงไว้)"""
    fmax = subj.final_max if (subj.final_max or 0) > 0 else 30
    mid, fin = row.score_mid, row.score_final
    total = None
    if mid is not None or fin is not None:
        total = (mid or 0) + (fin or 0)
    row.score = total
    return total, (keep_max + fmax)


@router.get("/academic/grades", response_class=HTMLResponse)
def grades_page(request: Request, db: Session = Depends(get_db), cid: int | None = None,
                sid: int | None = None, term: int | None = None, year: int | None = None):
    y = year or current_academic_year()
    sc = _scope(request, db)
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        classes = [c for c in classes if c.id in sc.teach_class_ids]
    c = db.get(AcadClass, cid) if cid else None
    if c and sc.is_teacher and c.id not in sc.teach_class_ids:
        return _deny()
    subjects, students, scores, subj = [], [], {}, None
    assignments, pieces, midterm, item_scores, keep_max = [], [], None, {}, 0
    sec, sel_term, annual = False, (term if term in (1, 2) else 1), {}
    if c:
        subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                    .order_by(AcadSubject.seq, AcadSubject.code).all())
        if sc.is_teacher:
            subjects = [x for x in subjects if (c.id, x.id) in sc.teach_pairs]
        subj = db.get(AcadSubject, sid) if sid else None
        # กันวิชาที่ค้างมาจากห้องก่อนหน้า (คนละระดับชั้น) -> ไม่แสดงวิชาที่ไม่ใช่ของห้องนี้
        if subj and subj.id not in {x.id for x in subjects}:
            subj = None
        if subj:
            # มัธยม: ตัดเกรดต่อเทอม (subject.term = 1/2) · ประถม: กรอก 2 เทอม เฉลี่ยเป็นเกรดรายปี
            sec = is_secondary(subj.level)
            sel_term = term if term in (1, 2) else 1
            t = (subj.term if subj.term in (1, 2) else 1) if sec else sel_term
            students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
            scores = {s.acad_student_id: s for s in
                      db.query(AcadScore).filter_by(subject_id=subj.id, term=t).all()}
            # ชิ้นงานเก็บคะแนน (ชิ้นงาน + สอบกลางภาค) ของวิชานี้
            assignments = (db.query(AcadAssignment)
                           .filter_by(subject_id=subj.id, term=t)
                           .order_by(AcadAssignment.seq, AcadAssignment.id).all())
            # สอบกลางภาคต้องมีเสมอ (สร้างอัตโนมัติถ้ายังไม่มี) - ไม่ต้องให้ครูติ๊กเพิ่มเอง
            midterm = next((a for a in assignments if a.is_midterm), None)
            if midterm is None:
                midterm = AcadAssignment(subject_id=subj.id, term=t, name="สอบกลางภาค",
                                         max_score=30, is_midterm=True, seq=999)
                db.add(midterm); db.commit()
                assignments.append(midterm)
            # ชิ้นงาน (ไม่ใช่สอบกลางภาค) เรียงตาม seq · คอลัมน์คะแนน = ชิ้นงาน + สอบกลางภาค
            pieces = [a for a in assignments if not a.is_midterm]
            assignments = pieces + [midterm]
            keep_max = round(sum((a.max_score or 0) for a in assignments), 2)
            aids = [a.id for a in assignments]
            for r in (db.query(AcadAssignmentScore)
                      .filter(AcadAssignmentScore.assignment_id.in_(aids)).all()):
                item_scores[(r.acad_student_id, r.assignment_id)] = r.score
            # ประถม: โหลดคะแนนทั้ง 2 ภาค เพื่อโชว์เฉลี่ยร้อยละ + เกรดรายปี (สด)
            if not sec:
                fmaxv = subj.final_max if (subj.final_max or 0) > 0 else 30
                dnm = {}
                for tno in (1, 2):
                    km = _keep_max(subj, db.query(AcadAssignment)
                                   .filter_by(subject_id=subj.id, term=tno).all())
                    dnm[tno] = (km + fmaxv) or 100
                both = {(x.acad_student_id, x.term): x for x in
                        db.query(AcadScore).filter(AcadScore.subject_id == subj.id,
                                                   AcadScore.term.in_([1, 2])).all()}
                for s in students:
                    def pc(tno):
                        r = both.get((s.id, tno))
                        return round(r.score * 100.0 / dnm[tno], 1) if (r and r.score is not None) else None
                    p1, p2 = pc(1), pc(2)
                    avg = round((p1 + p2) / 2.0, 2) if (p1 is not None and p2 is not None) else None
                    annual[s.id] = {"t1": p1, "t2": p2, "avg": avg,
                                    "grade": grade_of(avg) if avg is not None else ""}
    return templates.TemplateResponse("academic_grades.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "subjects": subjects, "subj": subj,
        "students": students, "scores": scores, "class_label": _class_label,
        "term_label": term_label, "grades": GRADE_CHOICES, "is_sec": sec,
        "sel_term": sel_term, "annual": annual,
        "assignments": assignments, "pieces": pieces, "midterm": midterm,
        "item_scores": item_scores, "keep_max": keep_max,
    })


@router.post("/academic/assignments/save")
async def assignments_save(request: Request, db: Session = Depends(get_db),
                           cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """จัดการชิ้นงานเก็บคะแนนของรายวิชา · ชิ้นงานส่งเป็น array (aid/aname/amax)
    สอบกลางภาคมีเสมอ (mid_max) แก้ได้แต่ลบไม่ได้ · ชิ้นงานที่ไม่ถูกส่งมา = ถูกลบ"""
    if not _scope(request, db).can_teach(_to_int(cid, 0), _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not subj:
        return RedirectResponse("/academic/grades", status_code=303)
    sec = is_secondary(subj.level)
    sel_term = _to_int(form.get("term", ""), 0)
    sel_term = sel_term if sel_term in (1, 2) else 1
    t = (subj.term if subj.term in (1, 2) else 1) if sec else sel_term
    existing = {a.id: a for a in db.query(AcadAssignment).filter_by(subject_id=subj.id, term=t).all()}

    # ----- สอบกลางภาค: มีเสมอ (สร้างถ้ายังไม่มี) แก้คะแนนเต็มได้ -----
    midterm = next((a for a in existing.values() if a.is_midterm), None)
    if midterm is None:
        midterm = AcadAssignment(subject_id=subj.id, term=t, name="สอบกลางภาค",
                                 is_midterm=True, seq=999)
        db.add(midterm)
    midterm.name = "สอบกลางภาค"
    midterm.max_score = max(0.0, _to_float(form.get("mid_max", ""), 30.0) or 0.0)

    # ----- ชิ้นงาน (array คู่ขนาน) -----
    aids = form.getlist("aid")
    anames = form.getlist("aname")
    amaxs = form.getlist("amax")
    kept = set()
    for i, raw_id in enumerate(aids):
        name = (anames[i] if i < len(anames) else "").strip()
        mx = max(0.0, _to_float(amaxs[i] if i < len(amaxs) else "", 10.0) or 0.0)
        aid = _to_int(raw_id, 0)
        a = existing.get(aid) if aid else None
        if a and a.is_midterm:                        # กันแก้สอบกลางภาคผ่านช่องชิ้นงาน
            continue
        if not name:                                  # แถวว่าง = ข้าม (ถือว่าลบถ้าเป็นของเดิม)
            continue
        if a:
            a.name, a.max_score, a.seq = name, mx, i
            kept.add(a.id)
        else:
            db.add(AcadAssignment(subject_id=subj.id, term=t, name=name,
                                  max_score=mx, is_midterm=False, seq=i))
    # ลบชิ้นงานเดิมที่ไม่ได้ส่งกลับมา (ไม่แตะสอบกลางภาค)
    for a in existing.values():
        if (not a.is_midterm) and a.id not in kept:
            db.delete(a)
    db.commit()
    tq = f"&term={sel_term}" if not sec else ""
    return RedirectResponse(f"/academic/grades?cid={cid}&sid={sid}{tq}&saved=1", status_code=303)


@router.post("/academic/grades/save")
async def grades_save(request: Request, db: Session = Depends(get_db),
                      cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """บันทึกคะแนนทั้งห้องในครั้งเดียว · เกรดคำนวณจากคะแนนรวม (กรอกเกรดเองทับได้)
    ถ้าวิชานี้มีชิ้นงาน คะแนนเก็บ = ผลรวมคะแนนรายชิ้น (กรอกช่องชิ้นงาน ไม่กรอกช่องเก็บรวม)"""
    if not _scope(request, db).can_teach(_to_int(cid, 0), _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not subj:
        return RedirectResponse("/academic/grades", status_code=303)
    sec = is_secondary(subj.level)
    sel_term = _to_int(form.get("term", ""), 0)
    sel_term = sel_term if sel_term in (1, 2) else 1
    t = (subj.term if subj.term in (1, 2) else 1) if sec else sel_term
    fmax = subj.final_max if (subj.final_max or 0) > 0 else 30
    assignments = (db.query(AcadAssignment).filter_by(subject_id=subj.id, term=t)
                   .order_by(AcadAssignment.seq, AcadAssignment.id).all())
    keep_max = _keep_max(subj, assignments)
    amax = {a.id: (a.max_score or 0) for a in assignments}
    cur = {s.acad_student_id: s for s in
           db.query(AcadScore).filter_by(subject_id=subj.id, term=t).all()}
    klass = db.get(AcadClass, _to_int(cid, 0))
    sids = ([s.id for s in klass.students] if klass else
            [_to_int(k[4:], 0) for k in form.keys() if k.startswith("fin_")])

    if assignments:
        # โหลด/อัปเดตคะแนนรายชิ้น แล้วรวมเป็นคะแนนเก็บ
        aids = list(amax.keys())
        item_rows = {(r.acad_student_id, r.assignment_id): r for r in
                     db.query(AcadAssignmentScore)
                     .filter(AcadAssignmentScore.assignment_id.in_(aids)).all()}
        for aid_s in sids:
            keep_sum, has_item = 0.0, False
            for a_id in aids:
                raw = form.get(f"item_{aid_s}_{a_id}", None)
                if raw is None:
                    continue
                v = _to_float(raw, None)
                if v is not None:
                    v = max(0.0, min(v, float(amax[a_id])))    # กันเกินเต็มของชิ้น
                    keep_sum += v
                    has_item = True
                r = item_rows.get((aid_s, a_id))
                if r is None:
                    r = AcadAssignmentScore(acad_student_id=aid_s, assignment_id=a_id)
                    db.add(r)
                r.score = v
            fin = _to_float(form.get(f"fin_{aid_s}", ""), None)
            if fin is not None:
                fin = max(0.0, min(fin, float(fmax)))
            manual = (form.get(f"grade_{aid_s}", "") or "").strip()
            mid = round(keep_sum, 2) if has_item else None
            row = cur.get(aid_s)
            if not row:
                row = AcadScore(acad_student_id=aid_s, subject_id=subj.id, term=t)
                db.add(row)
            row.score_mid, row.score_final = mid, fin
            total, denom = _recompute_score(row, subj, keep_max)
            pct = None if total is None else (total * 100.0 / denom if denom else None)
            row.grade = manual or grade_of(pct)
    else:
        # โหมดเดิม: กรอกคะแนนเก็บรวมเป็นก้อนเดียว
        mmax = subj.mid_max if (subj.mid_max or 0) > 0 else 70
        for aid_s in sids:
            if form.get(f"mid_{aid_s}", None) is None and form.get(f"fin_{aid_s}", None) is None:
                continue
            mid = _to_float(form.get(f"mid_{aid_s}", ""), None)
            fin = _to_float(form.get(f"fin_{aid_s}", ""), None)
            if mid is not None:
                mid = max(0.0, min(mid, float(mmax)))
            if fin is not None:
                fin = max(0.0, min(fin, float(fmax)))
            manual = (form.get(f"grade_{aid_s}", "") or "").strip()
            total = None
            if mid is not None or fin is not None:
                total = (mid or 0) + (fin or 0)
            row = cur.get(aid_s)
            if not row:
                row = AcadScore(acad_student_id=aid_s, subject_id=subj.id, term=t)
                db.add(row)
            row.score_mid, row.score_final, row.score = mid, fin, total
            pct = None if total is None else (total * 100.0 / (mmax + fmax))
            row.grade = manual or grade_of(pct)
    db.commit()

    # ประถม: คิดเกรด "รายปี" = เฉลี่ย "ร้อยละ" ของ 2 ภาค -> เก็บที่ term=0 (ที่ ปพ.5/ปพ.6 อ่าน)
    if not sec and subj:
        fmaxv = subj.final_max if (subj.final_max or 0) > 0 else 30
        denom_t = {}
        for tno in (1, 2):
            km = _keep_max(subj, db.query(AcadAssignment)
                           .filter_by(subject_id=subj.id, term=tno).all())
            denom_t[tno] = (km + fmaxv) or 100
        by_stu = {}
        for x in (db.query(AcadScore).filter(AcadScore.subject_id == subj.id,
                                             AcadScore.term.in_([1, 2])).all()):
            by_stu.setdefault(x.acad_student_id, {})[x.term] = x
        ann = {x.acad_student_id: x for x in
               db.query(AcadScore).filter_by(subject_id=subj.id, term=0).all()}
        for aid_s, terms in by_stu.items():
            def pct(tno):
                r = terms.get(tno)
                return (r.score * 100.0 / denom_t[tno]) if (r and r.score is not None) else None
            p1, p2 = pct(1), pct(2)
            have = [p for p in (p1, p2) if p is not None]
            row = ann.get(aid_s)
            if len(have) == 2:
                avg = round((p1 + p2) / 2.0, 2)      # เฉลี่ยร้อยละ 2 ภาค
                if not row:
                    row = AcadScore(acad_student_id=aid_s, subject_id=subj.id, term=0)
                    db.add(row); ann[aid_s] = row
                row.score = avg                       # เก็บเป็นร้อยละ (0-100)
                row.grade = grade_of(avg)
            elif row:                                # ยังไม่ครบ 2 ภาค -> ล้างเกรดรายปีกันค้าง
                row.score = None; row.grade = ""
        db.commit()
    tq = f"&term={sel_term}" if not sec else ""
    return RedirectResponse(f"/academic/grades?cid={cid}&sid={sid}{tq}&saved=1", status_code=303)


# ---------------- ประเมินตัวชี้วัดรายวิชา (หลักสูตรแกนกลาง 2551) ----------------
@router.get("/academic/indicators", response_class=HTMLResponse)
def indicators_page(request: Request, db: Session = Depends(get_db),
                    cid: int | None = None, sid: int | None = None, year: int | None = None):
    y = year or current_academic_year()
    sc = _scope(request, db)
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        classes = [x for x in classes if x.id in sc.teach_class_ids]
    c = db.get(AcadClass, cid) if cid else None
    if c and sc.is_teacher and c.id not in sc.teach_class_ids:
        return _deny()
    subjects, students, subj, inds, all_inds, picked, results = [], [], None, [], [], set(), {}
    if c:
        subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                    .order_by(AcadSubject.seq, AcadSubject.code).all())
        if sc.is_teacher:
            subjects = [x for x in subjects if (c.id, x.id) in sc.teach_pairs]
        subj = db.get(AcadSubject, sid) if sid else None
        if subj and subj.id not in {x.id for x in subjects}:
            subj = None
        if subj:
            students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
            all_inds = indicators_for(subj.learn_group, subj.level)   # ทั้งหมด (สำหรับกล่องเลือก)
            inds = selected_indicators(subj)                          # เฉพาะที่ครูเลือกใช้ (กรอกคะแนน)
            picked = {it["code"] for it in inds}
            if inds and students:
                sids = [s.id for s in students]
                for r in (db.query(AcadIndicatorResult)
                          .filter(AcadIndicatorResult.subject_id == subj.id,
                                  AcadIndicatorResult.acad_student_id.in_(sids)).all()):
                    results[(r.acad_student_id, r.code)] = (
                        r.score if r.score is not None else (3 if r.passed else None))
    return templates.TemplateResponse("academic_indicators.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "subjects": subjects, "subj": subj,
        "students": students, "class_label": _class_label, "term_label": term_label,
        "indicators": inds, "all_indicators": all_inds, "picked": picked, "results": results,
    })


@router.post("/academic/indicators/pick")
async def indicators_pick(request: Request, db: Session = Depends(get_db),
                          cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """บันทึกรายการตัวชี้วัดที่ครูเลือกใช้ (checkbox 'pick' = code) · เก็บ CSV คั่นด้วย |"""
    if not _scope(request, db).can_teach(_to_int(cid, 0), _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not subj:
        return RedirectResponse("/academic/indicators", status_code=303)
    valid = {it["code"] for it in indicators_for(subj.learn_group, subj.level)}
    chosen = [code for code in form.getlist("pick") if code in valid]
    subj.indicator_codes = "|".join(chosen)
    db.commit()
    return RedirectResponse(f"/academic/indicators?cid={cid}&sid={sid}&saved=1", status_code=303)


@router.post("/academic/indicators/save")
async def indicators_save(request: Request, db: Session = Depends(get_db),
                          cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """บันทึกผลประเมินตัวชี้วัดทั้งห้อง · คะแนน 0-3 ต่อข้อ ช่อง 'sc_<sid>_<idx>' · ผ่าน = score>=1"""
    if not _scope(request, db).can_teach(_to_int(cid, 0), _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    subj = db.get(AcadSubject, _to_int(sid, 0))
    c = db.get(AcadClass, _to_int(cid, 0))
    if not subj or not c:
        return RedirectResponse("/academic/indicators", status_code=303)
    inds = selected_indicators(subj)          # กรอก/บันทึกเฉพาะตัวชี้วัดที่เลือกใช้
    codes = [it["code"] for it in inds]
    sids = [s.id for s in c.students]
    cur = {}
    if sids:
        for r in (db.query(AcadIndicatorResult)
                  .filter(AcadIndicatorResult.subject_id == subj.id,
                          AcadIndicatorResult.acad_student_id.in_(sids)).all()):
            cur[(r.acad_student_id, r.code)] = r
    for s in c.students:
        for i, code in enumerate(codes):
            raw = form.get(f"sc_{s.id}_{i}", "")
            sc = _to_int(raw, None)
            if sc is not None:
                sc = max(0, min(3, sc))
            row = cur.get((s.id, code))
            if not row:
                row = AcadIndicatorResult(acad_student_id=s.id, subject_id=subj.id, code=code)
                db.add(row)
            row.score = sc
            row.passed = (sc is not None and sc >= 1)
    db.commit()
    return RedirectResponse(f"/academic/indicators?cid={cid}&sid={sid}&saved=1", status_code=303)


# ---------------- ประเมิน (ที่ ปพ.6 ต้องใช้) ----------------
@router.get("/academic/eval", response_class=HTMLResponse)
def eval_page(request: Request, db: Session = Depends(get_db),
              cid: int | None = None, year: int | None = None):
    y = year or current_academic_year()
    sc = _scope(request, db)
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        classes = [x for x in classes if x.id in sc.homeroom_ids]
    c = db.get(AcadClass, cid) if cid else None
    if c and not sc.can_homeroom(cid):
        return _deny()
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    eff = {s.id: effective_eval(s, db) for s in students}
    # จำนวนวิชาที่ประเมินคุณลักษณะ/อ่านคิดเขียนแล้ว (เทียบกับวิชาทั้งหมด) - รายคน
    # ผลรวมจะโชว์ต่อเมื่อประเมินครบทุกวิชา (กันโชว์ 'ดีเยี่ยม' ทั้งที่ประเมินวิชาเดียว)
    from app.models import AcadCharEval, AcadReadEval
    eval_subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level).all() if c else [])
    n_eval_subj = len(eval_subjects)
    char_done = {s.id: 0 for s in students}
    read_done = {s.id: 0 for s in students}
    if eval_subjects and students:
        _subids = [x.id for x in eval_subjects]
        _sids = [s.id for s in students]
        for r in (db.query(AcadCharEval)
                  .filter(AcadCharEval.subject_id.in_(_subids),
                          AcadCharEval.acad_student_id.in_(_sids)).all()):
            char_done[r.acad_student_id] = char_done.get(r.acad_student_id, 0) + 1
        for r in (db.query(AcadReadEval)
                  .filter(AcadReadEval.subject_id.in_(_subids),
                          AcadReadEval.acad_student_id.in_(_sids)).all()):
            read_done[r.acad_student_id] = read_done.get(r.acad_student_id, 0) + 1
    # กิจกรรมพัฒนาผู้เรียนที่ตั้งไว้ + ผลรายคน + สรุปรวม
    activities = activities_for(c.year, c.level, db) if c else []
    act_res, act_sum = {}, {}
    if activities and students:
        sids = [s.id for s in students]
        for r in (db.query(AcadActivityResult)
                  .filter(AcadActivityResult.acad_student_id.in_(sids)).all()):
            act_res[(r.acad_student_id, r.activity_id)] = (r.result or "").strip()
        act_sum = {s.id: activity_summary(s, db) for s in students}
    # O-NET เฉพาะชั้นปลายทาง (ป.6/ม.3/ม.6)
    onet_exit = bool(c) and is_exit_level(c.level)
    onet = {s.id: onet_for(s, db) for s in students} if onet_exit else {}
    return templates.TemplateResponse("academic_eval.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "students": students, "class_label": _class_label,
        "quality": QUALITY_LEVELS, "passfail": PASS_FAIL, "eff": eff,
        "n_eval_subj": n_eval_subj, "char_done": char_done, "read_done": read_done,
        "activities": activities, "act_res": act_res, "act_sum": act_sum,
        "onet_exit": onet_exit, "onet_subjects": ONET_SUBJECTS, "onet": onet,
    })


@router.post("/academic/eval/save")
async def eval_save(request: Request, db: Session = Depends(get_db), cid: str = Form("")):
    if not _scope(request, db).can_homeroom(_to_int(cid, 0)):
        return _deny()
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    if not c:
        return RedirectResponse("/academic/eval", status_code=303)
    # หน้านี้กรอกแค่กิจกรรมพัฒนาผู้เรียนแล้ว - คุณ/อ่าน มาจากประเมินรายวิชา (คำนวณ)
    # · ความเห็นครู/ผู้ปกครองเขียนมือในสมุดพก · เวลาเรียนอยู่หน้าเวลาเรียน
    # ผลกิจกรรมรายคน x รายกิจกรรม (upsert)
    acts = activities_for(c.year, c.level, db)
    if acts:
        sids = [s.id for s in c.students]
        cur_res = {}
        if sids:
            for r in (db.query(AcadActivityResult)
                      .filter(AcadActivityResult.acad_student_id.in_(sids)).all()):
                cur_res[(r.acad_student_id, r.activity_id)] = r
        for s in c.students:
            for a in acts:
                v = (form.get(f"act_{s.id}_{a.id}", "") or "").strip()
                row = cur_res.get((s.id, a.id))
                if row:
                    row.result = v
                elif v:
                    db.add(AcadActivityResult(acad_student_id=s.id, activity_id=a.id, result=v))
    # O-NET (เฉพาะชั้นปลายทาง) upsert ตาม นักเรียน x วิชา
    if is_exit_level(c.level):
        sids = [s.id for s in c.students]
        cur_onet = {}
        if sids:
            for r in db.query(AcadOnet).filter(AcadOnet.acad_student_id.in_(sids)).all():
                cur_onet[(r.acad_student_id, r.subject)] = r
        for s in c.students:
            for subj in ONET_SUBJECTS:
                full = (form.get(f"onet_{s.id}_{subj}_full", "") or "").strip()
                sc = (form.get(f"onet_{s.id}_{subj}_score", "") or "").strip()
                row = cur_onet.get((s.id, subj))
                if row:
                    row.full_score = _to_float(full, None) if full else None
                    row.score = _to_float(sc, None) if sc else None
                elif full or sc:
                    db.add(AcadOnet(acad_student_id=s.id, subject=subj,
                                    full_score=_to_float(full, None) if full else None,
                                    score=_to_float(sc, None) if sc else None))
    db.commit()
    return RedirectResponse(f"/academic/eval?cid={c.id}&saved=1", status_code=303)


# ---------------- ประเมินละเอียดรายวิชา (คุณลักษณะฯ / อ่านคิดเขียน) ----------------
@router.get("/academic/assess", response_class=HTMLResponse)
def assess_page(request: Request, db: Session = Depends(get_db),
                cid: int | None = None, sid: int | None = None,
                kind: str = "char", year: int | None = None, term: int | None = None):
    y = year or current_academic_year()
    kind = "read" if kind == "read" else "char"
    sc = _scope(request, db)
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        classes = [x for x in classes if x.id in sc.teach_class_ids]
    c = db.get(AcadClass, cid) if cid else None
    if c and sc.is_teacher and c.id not in sc.teach_class_ids:
        return _deny()
    all_subjects, terms, has_terms, subjects = [], [], False, []
    if c:
        all_subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                        .order_by(AcadSubject.seq, AcadSubject.code).all())
        if sc.is_teacher:
            all_subjects = [x for x in all_subjects if (c.id, x.id) in sc.teach_pairs]
        terms = sorted({s.term or 0 for s in all_subjects})
        # แยกเลือกภาคเรียนก่อน เมื่อรายวิชามีทั้งภาค 1 และ 2 (มัธยม) - ประถม (ทั้งปี) ไม่ต้องเลือก
        has_terms = len([t for t in terms if t in (1, 2)]) > 1
        if has_terms:
            subjects = [s for s in all_subjects if (s.term or 0) == term] if term in (1, 2) else []
        else:
            subjects = all_subjects
    subj = db.get(AcadSubject, sid) if sid else None
    if subj and c and (subj.year != c.year or subj.level != c.level):
        subj = None                        # กันเลือกวิชาข้ามชั้น
    if subj and has_terms and (subj.term or 0) != term:
        subj = None                        # วิชาไม่ตรงภาคเรียนที่เลือก
    # ประถม: คุณลักษณะ/อ่านคิดเขียน ประเมินรายภาคเรียน (เลือกภาค 1/2) · มัธยม: ผูกกับวิชาที่แยกภาคอยู่แล้ว
    sec = is_secondary(c.level) if c else False
    prathom_term = (term if term in (1, 2) else 1) if (c and not sec) else None
    eval_term = prathom_term if (c and not sec) else 0
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    Model = AcadReadEval if kind == "read" else AcadCharEval
    fields = [f for f, _ in READ_DOMAINS] if kind == "read" else CHAR_FIELDS
    labels = [lb for _, lb in READ_DOMAINS] if kind == "read" else CHAR_ITEMS
    rows = {}
    if subj:
        rows = {r.acad_student_id: r for r in
                db.query(Model).filter_by(subject_id=subj.id, term=eval_term).all()}
    return templates.TemplateResponse("academic_assess.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "subjects": subjects, "subj": subj, "kind": kind,
        "students": students, "rows": rows, "fields": fields, "labels": labels,
        "terms": terms, "term": term, "has_terms": has_terms,
        "sec": sec, "prathom_term": prathom_term, "eval_term": eval_term,
        "class_label": _class_label, "term_label": term_label,
    })


@router.post("/academic/assess/save")
async def assess_save(request: Request, db: Session = Depends(get_db),
                      cid: str = Form(""), sid: str = Form(""), kind: str = Form("char"),
                      eval_term: str = Form("0")):
    if not _scope(request, db).can_teach(_to_int(cid, 0), _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    kind = "read" if kind == "read" else "char"
    c = db.get(AcadClass, _to_int(cid, 0))
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not c or not subj:
        return RedirectResponse("/academic/assess", status_code=303)
    et = _to_int(eval_term, 0)
    et = et if et in (1, 2) else 0
    Model = AcadReadEval if kind == "read" else AcadCharEval
    fields = [f for f, _ in READ_DOMAINS] if kind == "read" else CHAR_FIELDS
    cur = {r.acad_student_id: r for r in
           db.query(Model).filter_by(subject_id=subj.id, term=et).all()}
    for s in c.students:
        r = cur.get(s.id)
        if not r:
            r = Model(acad_student_id=s.id, subject_id=subj.id, term=et)
            db.add(r)
        for f in fields:
            v = _to_int(form.get(f"{f}_{s.id}", ""), None)
            if v is not None:
                v = max(0, min(3, v))      # คะแนน 0-3 เท่านั้น
            setattr(r, f, v)
    db.commit()
    tq = f"&term={et}" if et in (1, 2) else ""
    return RedirectResponse(f"/academic/assess?cid={c.id}&sid={subj.id}&kind={kind}{tq}&saved=1",
                            status_code=303)


# ---------------- ปฏิทินการศึกษา ----------------
@router.get("/academic/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    y = year or current_academic_year()
    saved = {r.month: parse_days_csv(r.days_csv)
             for r in db.query(AcadCalendar).filter_by(year=y).all()}
    hol = holiday_map(y, db)
    setting = db.query(AcadYearSetting).filter_by(year=y).first()
    months = []
    for mnum, mshort in TH_MONTHS:
        wd = month_weekdays(y, mnum)
        # เดือนที่ยังไม่เคยตั้ง -> ใช้ที่ระบบแนะนำ (จ.-ศ. ลบวันหยุด ลบวันนอกเทอม)
        open_days = saved[mnum] if mnum in saved else auto_open_days(y, mnum, db)
        months.append({
            "num": mnum, "short": mshort, "name": TH_MONTH_FULL[mnum],
            "days": [{"d": d, "wd": wd[d], "open": d in open_days,
                      "hol": hol.get((mnum, d), ""),
                      "off": not in_term(y, mnum, d, setting)} for d in sorted(wd)],
            # ช่องว่างนำหน้าให้วันที่ 1 ตกคอลัมน์วันที่ถูกต้อง (จันทร์=คอลัมน์แรก)
            "lead": TH_WEEKDAYS.index(wd[1]),
            "configured": mnum in saved,
        })
    holidays = sorted(db.query(AcadHoliday).filter_by(year=y).all(),
                      key=lambda r: (r.month is None, TH_MONTH_ORDER.get(r.month or 0, 99),
                                     r.day or 0))
    return templates.TemplateResponse("academic_calendar.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "months": months, "any_set": bool(saved), "holidays": holidays,
        "setting": setting, "be_date": be_date_input, "month_list": TH_MONTHS,
        "lunar_names": LUNAR_HOLIDAY_NAMES,
    })


@router.post("/academic/calendar/terms")
def calendar_terms(request: Request, db: Session = Depends(get_db), year: str = Form(""),
                   t1_start: str = Form(""), t1_end: str = Form(""),
                   t2_start: str = Form(""), t2_end: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    row = db.query(AcadYearSetting).filter_by(year=y).first()
    if not row:
        row = AcadYearSetting(year=y)
        db.add(row)
    row.t1_start = parse_be_date(t1_start)
    row.t1_end = parse_be_date(t1_end)
    row.t2_start = parse_be_date(t2_start)
    row.t2_end = parse_be_date(t2_end)
    db.commit()
    return RedirectResponse(f"/academic/calendar?year={y}&saved=1", status_code=303)


@router.post("/academic/calendar/holidays")
async def calendar_holidays(request: Request, db: Session = Depends(get_db),
                            year: str = Form("")):
    """บันทึกตารางวันหยุดทั้งชุด (แก้/ลบแถวเดิม + เพิ่มแถวใหม่จากช่องท้ายตาราง)"""
    if _scope(request, db).is_teacher:
        return _deny()
    form = await request.form()
    y = _to_int(year, 0) or current_academic_year()
    for r in db.query(AcadHoliday).filter_by(year=y).all():
        if form.get(f"del_{r.id}"):
            db.delete(r)
            continue
        r.month = _to_int(form.get(f"m_{r.id}", ""), None) or None
        r.day = _to_int(form.get(f"d_{r.id}", ""), None) or None
        r.name = (form.get(f"n_{r.id}", "") or "").strip()
    nm = (form.get("new_name", "") or "").strip()
    nmm = _to_int(form.get("new_month", ""), None)
    nmd = _to_int(form.get("new_day", ""), None)
    if nm and nmm and nmd:
        db.add(AcadHoliday(year=y, month=nmm, day=nmd, name=nm, kind="other"))
    db.commit()
    return RedirectResponse(f"/academic/calendar?year={y}&saved=1", status_code=303)


@router.post("/academic/calendar/seed-holidays")
def calendar_seed_holidays(request: Request, db: Session = Depends(get_db), year: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    n = seed_fixed_holidays(y, db)
    return RedirectResponse(f"/academic/calendar?year={y}&seeded={n}", status_code=303)


@router.post("/academic/calendar/autofill")
def calendar_autofill(request: Request, db: Session = Depends(get_db), year: str = Form("")):
    """เติมวันเรียนทั้งปีจาก จ.-ศ. ลบวันหยุด ลบวันนอกภาคเรียน
    คำนวณฝั่งเซิร์ฟเวอร์เพราะต้องใช้ข้อมูลวันหยุด/ภาคเรียนจากฐานข้อมูล"""
    if _scope(request, db).is_teacher:
        return _deny()
    y = _to_int(year, 0) or current_academic_year()
    cur = {r.month: r for r in db.query(AcadCalendar).filter_by(year=y).all()}
    for mnum, _short in TH_MONTHS:
        row = cur.get(mnum)
        if not row:
            row = AcadCalendar(year=y, month=mnum)
            db.add(row)
        row.days_csv = ",".join(str(d) for d in auto_open_days(y, mnum, db))
    db.commit()
    return RedirectResponse(f"/academic/calendar?year={y}&filled=1", status_code=303)


@router.post("/academic/calendar/save")
async def calendar_save(request: Request, db: Session = Depends(get_db), year: str = Form("")):
    if _scope(request, db).is_teacher:
        return _deny()
    form = await request.form()
    y = _to_int(year, 0) or current_academic_year()
    cur = {r.month: r for r in db.query(AcadCalendar).filter_by(year=y).all()}
    for mnum, _short in TH_MONTHS:
        row = cur.get(mnum)
        if not row:
            row = AcadCalendar(year=y, month=mnum)
            db.add(row)
        days = parse_days_csv(form.get(f"m_{mnum}", ""))
        row.days_csv = ",".join(str(d) for d in days)
    db.commit()
    return RedirectResponse(f"/academic/calendar?year={y}&saved=1", status_code=303)


# ---------------- เวลาเรียน (สรุปรายเดือน + เช็กชื่อรายวัน) ----------------
@router.get("/academic/attendance", response_class=HTMLResponse)
def attendance_page(request: Request, db: Session = Depends(get_db),
                    cid: int | None = None, year: int | None = None,
                    month: int | None = None, sid: int | None = None,
                    mode: str | None = None):
    y = year or current_academic_year()
    school = get_school(db)
    sc = _scope(request, db)
    # หน้าเลือกโหมด (2 การ์ด): เช็กโดยรวม (รายห้อง/โฮมรูม) หรือ เช็กแยกรายวิชา
    if mode not in ("overall", "subject"):
        return templates.TemplateResponse("academic_attendance_home.html", {
            "request": request, "school": school, "year": y,
            "is_teacher": sc.is_teacher,
            "has_homeroom": (not sc.is_teacher) or bool(sc.homeroom_ids),
            "has_subject": (not sc.is_teacher) or bool(sc.teach_pairs),
        })
    by_subj = (mode == "subject")
    # ครู: เข้าตรงวิชา/ห้องเดียวที่ตัวเองมี (ตามที่เจ้าของสั่ง 'กดเข้ามาก็เจอวิชาตัวเองเลย')
    if sc.is_teacher and cid is None:
        cm = _current_month()
        if by_subj and len(sc.teach_pairs) == 1:
            # สอนวิชาเดียว -> เข้าหน้าเช็กชื่อรายวันเดือนปัจจุบันเลย (พร้อมติ๊กมา)
            (acid, asid) = next(iter(sc.teach_pairs))
            return RedirectResponse(
                f"/academic/attendance?mode=subject&cid={acid}&sid={asid}&month={cm}",
                status_code=303)
        if (not by_subj) and len(sc.homeroom_ids) == 1:
            return RedirectResponse(
                f"/academic/attendance?mode=overall&cid={next(iter(sc.homeroom_ids))}&month={cm}",
                status_code=303)
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    if sc.is_teacher:
        allowed = sc.teach_class_ids if by_subj else sc.homeroom_ids
        classes = [x for x in classes if x.id in allowed]
    c = db.get(AcadClass, cid) if cid else None
    if c and sc.is_teacher:
        allowed = sc.teach_class_ids if by_subj else sc.homeroom_ids
        if c.id not in allowed:
            return _deny()
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    cal = {r.month: parse_days_csv(r.days_csv)
           for r in db.query(AcadCalendar).filter_by(year=y).all()}
    # โหมดแยกรายวิชา: เลือกวิชาก่อน เช็กเวลาของวิชานั้น (subject_id) · โหมดโดยรวม: รายห้อง (subject_id NULL)
    subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                .order_by(AcadSubject.seq, AcadSubject.code).all()) if (c and by_subj) else []
    if sc.is_teacher and c and by_subj:
        subjects = [x for x in subjects if (c.id, x.id) in sc.teach_pairs]
    subj = db.get(AcadSubject, sid) if (by_subj and sid) else None
    if subj and sc.is_teacher and not sc.can_teach(c.id if c else 0, subj.id):
        subj = None
    home_pick = not by_subj
    att_sid = subj.id if (by_subj and subj) else None
    picked = (not by_subj) or (subj is not None)
    subj_cond = (AcadAttendance.subject_id == att_sid) if att_sid else AcadAttendance.subject_id.is_(None)
    rows = []
    if c and students and picked:
        rows = (db.query(AcadAttendance)
                .filter(AcadAttendance.acad_student_id.in_([s.id for s in students]), subj_cond).all())

    # ---- โหมดเช็กชื่อรายวัน ----
    if c and month in dict(TH_MONTHS) and picked:
        open_days = cal.get(month, [])
        wd = month_weekdays(y, month)
        marks = {a.acad_student_id: parse_marks(a.marks)
                 for a in rows if a.month == month}
        return templates.TemplateResponse("academic_attendance_day.html", {
            "request": request, "school": school, "year": y, "c": c,
            "students": students, "class_label": _class_label, "month": month,
            "month_name": TH_MONTH_FULL[month], "open_days": open_days,
            "weekdays": wd, "marks": marks, "states": MARK_STATES, "blank": MARK_BLANK,
            "by_subj": by_subj, "subj": subj, "home_pick": home_pick, "mode": mode,
        })

    # ---- โหมดสรุปรายเดือน ----
    opens, att, marked = {}, {}, set()
    if c:
        opens = {m.month: m.days_open for m in
                 db.query(AcadClassMonth).filter_by(class_id=c.id).all()}
        for a in rows:
            att[(a.acad_student_id, a.month)] = a.present
            if (a.marks or "").strip(MARK_BLANK):
                marked.add((a.acad_student_id, a.month))
    return templates.TemplateResponse("academic_attendance.html", {
        "request": request, "school": school, "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "students": students, "class_label": _class_label,
        "months": TH_MONTHS, "opens": opens, "att": att, "marked": marked,
        "cal_days": {m: len(d) for m, d in cal.items()}, "has_cal": bool(cal),
        "by_subj": by_subj, "subjects": subjects, "subj": subj,
        "picked": picked, "home_pick": home_pick, "mode": mode,
    })


@router.post("/academic/attendance/mode")
def attendance_mode(request: Request, db: Session = Depends(get_db),
                    by_subject: str = Form(""), cid: str = Form("")):
    """สลับโหมดเช็กเวลาเรียน รายห้อง <-> รายวิชา (ตั้งค่าทั้งโรงเรียน) จากหน้าเวลาเรียน"""
    if _scope(request, db).is_teacher:
        return _deny()
    s = get_school(db)
    s.attendance_by_subject = bool(by_subject)
    db.commit()
    q = f"?cid={cid}" if _to_int(cid, 0) else ""
    return RedirectResponse(f"/academic/attendance{q}", status_code=303)


@router.post("/academic/attendance/day-save")
async def attendance_day_save(request: Request, db: Session = Depends(get_db),
                              cid: str = Form(""), month: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """บันทึกเช็กชื่อรายวันของเดือนเดียว - เขียน marks + present ให้ตรงกัน"""
    if not _att_ok(_scope(request, db), _to_int(cid, 0), mode, _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    m = _to_int(month, 0)
    if not c or m not in dict(TH_MONTHS):
        return RedirectResponse("/academic/attendance", status_code=303)
    by_subj = (mode == "subject")
    att_sid = (_to_int(sid, 0) or None) if by_subj else None
    subj_cond = (AcadAttendance.subject_id == att_sid) if att_sid else AcadAttendance.subject_id.is_(None)
    cal = db.query(AcadCalendar).filter_by(year=c.year, month=m).first()
    open_days = parse_days_csv(cal.days_csv if cal else "")
    cur = {}
    sids = [s.id for s in c.students]
    if sids:
        cur = {a.acad_student_id: a for a in db.query(AcadAttendance)
               .filter(AcadAttendance.acad_student_id.in_(sids),
                       AcadAttendance.month == m, subj_cond).all()}
    for s in c.students:
        row = cur.get(s.id)
        if not row:
            row = AcadAttendance(acad_student_id=s.id, month=m, subject_id=att_sid)
            db.add(row)
        day_map = {}
        for d in open_days:                      # เก็บเฉพาะวันเปิดเรียนตามปฏิทิน
            ch = (form.get(f"d_{s.id}_{d}", "") or "").strip()
            if ch in MARK_CHARS:
                day_map[d] = ch
        row.marks = build_marks(day_map)
        row.present = count_marks(row.marks)["/"]
    # วันเปิดเรียนของห้องเดือนนี้ = จำนวนวันในปฏิทิน (ให้สรุป/เอกสารใช้ตัวเลขเดียวกัน)
    cm = db.query(AcadClassMonth).filter_by(class_id=c.id, month=m).first()
    if not cm:
        cm = AcadClassMonth(class_id=c.id, month=m)
        db.add(cm)
    cm.days_open = len(open_days) or None
    db.commit()
    sq = f"&mode={mode}" + (f"&sid={_to_int(sid, 0)}" if by_subj else "")
    return RedirectResponse(f"/academic/attendance?cid={c.id}&month={m}{sq}&saved=1",
                            status_code=303)


@router.post("/academic/attendance/save")
async def attendance_save(request: Request, db: Session = Depends(get_db),
                          cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    if not _att_ok(_scope(request, db), _to_int(cid, 0), mode, _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    if not c:
        return RedirectResponse("/academic/attendance", status_code=303)
    by_subj = (mode == "subject")
    att_sid = (_to_int(sid, 0) or None) if by_subj else None
    subj_cond = (AcadAttendance.subject_id == att_sid) if att_sid else AcadAttendance.subject_id.is_(None)
    # วันเปิดเรียนรายเดือนของห้อง
    curm = {m.month: m for m in db.query(AcadClassMonth).filter_by(class_id=c.id).all()}
    for mnum, _ in TH_MONTHS:
        row = curm.get(mnum)
        if not row:
            row = AcadClassMonth(class_id=c.id, month=mnum)
            db.add(row)
        row.days_open = _to_int(form.get(f"open_{mnum}", ""), None)
    # รายคน: รายเดือน + ยอดรวม + ป่วย/ลา/ขาด
    sids = [s.id for s in c.students]
    cura = {}
    if sids:
        for a in (db.query(AcadAttendance)
                  .filter(AcadAttendance.acad_student_id.in_(sids), subj_cond).all()):
            cura[(a.acad_student_id, a.month)] = a
    cure = {e.acad_student_id: e for e in db.query(AcadEval).join(AcadStudent)
            .filter(AcadStudent.class_id == c.id).all()}
    open_total = sum(v for v in
                     (_to_int(form.get(f"open_{m}", ""), None) for m, _ in TH_MONTHS)
                     if v is not None)
    for s in c.students:
        monthly = []
        for mnum, _ in TH_MONTHS:
            row = cura.get((s.id, mnum))
            if not row:
                row = AcadAttendance(acad_student_id=s.id, month=mnum, subject_id=att_sid)
                db.add(row)
            # เดือนที่เช็กชื่อรายวันไว้แล้ว ยอดมาจากการนับ marks - หน้าสรุปไม่ส่งช่องนั้นมา
            # (ถ้าเผลอทับ ตัวเลขบนหน้าจอจะไม่ตรงกับที่เอกสารใช้จริง)
            if row.id and (row.marks or "").strip(MARK_BLANK):
                if row.present is not None:
                    monthly.append(row.present)
                continue
            row.present = _to_int(form.get(f"p_{s.id}_{mnum}", ""), None)
            if row.present is not None:
                monthly.append(row.present)
        e = cure.get(s.id)
        if not e:
            e = AcadEval(acad_student_id=s.id)
            db.add(e)
        e.days_open = _to_int(form.get(f"dopen_{s.id}", ""), None) or (open_total or None)
        e.days_sick = _to_int(form.get(f"sick_{s.id}", ""), None)
        e.days_leave = _to_int(form.get(f"leave_{s.id}", ""), None)
        e.days_absent = _to_int(form.get(f"abs_{s.id}", ""), None)
        # มา(รวม) คิดฝั่งเซิร์ฟเวอร์ด้วย เผื่อ JS ไม่ทำงาน จะได้ไม่บันทึกเลขเก่าค้างไว้
        # ลำดับ: ผลรวมรายเดือน > วันเปิดเรียน ลบ ป่วย/ลา/ขาด > ค่าที่ส่งมา
        miss = sum(v for v in (e.days_sick, e.days_leave, e.days_absent) if v is not None)
        if monthly:
            e.days_present = sum(monthly)
        elif e.days_open:
            e.days_present = max(0, e.days_open - miss)
        else:
            e.days_present = _to_int(form.get(f"dpres_{s.id}", ""), None)
    db.commit()
    sq = f"&mode={mode}" + (f"&sid={_to_int(sid, 0)}" if by_subj else "")
    return RedirectResponse(f"/academic/attendance?cid={c.id}{sq}&saved=1", status_code=303)


@router.post("/academic/attendance/fill-year")
async def attendance_fill_year(request: Request, db: Session = Depends(get_db),
                               cid: str = Form(""), sid: str = Form(""), mode: str = Form("")):
    """ทุกคนมาเรียนทุกวันทั้งปี: เขียนเครื่องหมาย "มา" รายวันให้ครบทุกวันเปิดเรียน
    (เดือนที่มีปฏิทิน) + เติมยอดรายเดือน/รายปีให้ครบ · ป่วย/ลา/ขาด = 0
    เดือนที่ยังไม่มีปฏิทินแต่ครูพิมพ์จำนวนวันเปิดเรียนไว้ ใช้จำนวนนั้นเป็นยอด "มา" """
    if not _att_ok(_scope(request, db), _to_int(cid, 0), mode, _to_int(sid, 0)):
        return _deny()
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    if not c:
        return RedirectResponse("/academic/attendance", status_code=303)
    by_subj = (mode == "subject")
    att_sid = (_to_int(sid, 0) or None) if by_subj else None
    subj_cond = (AcadAttendance.subject_id == att_sid) if att_sid else AcadAttendance.subject_id.is_(None)
    cal = {r.month: parse_days_csv(r.days_csv)
           for r in db.query(AcadCalendar).filter_by(year=c.year).all()}
    # จำนวนวันเปิดเรียนต่อเดือน: ใช้ปฏิทินก่อน ไม่มีก็ใช้ค่าที่ครูพิมพ์ในฟอร์ม
    nday, marks_by_month = {}, {}
    for mnum, _ in TH_MONTHS:
        days = cal.get(mnum) or []
        if days:
            nday[mnum] = len(days)
            marks_by_month[mnum] = build_marks({d: "/" for d in days})
        else:
            typed = _to_int(form.get(f"open_{mnum}", ""), None)
            if typed:
                nday[mnum] = typed
    # วันเปิดเรียนรายเดือนของห้อง
    curm = {m.month: m for m in db.query(AcadClassMonth).filter_by(class_id=c.id).all()}
    for mnum, n in nday.items():
        row = curm.get(mnum)
        if not row:
            row = AcadClassMonth(class_id=c.id, month=mnum)
            db.add(row)
        row.days_open = n
    # รายคน
    sids = [s.id for s in c.students]
    cura = {}
    if sids:
        for a in (db.query(AcadAttendance)
                  .filter(AcadAttendance.acad_student_id.in_(sids), subj_cond).all()):
            cura[(a.acad_student_id, a.month)] = a
    cure = {e.acad_student_id: e for e in db.query(AcadEval).join(AcadStudent)
            .filter(AcadStudent.class_id == c.id).all()}
    total = sum(nday.values())
    for s in c.students:
        for mnum, n in nday.items():
            row = cura.get((s.id, mnum))
            if not row:
                row = AcadAttendance(acad_student_id=s.id, month=mnum, subject_id=att_sid)
                db.add(row)
            if mnum in marks_by_month:               # เดือนมีปฏิทิน -> เขียนมาร์ครายวันครบ
                row.marks = marks_by_month[mnum]
            row.present = n
        e = cure.get(s.id)
        if not e:
            e = AcadEval(acad_student_id=s.id)
            db.add(e)
        e.days_open = total or None
        e.days_present = total or None
        e.days_sick = e.days_leave = e.days_absent = 0
    db.commit()
    sq = f"&mode={mode}" + (f"&sid={_to_int(sid, 0)}" if by_subj else "")
    return RedirectResponse(f"/academic/attendance?cid={c.id}{sq}&saved=1", status_code=303)


# ---------------- เอกสาร ----------------
@router.get("/academic/classes/{cid}/pp5.docx")
def pp5_docx(cid: int, sid: int, request: Request, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp5
    c, subj = db.get(AcadClass, cid), db.get(AcadSubject, sid)
    if not c or not subj:
        return RedirectResponse("/academic/grades", status_code=303)
    if not _scope(request, db).can_teach(cid, sid):
        return _deny()
    return serve_generated(render_pp5(get_school(db), c, subj, db), _DOCX)


@router.get("/academic/classes/{cid}/pp5-book.docx")
def pp5_book_docx(cid: int, request: Request, term: int = 0, db: Session = Depends(get_db)):
    """ปพ.5 ทั้งเล่ม · มัธยมส่ง ?term=1/2 (เล่มรายภาค) · ประถมไม่ต้องส่ง"""
    from app.services.acad_doc import render_pp5_book
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    if not _scope(request, db).can_homeroom(cid):
        return _deny()
    return serve_generated(render_pp5_book(get_school(db), c, db, term=term), _DOCX)


@router.get("/academic/student/{aid}/pp6.docx")
def pp6_docx(aid: int, request: Request, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp6
    s = db.get(AcadStudent, aid)
    if not s:
        return RedirectResponse("/academic/classes", status_code=303)
    if not _scope(request, db).can_homeroom(s.class_id):
        return _deny()
    return serve_generated(render_pp6(get_school(db), s, db), _DOCX)


@router.get("/academic/classes/{cid}/pp6-all.docx")
def pp6_all_docx(cid: int, request: Request, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp6_class
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    if not _scope(request, db).can_homeroom(cid):
        return _deny()
    return serve_generated(render_pp6_class(get_school(db), c, db), _DOCX)
