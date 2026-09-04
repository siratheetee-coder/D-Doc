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


def _norm_hm(s: str) -> str:
    """ปรับเวลาให้เป็น 24 ชม. 'HH:MM' (เติมศูนย์นำ) · คืน '' ถ้าไม่ถูกต้อง
    รับได้ทั้ง '8:00', '0800', '08:00'"""
    s = (s or "").strip()
    if not s:
        return ""
    if ":" in s:
        parts = s.split(":")
        try:
            h, m = int(parts[0]), int((parts[1] or "0")[:2])
        except ValueError:
            return ""
    else:
        digits = "".join(c for c in s if c.isdigit())
        if not digits:
            return ""
        if len(digits) <= 2:
            h, m = int(digits), 0
        else:
            h, m = int(digits[:-2]), int(digits[-2:])
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return ""


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
    hm = _norm_hm(time) or datetime.now().strftime("%H:%M")
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
    st.ontime_start = _norm_hm(ontime_start) or "07:00"
    st.ontime_end = _norm_hm(ontime_end) or "08:00"
    st.late_end = _norm_hm(late_end) or "09:00"
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


@router.get("/general/arrival/stats", response_class=HTMLResponse)
def arrival_stats(request: Request, db: Session = Depends(get_db),
                  date_from: str = "", date_to: str = "", room: str = ""):
    """สถิติการมาเรียน: สรุปรายห้อง + รายชื่อนักเรียนมาสาย + กราฟ (ช่วงวันที่/กรองตามห้องได้)"""
    from collections import defaultdict
    today = _date.today()
    df = _valid_date(date_from) if date_from else today.replace(day=1).isoformat()
    dt = _valid_date(date_to) if date_to else today.isoformat()
    if df > dt:
        df, dt = dt, df
    recs = (db.query(Arrival)
            .filter(Arrival.date >= df, Arrival.date <= dt).all())
    studs = {s.id: s for s in db.query(Student).all()}

    def rlabel(sid):
        s = studs.get(sid)
        return _class_label(s) if s else "-"

    # รายชื่อห้องที่มีบันทึก (สำหรับ dropdown กรอง)
    rooms = sorted({rlabel(r.student_id) for r in recs})
    room = room if room in rooms else ""
    frecs = [r for r in recs if (not room or rlabel(r.student_id) == room)]

    # รายวัน (ในช่วง/ตามห้องที่กรอง)
    per_day = defaultdict(lambda: [0, 0])   # date -> [total, late]
    for r in frecs:
        per_day[r.date][0] += 1
        per_day[r.date][1] += (r.status == "late")
    day_rows = [{"date": k, "be": _be(k), "total": v[0], "late": v[1]}
                for k, v in sorted(per_day.items())]
    day_max = max([d["total"] for d in day_rows], default=0)

    # รายห้อง (ทุกห้องเสมอ เพื่อเทียบกัน)
    per_room = defaultdict(lambda: [0, 0])
    for r in recs:
        rl = rlabel(r.student_id)
        per_room[rl][0] += 1
        per_room[rl][1] += (r.status == "late")
    room_rows = [{"room": k, "total": v[0], "late": v[1], "ontime": v[0] - v[1],
                  "pct": round(v[1] / v[0] * 100) if v[0] else 0}
                 for k, v in sorted(per_room.items())]
    room_late_max = max([r["late"] for r in room_rows], default=0)

    # รายชื่อนักเรียนที่มาสาย (ในช่วง/ตามห้องที่กรอง)
    per_stu = defaultdict(lambda: [0, 0])   # sid -> [total, late]
    for r in frecs:
        per_stu[r.student_id][0] += 1
        per_stu[r.student_id][1] += (r.status == "late")
    late_students = []
    for sid, (tot, lt) in per_stu.items():
        if lt > 0:
            s = studs.get(sid)
            late_students.append({
                "name": s.name if s else "-", "no": (s.student_no if s else "") or "",
                "room": rlabel(sid), "late": lt, "total": tot,
                "pct": round(lt / tot * 100) if tot else 0})
    late_students.sort(key=lambda x: (-x["late"], -x["pct"], x["name"]))
    late_max = max([x["late"] for x in late_students], default=0)

    n_total = len(frecs)
    n_late = sum(1 for r in frecs if r.status == "late")
    return templates.TemplateResponse("general_arrival_stats.html", {
        "request": request, "school": get_school(db),
        "df": df, "dt": dt, "df_be": _be(df), "dt_be": _be(dt),
        "room": room, "rooms": rooms,
        "day_rows": day_rows, "day_max": day_max,
        "room_rows": room_rows, "room_late_max": room_late_max,
        "late_students": late_students, "late_max": late_max,
        "n_total": n_total, "n_late": n_late, "n_ontime": n_total - n_late,
        "pct_late": round(n_late / n_total * 100) if n_total else 0,
    })
