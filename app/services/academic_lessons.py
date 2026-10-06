"""Period attendance. Durations are integer minutes; legacy daily data stays separate."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from app.models import (AcadLesson, AcadLessonMark, AcadLessonPlan, AcadCalendar,
                        AcadTimetable, AcadPeriod)
from app.services.academic import parse_days_csv

MARKS = {"/": "มา", "ป": "ป่วย", "ล": "ลา", "ข": "ขาด"}


def hours(minutes):
    return f"{minutes / 60:.2f}".rstrip("0").rstrip(".")


def target_minutes(value):
    if not str(value).strip():
        return None
    try:
        n = Decimal(str(value)) * 60
        if not n.is_finite() or n < 0 or n > 600000 or n != int(n):
            raise ValueError()
        return int(n)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError("กรอกชั่วโมงเป้าหมายเป็นจำนวนตั้งแต่ 0 และละเอียดไม่เกินนาที")


def check_date(klass, raw):
    from app.thai_utils import parse_be_date
    parsed = parse_be_date(str(raw))
    if parsed is None:
        raise ValueError("กรุณาระบุวันที่สอนให้ถูกต้อง")
    d = parsed.date()
    ce = klass.year - 543
    if not date(ce, 5, 1) <= d < date(ce + 1, 5, 1):
        raise ValueError("วันที่สอนต้องอยู่ในปีการศึกษาของห้องนี้ (พฤษภาคม–เมษายน)")
    return d


def check_term(subject, value):
    if str(value) not in ("1", "2"):
        raise ValueError("กรุณาเลือกภาคเรียน")
    term = int(value)
    if subject.term in (1, 2) and subject.term != term:
        raise ValueError("ภาคเรียนไม่ตรงกับรายวิชาที่เลือก")
    return term


def check_minutes(value):
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ValueError("กรอกระยะเวลาเรียนเป็นนาที")
    if not 1 <= n <= 720:
        raise ValueError("ระยะเวลาของหนึ่งคาบต้องอยู่ระหว่าง 1–720 นาที")
    return n


def plan_for(db, cid, sid, create=False):
    plan = db.query(AcadLessonPlan).filter_by(class_id=cid, subject_id=sid).first()
    if plan is None and create:
        plan = AcadLessonPlan(class_id=cid, subject_id=sid)
        db.add(plan)
        db.flush()
    return plan


def calendar_days(db, year):
    return {r.month: set(parse_days_csv(r.days_csv))
            for r in db.query(AcadCalendar).filter_by(year=year)}


def lessons_for(db, cid, sid, term=None):
    q = db.query(AcadLesson).filter_by(class_id=cid, subject_id=sid)
    if term:
        q = q.filter_by(term=term)
    return q.order_by(AcadLesson.date, AcadLesson.id).all()


def snapshot(db, klass, subject, term):
    all_rows = lessons_for(db, klass.id, subject.id)
    rows = [r for r in all_rows if r.term == term]
    ids = [r.id for r in rows]
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    student_ids = {s.id for s in students}
    marks = {(m.lesson_id, m.acad_student_id): m.mark for m in
             db.query(AcadLessonMark).filter(AcadLessonMark.lesson_id.in_(ids))
             if m.acad_student_id in student_ids} if ids else {}
    totals = {t: sum(r.minutes for r in all_rows if r.term == t) for t in (1, 2)}
    checked_counts = {r.id: sum((r.id, s.id) in marks for s in students) for r in rows}
    checked = sum(r.minutes for r in rows if students and checked_counts[r.id] == len(students))
    summary = {}
    for s in students:
        counts = {k: sum(r.minutes for r in rows if marks.get((r.id, s.id)) == k)
                  for k in MARKS}
        counts[""] = sum(r.minutes for r in rows if (r.id, s.id) not in marks)
        summary[s.id] = counts
    plan = plan_for(db, klass.id, subject.id)
    target = getattr(plan, f"term{term}_minutes", None)
    if subject.term in (1, 2):
        target = (subject.hours or 0) * 60 or None
    return dict(lessons=rows, students=students, marks=marks, totals=totals,
                checked=checked, checked_counts=checked_counts, summary=summary, plan=plan, target=target)


def add_lesson(db, klass, subject, term, day, slot, minutes, source="manual"):
    slot = str(slot).strip()
    if not slot or len(slot) > 80:
        raise ValueError("กรอกชื่อคาบหรือช่วงเวลา ไม่เกิน 80 ตัวอักษร")
    existing = db.query(AcadLesson).filter_by(class_id=klass.id, subject_id=subject.id,
                                             date=day, slot=slot).first()
    if existing:
        return False
    plan_for(db, klass.id, subject.id, create=True)
    db.add(AcadLesson(class_id=klass.id, subject_id=subject.id, term=term,
                      date=day, slot=slot, minutes=minutes, source=source))
    db.flush()
    return True


def period_minutes(label):
    match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\s*", label or "")
    if not match:
        return None
    a, b, c, d = map(int, match.groups())
    if max(a, c) > 23 or max(b, d) > 59:
        return None
    n = c * 60 + d - a * 60 - b
    return n if 0 < n <= 720 else None


def import_preview(db, klass, subject, term, start, end, fallback=None):
    start, end = check_date(klass, start), check_date(klass, end)
    if end < start:
        raise ValueError("วันสิ้นสุดต้องไม่น้อยกว่าวันเริ่มต้น")
    cal = calendar_days(db, klass.year)
    slots = (db.query(AcadTimetable, AcadPeriod)
             .join(AcadPeriod, AcadPeriod.id == AcadTimetable.period_id)
             .filter(AcadTimetable.class_id == klass.id,
                     AcadTimetable.subject_id == subject.id,
                     AcadPeriod.year == klass.year, AcadPeriod.is_break == False).all())
    if not slots:
        raise ValueError("ยังไม่มีคาบของวิชานี้ในตารางเรียน เพิ่มวันสอนเองหรือจัดตารางเรียนก่อน")
    months = set()
    day = start
    result, seen = [], set()
    existing = {(r.date, r.slot) for r in lessons_for(db, klass.id, subject.id)}
    while day <= end:
        months.add(day.month)
        for tt, period in slots:
            if tt.day != day.isoweekday() or day.day not in cal.get(day.month, set()):
                continue
            slot = (period.name or f"คาบ {period.seq}").strip()
            key = (day, slot)
            if key in seen:
                continue
            seen.add(key)
            minutes = period_minutes(period.time_label) or fallback
            if not minutes:
                raise ValueError("บางคาบไม่มีเวลาเริ่ม–สิ้นสุด กรุณาระบุนาทีต่อคาบสำหรับคาบที่ยังไม่มีเวลา")
            result.append(dict(date=day.isoformat(), slot=slot, minutes=minutes,
                               duplicate=key in existing))
        day += timedelta(days=1)
    if any(m not in cal for m in months):
        raise ValueError("ช่วงวันที่นี้ยังตั้งปฏิทินการศึกษาไม่ครบ จึงยังดึงตารางไม่ได้ หรือเลือกเพิ่มวันสอนเองได้")
    return result
