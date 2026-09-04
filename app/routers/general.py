# -*- coding: utf-8 -*-
"""
general.py - งานบริหารทั่วไป
ฟังก์ชันแรก: บันทึกการมาเรียน (คลิกชื่อนักเรียน -> ลงเวลามาทันที + สรุปสาย/มาทัน)
เข้าถึงได้ทุกบัญชีของโรงเรียน (ไม่อยู่ในระบบคิดเงินโมดูล -> path /general = mod None)
"""
from datetime import datetime, date as _date

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student, Arrival, ArrivalSetting
from app.templating import templates
from app.routers.pages import get_school

router = APIRouter()


def _setting(db: Session) -> ArrivalSetting:
    """คืนแถวตั้งค่าช่วงเวลา (สร้างค่าเริ่มต้นถ้ายังไม่มี)"""
    s = db.query(ArrivalSetting).first()
    if not s:
        s = ArrivalSetting()
        db.add(s)
        db.commit()
    return s


def _today_iso() -> str:
    return _date.today().isoformat()


def _valid_date(s: str) -> str:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except (ValueError, TypeError):
        return _today_iso()


def _status_for(time_hm: str, st: ArrivalSetting) -> str:
    """มาทัน ถ้าเวลามา <= ontime_end · หลังจากนั้น = สาย (เทียบสตริง HH:MM ได้ตรง)"""
    return "ontime" if (time_hm or "") <= (st.ontime_end or "08:00") else "late"


def _class_label(stu: Student) -> str:
    lvl = (stu.level or "").strip()
    room = (stu.room or "").strip()
    if lvl and room:
        return f"{lvl}/{room}"
    return lvl or "-"


def _student_rows(db: Session):
    """รายชื่อนักเรียนทั้งหมด (เรียงชั้น/ห้อง/ชื่อ) สำหรับช่องค้นหา"""
    studs = db.query(Student).order_by(Student.level, Student.room, Student.name).all()
    return [{"id": s.id, "name": s.name, "no": s.student_no or "",
             "cls": _class_label(s)} for s in studs]


def _be(iso: str) -> str:
    """ISO date -> ข้อความไทย เช่น 4 กันยายน 2569"""
    from app.thai_utils import _THAI_MONTHS
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.day} {_THAI_MONTHS[d.month]} {d.year + 543}"
    except (ValueError, TypeError):
        return iso


@router.get("/general", response_class=HTMLResponse)
def general_home(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("general_home.html", {
        "request": request, "school": get_school(db),
    })


@router.get("/general/arrival", response_class=HTMLResponse)
def arrival_page(request: Request, db: Session = Depends(get_db),
                 date: str = "", msg: str = ""):
    day = _valid_date(date)
    st = _setting(db)
    recs = (db.query(Arrival).filter(Arrival.date == day)
            .order_by(Arrival.time).all())
    done_ids = {r.student_id for r in recs}
    rows = []
    for i, r in enumerate(recs, 1):
        s = r.student
        rows.append({"seq": i, "id": r.id, "sid": r.student_id,
                     "name": s.name if s else "-", "no": (s.student_no if s else "") or "",
                     "cls": _class_label(s) if s else "-",
                     "time": r.time, "status": r.status})
    n_late = sum(1 for r in recs if r.status == "late")
    return templates.TemplateResponse("general_arrival.html", {
        "request": request, "school": get_school(db), "day": day, "day_be": _be(day),
        "setting": st, "students": _student_rows(db), "done_ids": list(done_ids),
        "rows": rows, "n_total": len(recs), "n_late": n_late,
        "n_ontime": len(recs) - n_late, "msg": msg,
    })


@router.post("/general/arrival/record")
def arrival_record(request: Request, db: Session = Depends(get_db),
                   student_id: int = Form(...), date: str = Form(""),
                   time: str = Form("")):
    """ลงเวลามาของนักเรียน (คลิกชื่อ) - เวลา = ตอนกด (หรือกรอกเอง) · upsert 1 คน/วัน"""
    day = _valid_date(date)
    stu = db.get(Student, student_id)
    if not stu:
        return JSONResponse({"ok": False, "error": "ไม่พบนักเรียน"}, status_code=404)
    hm = (time or "").strip() or datetime.now().strftime("%H:%M")
    st = _setting(db)
    status = _status_for(hm, st)
    rec = (db.query(Arrival)
           .filter(Arrival.student_id == student_id, Arrival.date == day).first())
    if rec:
        rec.time = hm
        rec.status = status
    else:
        rec = Arrival(student_id=student_id, date=day, time=hm, status=status)
        db.add(rec)
    db.commit()
    db.refresh(rec)
    return JSONResponse({
        "ok": True, "id": rec.id, "sid": student_id, "name": stu.name,
        "no": stu.student_no or "", "cls": _class_label(stu),
        "time": rec.time, "status": rec.status,
    })


@router.post("/general/arrival/{aid}/delete")
def arrival_delete(aid: int, request: Request, db: Session = Depends(get_db),
                   date: str = Form("")):
    rec = db.get(Arrival, aid)
    day = _valid_date(date or (rec.date if rec else ""))
    if rec:
        db.delete(rec)
        db.commit()
    return RedirectResponse(f"/general/arrival?date={day}", status_code=303)


@router.post("/general/arrival/settings")
def arrival_settings(request: Request, db: Session = Depends(get_db),
                     ontime_start: str = Form("07:00"), ontime_end: str = Form("08:00"),
                     late_end: str = Form("09:00"), date: str = Form("")):
    st = _setting(db)
    st.ontime_start = (ontime_start or "07:00").strip()
    st.ontime_end = (ontime_end or "08:00").strip()
    st.late_end = (late_end or "09:00").strip()
    db.commit()
    day = _valid_date(date)
    return RedirectResponse(f"/general/arrival?date={day}&msg=" +
                            "บันทึกช่วงเวลาแล้ว", status_code=303)


@router.get("/general/arrival/print", response_class=HTMLResponse)
def arrival_print(request: Request, db: Session = Depends(get_db), date: str = ""):
    day = _valid_date(date)
    recs = (db.query(Arrival).filter(Arrival.date == day)
            .order_by(Arrival.time).all())
    rows = []
    for i, r in enumerate(recs, 1):
        s = r.student
        rows.append({"seq": i, "name": s.name if s else "-",
                     "no": (s.student_no if s else "") or "", "cls": _class_label(s) if s else "-",
                     "time": r.time, "status": r.status})
    n_late = sum(1 for r in recs if r.status == "late")
    return templates.TemplateResponse("general_arrival_print.html", {
        "request": request, "school": get_school(db), "day_be": _be(day),
        "rows": rows, "n_total": len(recs), "n_late": n_late,
        "n_ontime": len(recs) - n_late,
    })
