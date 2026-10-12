"""Subject lessons, separate from the existing homeroom daily attendance routes."""
from urllib.parse import urlencode
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature

from app.database import get_db
from app.accounts import get_secret_key
from app.models import AcadClass, AcadSubject, AcadLesson, AcadLessonMark, AcadAttendance
from app.templating import templates
from app.services import academic_lessons as svc
from app.routers.pages import get_school

router = APIRouter()


def access(request, db, cid, sid):
    from app.routers.academic import _scope, _att_ok
    c, subject = db.get(AcadClass, cid), db.get(AcadSubject, sid)
    if not c or not subject or (c.year, c.level) != (subject.year, subject.level):
        raise HTTPException(404, "ไม่พบห้องหรือรายวิชาในปีการศึกษานี้")
    if not _att_ok(_scope(request, db), cid, "subject", sid):
        raise HTTPException(403, "ไม่มีสิทธิ์แก้ไขเวลาเรียนวิชานี้")
    return c, subject


def back(cid, sid, term, **extra):
    return RedirectResponse("/academic/lessons?" + urlencode(dict(cid=cid, sid=sid, term=term, **extra)), 303)


def signer():
    return URLSafeTimedSerializer(get_secret_key(), salt="academic-lesson-preview-v1")


def legacy_page(request, db, c, subject):
    from app.services.academic import parse_marks, TH_MONTHS
    from app.routers.academic import _class_label
    students = sorted(c.students, key=lambda s: (s.seq or 999, s.name))
    rows = db.query(AcadAttendance).filter(AcadAttendance.subject_id == subject.id,
        AcadAttendance.acad_student_id.in_([s.id for s in students])).all()
    values = {(r.acad_student_id, r.month): r for r in rows}
    return templates.TemplateResponse("academic_lessons_legacy.html", dict(
        request=request, school=get_school(db), c=c, subj=subject, students=students,
        months=TH_MONTHS, values=values, parse_marks=parse_marks, class_label=_class_label))


def page(request, db, c, subject, term, *, preview=None, token="", error="", entered=None):
    from datetime import date
    from itertools import groupby
    from app.models import AcadPeriod
    from app.routers.academic import _class_label
    from app.thai_utils import parse_be_date, be_date_input
    state = svc.snapshot(db, c, subject, term)
    months=[f'{c.year-543+(m<5)}-{m:02}' for m in list(range(5,13))+list(range(1,5))]
    default=date.today().strftime('%Y-%m')
    if default not in months:default=months[0]
    month=(entered or {}).get('month') or request.query_params.get('month') or default
    if month not in months:month=default
    from app.services.timetable_sections import periods as school_periods
    periods=[p for p in school_periods(db,c.year,level=c.level) if not p.is_break]
    import re
    order={p.name or f'คาบ {p.seq}':p.seq for p in periods}
    def slot_order(row):
        number=re.search(r'\d+',row.slot)
        return (row.date,order.get(row.slot, int(number.group()) if number else 999),row.slot,row.id)
    grid=sorted((r for r in state['lessons'] if r.date.strftime('%Y-%m')==month),key=slot_order)
    day_groups=[(d,list(rows)) for d,rows in groupby(grid,key=lambda r:r.date)]
    slot_choices=[dict(name=p.name or f'คาบ {p.seq}',minutes=svc.period_minutes(p.time_label) or 50) for p in periods]
    if not slot_choices:slot_choices=[dict(name=f'คาบ {i}',minutes=50) for i in range(1,9)]
    sids = [s.id for s in c.students]
    legacy = bool(sids) and db.query(AcadAttendance).filter(
        AcadAttendance.subject_id == subject.id, AcadAttendance.acad_student_id.in_(sids)).first() is not None
    cal = svc.calendar_days(db, c.year)
    off_calendar = {r.id for r in state["lessons"] if r.date.day not in cal.get(r.date.month, set())}
    return templates.TemplateResponse("academic_lessons.html", dict(
        request=request, school=get_school(db), c=c, subj=subject, term=term,
        format_date=lambda value: be_date_input(parse_be_date(value)),
        class_label=_class_label, hours=svc.hours, states=svc.MARKS, legacy=legacy,
        off_calendar=off_calendar, preview=preview, token=token, error=error,
        entered=entered or {}, months=months,month=month,grid=grid,day_groups=day_groups,
        slot_choices=slot_choices,calendar_events=[dict(date=r.date.isoformat(),slot=r.slot) for r in state['lessons']], **state))


