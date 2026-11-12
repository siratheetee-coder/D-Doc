# -*- coding: utf-8 -*-
"""หน้าหลักครู คอลัมน์ซ้าย: คาบสอนวันนี้ + สรุปงานวิชาการ + ปฏิทิน 7 วันข้างหน้า

เจ้าของสั่งเพิ่ม (2026-11-13) เดิมงานวิชาการอยู่เฉพาะหน้า /academic
ทุกส่วนห่อ try ไว้ ข้อมูลวิชาการพังต้องไม่ทำหน้าหลักล่ม
"""
from datetime import date, timedelta

TH_WD = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
TH_MS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def _slot_key(s):
    digits = "".join(ch for ch in (s or "") if ch.isdigit())
    return (int(digits) if digits else 99, s or "")


def today_lessons(db, sc, today):
    from app.models import AcadLesson, AcadLessonMark
    from app.routers.academic import _class_label
    pairs = sc.teach_pairs or set()
    if not pairs:
        return []
    rows = db.query(AcadLesson).filter(AcadLesson.date == today,
                                       AcadLesson.class_id.in_({c for c, _ in pairs})).all()
    out = []
    for r in rows:
        if (r.class_id, r.subject_id) not in pairs:
            continue
        n_st = len(r.klass.students) if r.klass else 0
        n_mk = db.query(AcadLessonMark).filter(AcadLessonMark.lesson_id == r.id).count()
        subj = r.subject
        out.append(dict(slot=r.slot, minutes=r.minutes,
                        subject=((subj.code + " ") if subj and subj.code else "") + (subj.name if subj else ""),
                        cls=_class_label(r.klass) if r.klass else "",
                        done=bool(n_st) and n_mk >= n_st, marked=n_mk, total=n_st,
                        href=f"/academic/attendance?mode=subject&cid={r.class_id}&sid={r.subject_id}&month={today.month}"))
    out.sort(key=lambda x: _slot_key(x["slot"]))
    return out


def summary(db, sc, year, term):
    from app.routers.academic import _teacher_todo
    todo = _teacher_todo(sc, db, year, term)
    items = todo["items"]
    full = none = 0
    parts = 0
    for it in items:
        n = sum(1 for k in ("grade", "att", "char", "read") if it[k])
        parts += n
        full += n == 4
        none += n == 0
    total = len(items)
    pct = round(100 * parts / (total * 4)) if total else 0
    return dict(total=total, full=full, none=none, doing=total - full - none, pct=pct)


def week_events(db, year, today, days=7):
    """วันหยุด + วันเปิด/ปิดภาคเรียน ใน N วันข้างหน้า"""
    from app.models import AcadHoliday, AcadYearSetting
    end = today + timedelta(days=days - 1)
    ev = []
    for h in db.query(AcadHoliday).filter(AcadHoliday.year.in_([year, year - 1])).all():
        if not h.month or not h.day:
            continue
        ce = h.year - 543 + (1 if h.month <= 4 else 0)
        try:
            d = date(ce, h.month, h.day)
        except ValueError:
            continue
        if today <= d <= end:
            ev.append((d, h.name or "วันหยุด", "holiday"))
    ys = db.query(AcadYearSetting).filter(AcadYearSetting.year == year).first()
    if ys:
        for col, label, kind in (("t1_start", "เปิดภาคเรียนที่ 1", "open"), ("t1_end", "ปิดภาคเรียนที่ 1", "close"),
                                 ("t2_start", "เปิดภาคเรียนที่ 2", "open"), ("t2_end", "ปิดภาคเรียนที่ 2", "close")):
            v = getattr(ys, col)
            if v and today <= v.date() <= end:
                ev.append((v.date(), label, kind))
    ev.sort()
    return [dict(day=d.day, mon=TH_MS[d.month], wd=TH_WD[d.weekday()], name=n, kind=k,
                 rel="วันนี้" if d == today else "พรุ่งนี้" if d == today + timedelta(days=1) else "")
            for d, n, k in ev]


def build(db, pid):
    from app.routers.academic import _Scope, _acad_year
    from app.thai_utils import current_term
    today = date.today()
    out = dict(today_label=f"วัน{TH_WD[today.weekday()]}ที่ {today.day} {TH_MS[today.month]}",
               lessons=[], sum=None, events=[], homeroom=False)
    try:
        sc = _Scope(int(pid), db)
        year = _acad_year(db)
        out["homeroom"] = bool(sc.homeroom_ids)
        out["lessons"] = today_lessons(db, sc, today)
        if sc.teach_pairs:
            out["sum"] = summary(db, sc, year, current_term())
        out["events"] = week_events(db, year, today)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("teacher_home_acad")
    return out
