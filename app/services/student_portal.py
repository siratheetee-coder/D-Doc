"""บัญชีนักเรียน ระยะ 1: ดูข้อมูลตัวเองอย่างเดียว (เวลาเรียน ตารางเรียน เกรดที่ครูเผยแพร่)

ความปลอดภัย: ทุกอย่างอ้างจาก student_id ในบัญชีที่ล็อกอิน ไม่รับรหัสนักเรียนจาก URL
และ middleware ปิดทุกหน้าไว้ก่อน เปิดเฉพาะที่ path_ok อนุญาต
"""
import re

from app.models import (AcadStudent, AcadClass, AcadAttendance, AcadSubject, AcadScore,
                        AcadTimetable, AcadScorePublish, Student)

_ALLOW_GET = re.compile(r"^/student(/(timetable|grades|attendance|savings))?/?$")
_ALLOW_ANY = ("/logout",)

MARK_LABEL = {"/": "มา", "ป": "ป่วย", "ล": "ลา", "ข": "ขาด"}


def path_ok(path, method) -> bool:
    if path in _ALLOW_ANY:
        return True
    return method in ("GET", "HEAD") and bool(_ALLOW_GET.match(path or ""))


def current_row(db, student_id, year):
    """แถวนักเรียนในห้องของปีการศึกษาปัจจุบัน (None = ยังไม่ได้อยู่ห้องไหนในปีนี้)"""
    return (db.query(AcadStudent).join(AcadClass, AcadStudent.class_id == AcadClass.id)
            .filter(AcadStudent.student_id == student_id, AcadClass.year == year)
            .order_by(AcadStudent.id.desc()).first())


def _count(marks):
    c = {"/": 0, "ป": 0, "ล": 0, "ข": 0}
    for ch in marks or "":
        if ch in c:
            c[ch] += 1
    return c


def attendance(db, row):
    """เวลาเรียนแบบสดจากที่ครูเช็คชื่อ · overall = รายห้อง (subject_id NULL) · subjects = รายวิชา"""
    order = [5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3, 4]
    rank = {m: i for i, m in enumerate(order)}
    rows = db.query(AcadAttendance).filter_by(acad_student_id=row.id).all()

    def summarize(rs):
        tot = {"/": 0, "ป": 0, "ล": 0, "ข": 0}
        months = []
        for r in sorted(rs, key=lambda r: rank.get(r.month, 99)):
            c = _count(r.marks)
            if not any(c.values()) and r.present:
                c["/"] = r.present           # กรอกเป็นยอดรายเดือน ไม่ได้ติ๊กรายวัน
            days = sum(c.values())
            if not days:
                continue
            for k in tot:
                tot[k] += c[k]
            months.append({"month": r.month, "present": c["/"], "days": days, "c": c, "marks": r.marks or ""})
        days = sum(tot.values())
        pct = round(tot["/"] * 100 / days, 1) if days else None
        # ขาดติดกันล่าสุด (นับจากวันเรียนล่าสุดย้อนกลับ ข้ามวันที่ยังไม่ใช่วันเรียน)
        seq = [ch for m in months for ch in m["marks"] if ch in "/ปลข"]
        streak = 0
        for ch in reversed(seq):
            if ch != "ข":
                break
            streak += 1
        return {"tot": tot, "days": days, "pct": pct, "months": months, "streak": streak}

    overall = summarize([r for r in rows if r.subject_id is None])
    subs = {}
    for r in rows:
        if r.subject_id is not None:
            subs.setdefault(r.subject_id, []).append(r)
    names = {s.id: s for s in db.query(AcadSubject).filter(AcadSubject.id.in_(list(subs) or [0])).all()}
    subjects = [dict(summarize(v), subject=names.get(k)) for k, v in subs.items() if names.get(k)]
    subjects.sort(key=lambda x: (x["subject"].seq or 0, x["subject"].code or ""))
    return {"overall": overall, "subjects": subjects}


def timetable(db, klass):
    from app.services import timetable_sections as ts
    periods = ts.periods(db, klass.year, level=klass.level)
    cells = {(c.day, c.period_id): c for c in db.query(AcadTimetable).filter_by(class_id=klass.id).all()}
    days = sorted({1, 2, 3, 4, 5} | {d for (d, _p) in cells})   # จันทร์-ศุกร์เสมอ + เสาร์/อาทิตย์ถ้ามีคาบ
    from app.models import AcadTeaching
    teachers = {t.subject_id: t.teacher.name for t in db.query(AcadTeaching).filter_by(class_id=klass.id).all()
                if t.teacher and t.teacher.name}
    return {"periods": periods, "cells": cells, "days": days, "teachers": teachers}


def grades(db, row):
    """เฉพาะวิชาที่ครูเผยแพร่แล้ว (ห้อง x วิชา x ภาค)"""
    pubs = {(p.subject_id, p.term or 0) for p in db.query(AcadScorePublish).filter_by(class_id=row.class_id).all()}
    out = []
    for s in db.query(AcadScore).filter_by(acad_student_id=row.id).all():
        if (s.subject_id, s.term or 0) in pubs and s.subject:
            out.append(s)
    out.sort(key=lambda s: (s.term or 0, s.subject.seq or 0, s.subject.code or ""))
    return out


def student_name(db, student_id):
    st = db.get(Student, student_id)
    return st.name if st else ""