@router.get("/academic/lessons")
def lesson_page(request: Request, cid: int, sid: int, term: int = 1, db: Session = Depends(get_db)):
    c, subject = access(request, db, cid, sid)
    term = subject.term if subject.term in (1, 2) else (2 if term == 2 else 1)
    return page(request, db, c, subject, term)


@router.post("/academic/lessons/{action}")
async def lesson_action(action: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        cid, sid = int(form.get("cid", 0)), int(form.get("sid", 0))
    except ValueError:
        raise HTTPException(400, "กรุณาเลือกห้องและรายวิชา")
    c, subject = access(request, db, cid, sid)
    term = subject.term if subject.term in (1, 2) else 1
    try:
        term = svc.check_term(subject, form.get("term", ""))
        if action == "targets":
            if subject.term in (1, 2):
                raise ValueError("วิชารายเทอมใช้จำนวนชั่วโมงจากหน้ารายวิชา")
            first, second = svc.target_minutes(form.get("term1", "")), svc.target_minutes(form.get("term2", ""))
            plan = svc.plan_for(db, cid, sid, create=True)
            plan.term1_minutes, plan.term2_minutes = first, second
        elif action == "batch-add":
            import json
            dates=json.loads(form.get('dates','[]'));slots=json.loads(form.get('slots','[]'))
            if not isinstance(dates,list) or not isinstance(slots,list) or not dates or not slots or len(dates)*len(slots)>1000:
                raise ValueError('เลือกวันและคาบที่จะเพิ่ม ไม่เกิน 1,000 คาบต่อครั้ง')
            days=sorted({svc.check_date(c,d) for d in dates})
            choices=[]
            for slot in slots:
                if not isinstance(slot,dict):raise ValueError('คาบไม่ถูกต้อง')
                name=str(slot.get('name','')).strip()
                if not name or len(name)>80:raise ValueError('กรอกชื่อคาบไม่เกิน 80 ตัวอักษร')
                choices.append((name,svc.check_minutes(str(slot.get('minutes','')))))
            added=0
            for day in days:
                for name,minutes in choices:added+=svc.add_lesson(db,c,subject,term,day,name,minutes)
            db.commit()
            return back(cid,sid,term,imported=added,month=days[0].strftime('%Y-%m'))
        elif action == "grid-marks":
            import json
            changes=json.loads(form.get('changes','[]'))
            if not isinstance(changes,list) or len(changes)>20000:raise ValueError('ข้อมูลเช็กชื่อไม่ถูกต้อง')
            student_ids={s.id for s in c.students}
            allowed={r.id for r in svc.lessons_for(db,cid,sid,term)}
            pending=[];seen=set()
            for item in changes:
                if not isinstance(item,dict):raise ValueError('ข้อมูลเช็กชื่อไม่ถูกต้อง')
                lid,student_id=int(str(item.get('lesson_id',0))),int(str(item.get('student_id',0)))
                mark=str(item.get('mark',''));old=str(item.get('old',''))
                if lid not in allowed or student_id not in student_ids:raise HTTPException(403,'คาบหรือนักเรียนไม่อยู่ในรายวิชาที่เลือก')
                if (lid,student_id) in seen or (mark and mark not in svc.MARKS):raise ValueError('สถานะเช็กชื่อไม่ถูกต้อง')
                seen.add((lid,student_id))
                row=db.query(AcadLessonMark).filter_by(lesson_id=lid,acad_student_id=student_id).first()
                if (row.mark if row else '')!=old:raise ValueError('มีผู้แก้ไขข้อมูลบางช่องแล้ว กรุณาโหลดหน้าล่าสุดก่อนบันทึก')
                pending.append((row,lid,student_id,mark))
            for row,lid,student_id,mark in pending:
                if not mark:
                    if row:db.delete(row)
                elif row:row.mark=mark
                else:db.add(AcadLessonMark(lesson_id=lid,acad_student_id=student_id,mark=mark))
        elif action == "add":
            day = svc.check_date(c, form.get("date", ""))
            minutes = svc.check_minutes(form.get("minutes", ""))
            if not svc.add_lesson(db, c, subject, term, day, form.get("slot", ""), minutes):
                raise ValueError("วันและคาบนี้มีอยู่แล้ว ระบบไม่เพิ่มซ้ำ")
        elif action == "preview":
            fallback = svc.check_minutes(form["fallback"]) if form.get("fallback") else None
            rows = svc.import_preview(db, c, subject, term, form.get("start", ""), form.get("end", ""), fallback)
            payload = dict(cid=cid, sid=sid, term=term, tid=request.session.get("tid"),
                           uid=request.session.get("uid"), rows=rows)
            return page(request, db, c, subject, term, preview=rows, token=signer().dumps(payload), entered=dict(form))
        elif action == "import":
            try:
                data = signer().loads(form.get("token", ""), max_age=1800)
            except BadSignature:
                raise ValueError("ตัวอย่างหมดอายุ กรุณากดดึงวันสอนเพื่อดูตัวอย่างใหม่")
            if any(data.get(k) != v for k, v in dict(cid=cid, sid=sid, term=term,
                    tid=request.session.get("tid"), uid=request.session.get("uid")).items()):
                raise HTTPException(403, "ตัวอย่างไม่ตรงกับผู้ใช้หรือรายวิชา")
            added = 0
            for row in data["rows"]:
                added += svc.add_lesson(db, c, subject, term, svc.check_date(c, row["date"]),
                                        row["slot"], svc.check_minutes(row["minutes"]), "timetable")
            db.commit()
            return back(cid, sid, term, imported=added)
        elif action in ("marks", "remove"):
            try:
                lesson = db.get(AcadLesson, int(form.get("lesson_id", 0)))
            except ValueError:
                lesson = None
            if not lesson or (lesson.class_id, lesson.subject_id, lesson.term) != (cid, sid, term):
                raise HTTPException(404, "ไม่พบคาบนี้")
            if action == "remove":
                if db.query(AcadLessonMark).filter_by(lesson_id=lesson.id).first():
                    raise ValueError("คาบนี้มีผลเช็คชื่อแล้ว กรุณาตรวจสอบและล้างผลเช็คชื่อของคาบนี้ก่อนลบ")
                db.delete(lesson)
            else:
                # Validate the whole submission before changing any student's mark.
                values = {s.id: str(form.get(f"mark_{s.id}", "")) for s in c.students}
                if any(v and v not in svc.MARKS for v in values.values()):
                    raise ValueError("สถานะเช็คชื่อไม่ถูกต้อง")
                existing = {m.acad_student_id: m for m in db.query(AcadLessonMark).filter_by(lesson_id=lesson.id)}
                for student_id, mark in values.items():
                    row = existing.get(student_id)
                    if not mark:
                        if row:
                            db.delete(row)
                    elif row:
                        row.mark = mark
                    else:
                        db.add(AcadLessonMark(lesson_id=lesson.id, acad_student_id=student_id, mark=mark))
        else:
            raise HTTPException(404)
        db.commit()
        return back(cid, sid, term, saved=1, **({"lesson": lesson.id} if action == "marks" else {}), **({'month':form['month']} if form.get('month') else {}))
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        error = str(exc) if isinstance(exc, ValueError) else "มีการบันทึกคาบนี้แล้ว กรุณาตรวจรายการล่าสุดเพื่อไม่ให้ซ้ำ"
        return page(request, db, c, subject, term, error=error, entered=dict(form))


@router.get("/academic/lessons/report.docx")
def lesson_report(request: Request, cid: int, sid: int, term: int = 1, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_lesson_attendance
    from app.routers.pages import serve_generated
    c, subject = access(request, db, cid, sid)
    try:
        term = svc.check_term(subject, term)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return serve_generated(render_lesson_attendance(get_school(db), c, subject, db, term=term),
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/academic/lessons/legacy.docx")
def legacy_report(request: Request, cid: int, sid: int, term: int = 1, db: Session = Depends(get_db)):
    from app.services.acad_doc import render_attendance_term
    from app.routers.pages import serve_generated
    c, subject = access(request, db, cid, sid)
    if term not in (1, 2):
        raise HTTPException(400, "กรุณาเลือกภาคเรียน")
    return serve_generated(render_attendance_term(get_school(db), c, db, term, subject=subject),
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
