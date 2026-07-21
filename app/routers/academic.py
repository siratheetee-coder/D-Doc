# -*- coding: utf-8 -*-
"""
academic.py — งานวิชาการ
เฟส 1: ห้องเรียน/ครูประจำชั้น + รายวิชา + ผลการเรียน + ปพ.5 / ปพ.6 (สมุดพก)

ความสัมพันธ์กับทะเบียนกลาง: ดึงรายชื่อจาก Student แล้วเก็บ "สำเนารายปี" (AcadStudent)
เหมือนงานภาวะโภชนาการ — ผลการเรียนของปีเก่าจึงไม่ขยับเมื่อนักเรียนเลื่อนชั้น
ครูทั้งหมดมาจากทะเบียนบุคลากรกลาง (Person) ไม่มีการสร้างทะเบียนครูซ้ำ
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Student, Person, AcadClass, AcadStudent, AcadSubject,
                        AcadTeaching, AcadScore, AcadEval,
                        AcadCharEval, AcadReadEval, AcadAttendance, AcadClassMonth,
                        AcadCalendar)
from app.thai_utils import SCHOOL_LEVELS, GRADUATED, current_academic_year, is_secondary, level_rank
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated
from app.services.academic import (grade_of, subject_preset, term_choices, term_label,
                                   GRADE_CHOICES, QUALITY_LEVELS, PASS_FAIL, SUBJECT_KINDS,
                                   CHAR_ITEMS, CHAR_FIELDS, READ_DOMAINS, TH_MONTHS,
                                   TH_MONTH_FULL, quality_of_avg, char_avg, read_avg,
                                   effective_eval, MARK_STATES, MARK_CHARS, MARK_BLANK,
                                   TH_WEEKDAYS, month_weekdays, default_open_days,
                                   parse_days_csv, parse_marks, build_marks, count_marks)

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


# ---------------- หน้าหลัก ----------------
@router.get("/academic", response_class=HTMLResponse)
def academic_home(request: Request, db: Session = Depends(get_db), year: int | None = None):
    y = year or current_academic_year()
    classes = db.query(AcadClass).filter_by(year=y).all()
    n_students = (db.query(AcadStudent).join(AcadClass)
                  .filter(AcadClass.year == y).count())
    return templates.TemplateResponse("academic_home.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "n_classes": len(classes), "n_students": n_students,
        "n_subjects": db.query(AcadSubject).filter_by(year=y).count(),
    })


# ---------------- ห้องเรียน ----------------
@router.get("/academic/classes", response_class=HTMLResponse)
def classes_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    y = year or current_academic_year()
    rows = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    return templates.TemplateResponse("academic_classes.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "rows": rows, "levels": SCHOOL_LEVELS, "class_label": _class_label,
        "teachers": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
    })


@router.post("/academic/classes/add")
def class_add(db: Session = Depends(get_db), year: str = Form(""), level: str = Form(""),
              room: str = Form(""), homeroom_id: str = Form(""), co_homeroom_id: str = Form("")):
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
def class_update(cid: int, db: Session = Depends(get_db), level: str = Form(""),
                 room: str = Form(""), homeroom_id: str = Form(""),
                 co_homeroom_id: str = Form(""), note: str = Form("")):
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
def class_delete(cid: int, db: Session = Depends(get_db)):
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
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
    subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                .order_by(AcadSubject.seq, AcadSubject.code).all())
    teach = {t.subject_id: t for t in c.teachings}
    return templates.TemplateResponse("academic_class.html", {
        "request": request, "school": get_school(db), "c": c, "students": students,
        "subjects": subjects, "teach": teach, "class_label": _class_label(c),
        "teachers": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
        "terms": term_choices(c.level), "term_label": term_label,
        "is_sec": is_secondary(c.level),
    })


@router.post("/academic/classes/{cid}/pull-roster")
def class_pull_roster(cid: int, db: Session = Depends(get_db)):
    """ดึงนักเรียนจากทะเบียนกลางเข้าห้องนี้ (จับคู่ด้วยชั้น+ห้อง · ข้ามคนที่ดึงมาแล้ว)"""
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
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
def acad_student_update(aid: int, db: Session = Depends(get_db), seq: str = Form(""),
                        student_no: str = Form(""), name: str = Form(""), sex: str = Form("")):
    s = db.get(AcadStudent, aid)
    if s:
        s.seq = _to_int(seq, 0)
        s.student_no = (student_no or "").strip()
        s.name = (name or "").strip() or s.name
        s.sex = (sex or "").strip()
        db.commit()
    return RedirectResponse(f"/academic/classes/{s.class_id}" if s else "/academic/classes",
                            status_code=303)


@router.post("/academic/student/{aid}/delete")
def acad_student_delete(aid: int, db: Session = Depends(get_db)):
    s = db.get(AcadStudent, aid)
    cid = s.class_id if s else None
    if s:
        db.delete(s); db.commit()
    return RedirectResponse(f"/academic/classes/{cid}" if cid else "/academic/classes",
                            status_code=303)


@router.post("/academic/classes/{cid}/teaching")
async def teaching_save(cid: int, request: Request, db: Session = Depends(get_db)):
    """กำหนดครูผู้สอนรายวิชาของห้องนี้ (วิชาเดียวกันคนละห้องคนละครูได้)"""
    form = await request.form()
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    cur = {t.subject_id: t for t in c.teachings}
    for key, val in form.items():
        if not key.startswith("teacher_"):
            continue
        sid = _to_int(key[8:], 0)
        tid = _to_int(val, 0) or None
        if not sid:
            continue
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
    q = db.query(AcadSubject).filter_by(year=y)
    if level:
        q = q.filter_by(level=level)
    rows = sorted(q.all(), key=lambda s: (level_rank(s.level), s.seq or 0, s.code or ""))
    return templates.TemplateResponse("academic_subjects.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "rows": rows, "level": level, "levels": SCHOOL_LEVELS, "kinds": SUBJECT_KINDS,
        "term_label": term_label, "is_secondary": is_secondary,
    })


@router.post("/academic/subjects/add")
def subject_add(db: Session = Depends(get_db), year: str = Form(""), level: str = Form(""),
                code: str = Form(""), name: str = Form(""), learn_group: str = Form(""),
                kind: str = Form("พื้นฐาน"), hours: str = Form(""), credit: str = Form(""),
                term: str = Form("0"), mid_max: str = Form("70"), final_max: str = Form("30")):
    y = _to_int(year, 0) or current_academic_year()
    nm = (name or "").strip()
    if nm:
        n = db.query(AcadSubject).filter_by(year=y, level=(level or "").strip()).count()
        mm, fm = max(0, _to_int(mid_max, 70)), max(0, _to_int(final_max, 30))
        if (mm + fm) <= 0:            # กันสัดส่วน 0:0 (เกรดจะคิดจากค่าปริยายเงียบ ๆ)
            mm, fm = 70, 30
        db.add(AcadSubject(year=y, level=(level or "").strip(), code=(code or "").strip(),
                           name=nm, learn_group=(learn_group or "").strip(),
                           kind=(kind or "พื้นฐาน").strip(), hours=_to_int(hours, 0),
                           credit=_to_float(credit, 0.0), term=_to_int(term, 0), seq=n + 1,
                           mid_max=mm, final_max=fm))
        db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}&level={level}", status_code=303)


@router.post("/academic/subjects/{sid}/update")
def subject_update(sid: int, db: Session = Depends(get_db), code: str = Form(""),
                   name: str = Form(""), learn_group: str = Form(""), kind: str = Form(""),
                   hours: str = Form(""), credit: str = Form(""), term: str = Form("0"),
                   mid_max: str = Form("70"), final_max: str = Form("30")):
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
        db.commit()
    return RedirectResponse(f"/academic/subjects?year={s.year if s else ''}", status_code=303)


@router.post("/academic/subjects/{sid}/delete")
def subject_delete(sid: int, db: Session = Depends(get_db)):
    s = db.get(AcadSubject, sid)
    y = s.year if s else ""
    if s:
        db.delete(s); db.commit()
    return RedirectResponse(f"/academic/subjects?year={y}", status_code=303)


@router.post("/academic/subjects/preset")
def subjects_preset(db: Session = Depends(get_db), year: str = Form(""), level: str = Form("")):
    """สร้างรายวิชาพื้นฐาน 8 กลุ่มสาระของชั้นนี้ในคลิกเดียว (ข้ามวิชาที่มีรหัสซ้ำแล้ว)"""
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


# ---------------- กรอกผลการเรียน ----------------
@router.get("/academic/grades", response_class=HTMLResponse)
def grades_page(request: Request, db: Session = Depends(get_db), cid: int | None = None,
                sid: int | None = None, term: int | None = None, year: int | None = None):
    y = year or current_academic_year()
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    c = db.get(AcadClass, cid) if cid else None
    subjects, students, scores, subj = [], [], {}, None
    if c:
        subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                    .order_by(AcadSubject.seq, AcadSubject.code).all())
        subj = db.get(AcadSubject, sid) if sid else None
        if subj:
            t = subj.term if subj.term is not None else 0
            students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
            scores = {s.acad_student_id: s for s in
                      db.query(AcadScore).filter_by(subject_id=subj.id, term=t).all()}
    return templates.TemplateResponse("academic_grades.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "subjects": subjects, "subj": subj,
        "students": students, "scores": scores, "class_label": _class_label,
        "term_label": term_label, "grades": GRADE_CHOICES,
    })


@router.post("/academic/grades/save")
async def grades_save(request: Request, db: Session = Depends(get_db),
                      cid: str = Form(""), sid: str = Form("")):
    """บันทึกคะแนนทั้งห้องในครั้งเดียว · เกรดคำนวณจากคะแนนรวม (กรอกเกรดเองทับได้)"""
    form = await request.form()
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not subj:
        return RedirectResponse("/academic/grades", status_code=303)
    t = subj.term if subj.term is not None else 0
    mmax = subj.mid_max if (subj.mid_max or 0) > 0 else 70
    fmax = subj.final_max if (subj.final_max or 0) > 0 else 30
    cur = {s.acad_student_id: s for s in
           db.query(AcadScore).filter_by(subject_id=subj.id, term=t).all()}
    for key in [k for k in form.keys() if k.startswith("mid_")]:
        aid = _to_int(key[4:], 0)
        if not aid:
            continue
        mid = _to_float(form.get(f"mid_{aid}", ""), None)
        fin = _to_float(form.get(f"fin_{aid}", ""), None)
        if mid is not None:
            mid = max(0.0, min(mid, float(mmax)))    # กันกรอกเกินคะแนนเต็มของวิชานี้
        if fin is not None:
            fin = max(0.0, min(fin, float(fmax)))
        manual = (form.get(f"grade_{aid}", "") or "").strip()
        total = None
        if mid is not None or fin is not None:
            total = (mid or 0) + (fin or 0)
        row = cur.get(aid)
        if not row:
            row = AcadScore(acad_student_id=aid, subject_id=subj.id, term=t)
            db.add(row)
        row.score_mid, row.score_final, row.score = mid, fin, total
        # เกรดตัดจากร้อยละ — ถ้าสัดส่วนรวมไม่ใช่ 100 (เช่น 80:20 เต็ม 100 อยู่แล้วก็ค่าเดิม)
        pct = None if total is None else (total * 100.0 / (mmax + fmax))
        row.grade = manual or grade_of(pct)
    db.commit()
    return RedirectResponse(f"/academic/grades?cid={cid}&sid={sid}&saved=1", status_code=303)


# ---------------- ประเมิน (ที่ ปพ.6 ต้องใช้) ----------------
@router.get("/academic/eval", response_class=HTMLResponse)
def eval_page(request: Request, db: Session = Depends(get_db),
              cid: int | None = None, year: int | None = None):
    y = year or current_academic_year()
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    c = db.get(AcadClass, cid) if cid else None
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    eff = {s.id: effective_eval(s, db) for s in students}
    return templates.TemplateResponse("academic_eval.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "students": students, "class_label": _class_label,
        "quality": QUALITY_LEVELS, "passfail": PASS_FAIL, "eff": eff,
    })


@router.post("/academic/eval/save")
async def eval_save(request: Request, db: Session = Depends(get_db), cid: str = Form("")):
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    if not c:
        return RedirectResponse("/academic/eval", status_code=303)
    cur = {e.acad_student_id: e for e in db.query(AcadEval).join(AcadStudent)
           .filter(AcadStudent.class_id == c.id).all()}
    for s in c.students:
        e = cur.get(s.id)
        if not e:
            e = AcadEval(acad_student_id=s.id)
            db.add(e)
        # ช่องที่ถูกแทนด้วยป้าย "คำนวณจากรายวิชา" จะไม่ถูกส่งมา — ห้ามเขียนทับค่า manual เดิม
        # (เผื่อครูลบข้อมูลรายวิชาทีหลัง ค่าที่เคยเลือกไว้ต้องยังอยู่)
        if f"read_{s.id}" in form:
            e.read_think = (form.get(f"read_{s.id}", "") or "").strip()
        if f"char_{s.id}" in form:
            e.desired_char = (form.get(f"char_{s.id}", "") or "").strip()
        e.act_guidance = (form.get(f"guid_{s.id}", "") or "").strip()
        e.act_scout = (form.get(f"scout_{s.id}", "") or "").strip()
        e.act_club = (form.get(f"club_{s.id}", "") or "").strip()
        e.act_social = (form.get(f"social_{s.id}", "") or "").strip()
        # ช่องวัน (เปิด/มา/ป่วย/ลา/ขาด) ย้ายไปหน้า "เวลาเรียน" — ห้ามอ่านที่นี่
        # ไม่งั้นการบันทึกหน้านี้จะเขียนทับค่าที่กรอกไว้เป็นว่าง
        e.comment = (form.get(f"cmt_{s.id}", "") or "").strip()
    db.commit()
    return RedirectResponse(f"/academic/eval?cid={c.id}&saved=1", status_code=303)


# ---------------- ประเมินละเอียดรายวิชา (คุณลักษณะฯ / อ่านคิดเขียน) ----------------
@router.get("/academic/assess", response_class=HTMLResponse)
def assess_page(request: Request, db: Session = Depends(get_db),
                cid: int | None = None, sid: int | None = None,
                kind: str = "char", year: int | None = None):
    y = year or current_academic_year()
    kind = "read" if kind == "read" else "char"
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    c = db.get(AcadClass, cid) if cid else None
    subjects = []
    if c:
        subjects = (db.query(AcadSubject).filter_by(year=c.year, level=c.level)
                    .order_by(AcadSubject.seq, AcadSubject.code).all())
    subj = db.get(AcadSubject, sid) if sid else None
    if subj and c and (subj.year != c.year or subj.level != c.level):
        subj = None                        # กันเลือกวิชาข้ามชั้น
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    Model = AcadReadEval if kind == "read" else AcadCharEval
    fields = [f for f, _ in READ_DOMAINS] if kind == "read" else CHAR_FIELDS
    labels = [lb for _, lb in READ_DOMAINS] if kind == "read" else CHAR_ITEMS
    rows = {}
    if subj:
        rows = {r.acad_student_id: r for r in
                db.query(Model).filter_by(subject_id=subj.id).all()}
    return templates.TemplateResponse("academic_assess.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "subjects": subjects, "subj": subj, "kind": kind,
        "students": students, "rows": rows, "fields": fields, "labels": labels,
        "class_label": _class_label, "term_label": term_label,
    })


@router.post("/academic/assess/save")
async def assess_save(request: Request, db: Session = Depends(get_db),
                      cid: str = Form(""), sid: str = Form(""), kind: str = Form("char")):
    form = await request.form()
    kind = "read" if kind == "read" else "char"
    c = db.get(AcadClass, _to_int(cid, 0))
    subj = db.get(AcadSubject, _to_int(sid, 0))
    if not c or not subj:
        return RedirectResponse("/academic/assess", status_code=303)
    Model = AcadReadEval if kind == "read" else AcadCharEval
    fields = [f for f, _ in READ_DOMAINS] if kind == "read" else CHAR_FIELDS
    cur = {r.acad_student_id: r for r in
           db.query(Model).filter_by(subject_id=subj.id).all()}
    for s in c.students:
        r = cur.get(s.id)
        if not r:
            r = Model(acad_student_id=s.id, subject_id=subj.id)
            db.add(r)
        for f in fields:
            v = _to_int(form.get(f"{f}_{s.id}", ""), None)
            if v is not None:
                v = max(0, min(3, v))      # คะแนน 0-3 เท่านั้น
            setattr(r, f, v)
    db.commit()
    return RedirectResponse(f"/academic/assess?cid={c.id}&sid={subj.id}&kind={kind}&saved=1",
                            status_code=303)


# ---------------- ปฏิทินการศึกษา ----------------
@router.get("/academic/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    y = year or current_academic_year()
    saved = {r.month: parse_days_csv(r.days_csv)
             for r in db.query(AcadCalendar).filter_by(year=y).all()}
    months = []
    for mnum, mshort in TH_MONTHS:
        wd = month_weekdays(y, mnum)
        # เดือนที่ยังไม่เคยตั้ง -> ตั้งต้นเป็นวันจันทร์-ศุกร์ (ครูค่อยคลิกปิดวันหยุด)
        open_days = saved[mnum] if mnum in saved else default_open_days(y, mnum)
        months.append({
            "num": mnum, "short": mshort, "name": TH_MONTH_FULL[mnum],
            "days": [{"d": d, "wd": wd[d], "open": d in open_days} for d in sorted(wd)],
            # ช่องว่างนำหน้าให้วันที่ 1 ตกคอลัมน์วันที่ถูกต้อง (จันทร์=คอลัมน์แรก)
            "lead": TH_WEEKDAYS.index(wd[1]),
            "configured": mnum in saved,
        })
    return templates.TemplateResponse("academic_calendar.html", {
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "months": months, "any_set": bool(saved),
    })


@router.post("/academic/calendar/save")
async def calendar_save(request: Request, db: Session = Depends(get_db), year: str = Form("")):
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
                    month: int | None = None):
    y = year or current_academic_year()
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=y).all())
    c = db.get(AcadClass, cid) if cid else None
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name)) if c else []
    cal = {r.month: parse_days_csv(r.days_csv)
           for r in db.query(AcadCalendar).filter_by(year=y).all()}
    rows = []
    if c and students:
        rows = (db.query(AcadAttendance)
                .filter(AcadAttendance.acad_student_id.in_([s.id for s in students])).all())

    # ---- โหมดเช็กชื่อรายวัน ----
    if c and month in dict(TH_MONTHS):
        open_days = cal.get(month, [])
        wd = month_weekdays(y, month)
        marks = {a.acad_student_id: parse_marks(a.marks)
                 for a in rows if a.month == month}
        return templates.TemplateResponse("academic_attendance_day.html", {
            "request": request, "school": get_school(db), "year": y, "c": c,
            "students": students, "class_label": _class_label, "month": month,
            "month_name": TH_MONTH_FULL[month], "open_days": open_days,
            "weekdays": wd, "marks": marks, "states": MARK_STATES, "blank": MARK_BLANK,
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
        "request": request, "school": get_school(db), "year": y, "years": _years(db, y),
        "classes": classes, "c": c, "students": students, "class_label": _class_label,
        "months": TH_MONTHS, "opens": opens, "att": att, "marked": marked,
        "cal_days": {m: len(d) for m, d in cal.items()}, "has_cal": bool(cal),
    })


@router.post("/academic/attendance/day-save")
async def attendance_day_save(request: Request, db: Session = Depends(get_db),
                              cid: str = Form(""), month: str = Form("")):
    """บันทึกเช็กชื่อรายวันของเดือนเดียว — เขียน marks + present ให้ตรงกัน"""
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    m = _to_int(month, 0)
    if not c or m not in dict(TH_MONTHS):
        return RedirectResponse("/academic/attendance", status_code=303)
    cal = db.query(AcadCalendar).filter_by(year=c.year, month=m).first()
    open_days = parse_days_csv(cal.days_csv if cal else "")
    cur = {}
    sids = [s.id for s in c.students]
    if sids:
        cur = {a.acad_student_id: a for a in db.query(AcadAttendance)
               .filter(AcadAttendance.acad_student_id.in_(sids),
                       AcadAttendance.month == m).all()}
    for s in c.students:
        row = cur.get(s.id)
        if not row:
            row = AcadAttendance(acad_student_id=s.id, month=m)
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
    return RedirectResponse(f"/academic/attendance?cid={c.id}&month={m}&saved=1",
                            status_code=303)


@router.post("/academic/attendance/save")
async def attendance_save(request: Request, db: Session = Depends(get_db), cid: str = Form("")):
    form = await request.form()
    c = db.get(AcadClass, _to_int(cid, 0))
    if not c:
        return RedirectResponse("/academic/attendance", status_code=303)
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
                  .filter(AcadAttendance.acad_student_id.in_(sids)).all()):
            cura[(a.acad_student_id, a.month)] = a
    cure = {e.acad_student_id: e for e in db.query(AcadEval).join(AcadStudent)
            .filter(AcadStudent.class_id == c.id).all()}
    for s in c.students:
        for mnum, _ in TH_MONTHS:
            row = cura.get((s.id, mnum))
            if not row:
                row = AcadAttendance(acad_student_id=s.id, month=mnum)
                db.add(row)
            # เดือนที่เช็กชื่อรายวันไว้แล้ว ยอดมาจากการนับ marks — หน้าสรุปไม่ส่งช่องนั้นมา
            # (ถ้าเผลอทับ ตัวเลขบนหน้าจอจะไม่ตรงกับที่เอกสารใช้จริง)
            if row.id and (row.marks or "").strip(MARK_BLANK):
                continue
            row.present = _to_int(form.get(f"p_{s.id}_{mnum}", ""), None)
        e = cure.get(s.id)
        if not e:
            e = AcadEval(acad_student_id=s.id)
            db.add(e)
        e.days_open = _to_int(form.get(f"dopen_{s.id}", ""), None)
        e.days_present = _to_int(form.get(f"dpres_{s.id}", ""), None)
        e.days_sick = _to_int(form.get(f"sick_{s.id}", ""), None)
        e.days_leave = _to_int(form.get(f"leave_{s.id}", ""), None)
        e.days_absent = _to_int(form.get(f"abs_{s.id}", ""), None)
    db.commit()
    return RedirectResponse(f"/academic/attendance?cid={c.id}&saved=1", status_code=303)


# ---------------- เอกสาร ----------------
@router.get("/academic/classes/{cid}/pp5.docx")
def pp5_docx(cid: int, sid: int, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp5
    c, subj = db.get(AcadClass, cid), db.get(AcadSubject, sid)
    if not c or not subj:
        return RedirectResponse("/academic/grades", status_code=303)
    return serve_generated(render_pp5(get_school(db), c, subj, db), _DOCX)


@router.get("/academic/classes/{cid}/pp5-book.docx")
def pp5_book_docx(cid: int, term: int = 0, db: Session = Depends(get_db)):
    """ปพ.5 ทั้งเล่ม · มัธยมส่ง ?term=1/2 (เล่มรายภาค) · ประถมไม่ต้องส่ง"""
    from app.services.acad_doc import render_pp5_book
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    return serve_generated(render_pp5_book(get_school(db), c, db, term=term), _DOCX)


@router.get("/academic/student/{aid}/pp6.docx")
def pp6_docx(aid: int, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp6
    s = db.get(AcadStudent, aid)
    if not s:
        return RedirectResponse("/academic/classes", status_code=303)
    return serve_generated(render_pp6(get_school(db), s, db), _DOCX)


@router.get("/academic/classes/{cid}/pp6-all.docx")
def pp6_all_docx(cid: int, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_pp6_class
    c = db.get(AcadClass, cid)
    if not c:
        return RedirectResponse("/academic/classes", status_code=303)
    return serve_generated(render_pp6_class(get_school(db), c, db), _DOCX)
