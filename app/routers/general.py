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
    """คืนวันที่เป็น ISO 'YYYY-MM-DD' · รับได้ทั้งไทย (วว/ดด/ปปปป) และ ISO · ว่าง/ผิด = วันนี้"""
    from app.thai_utils import parse_be_date
    dt = parse_be_date(s)
    return dt.date().isoformat() if dt else _today_iso()


def _be_input(iso: str) -> str:
    """ISO -> ค่าช่องกรอกแบบไทย 'วว/ดด/ปปปป' (พ.ศ.)"""
    from app.thai_utils import be_date_input
    try:
        return be_date_input(datetime.strptime(iso, "%Y-%m-%d"))
    except (ValueError, TypeError):
        return ""


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
        "day_input": _be_input(day),
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
        "df_input": _be_input(df), "dt_input": _be_input(dt),
        "room": room, "rooms": rooms,
        "day_rows": day_rows, "day_max": day_max,
        "room_rows": room_rows, "room_late_max": room_late_max,
        "late_students": late_students, "late_max": late_max,
        "n_total": n_total, "n_late": n_late, "n_ontime": n_total - n_late,
        "pct_late": round(n_late / n_total * 100) if n_total else 0,
    })


# ============================================================
# ทัศนศึกษา (พานักเรียนไปนอกสถานศึกษา) - ระเบียบ ศธ. พ.ศ. 2562
# ============================================================
def _trip_or_404(db, tid):
    from fastapi import HTTPException
    from app.models import FieldTrip
    t = db.get(FieldTrip, tid)
    if not t:
        raise HTTPException(404)
    return t


def _dt(date_s: str, time_s: str = ""):
    from app.thai_utils import parse_be_date
    d = parse_be_date(date_s or "")
    if not d:
        return None
    hm = _norm_hm(time_s)
    if hm:
        h, m = hm.split(":")
        d = d.replace(hour=int(h), minute=int(m))
    return d


def _float(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/general/trips", response_class=HTMLResponse)
def trips_list(request: Request, db: Session = Depends(get_db)):
    from app.models import FieldTrip
    from app.services import fieldtrip as ft
    trips = db.query(FieldTrip).order_by(FieldTrip.id.desc()).all()
    rows = [{"t": t, "c": ft.counts(t), "total": ft.total_cost(t),
             "warn": sum(1 for lv, _ in ft.warnings(t) if lv in ("error", "warn"))} for t in trips]
    return templates.TemplateResponse("general_trips.html", {
        "request": request, "school": get_school(db), "rows": rows,
        "types": ft.TRIP_TYPES, "status": ft.STATUS})


@router.post("/general/trips/new")
def trip_new(db: Session = Depends(get_db)):
    from app.models import FieldTrip, FieldTripCost
    from app.thai_utils import current_academic_year
    school = get_school(db)
    t = FieldTrip(year=getattr(school, "academic_year", None) or current_academic_year(),
                  title="ทัศนศึกษา", responsible=school.name or "", request_date=datetime.now())
    # รายการที่พบบ่อย - อัตราเว้นว่างให้โรงเรียนกรอกเอง (ระบบไม่เดาอัตรา)
    for i, (item, basis) in enumerate((("ค่าจ้างเหมารถโดยสาร", "lump"), ("ค่าอาหารและอาหารว่าง", "person"),
                                       ("ค่าเข้าชมสถานที่", "student"), ("ค่าประกันภัยการเดินทาง", "student"))):
        t.costs.append(FieldTripCost(seq=i, item=item, basis=basis, rate=0, times=1))
    db.add(t)
    db.commit()
    return RedirectResponse(f"/general/trips/{t.id}", status_code=303)


@router.get("/general/trips/{tid}", response_class=HTMLResponse)
def trip_detail(tid: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    from app.models import Person, Student, Project
    from app.services import fieldtrip as ft
    from app.services.budget import project_budget, project_remaining
    from app.thai_utils import be_date_input
    t = _trip_or_404(db, tid)
    school = get_school(db)
    c = ft.counts(t)
    persons = db.query(Person).filter(Person.active == True).order_by(Person.id).all()  # noqa: E712
    students = db.query(Student).order_by(Student.level, Student.room, Student.student_no, Student.name).all()
    projects = (db.query(Project).filter(Project.active == True)  # noqa: E712
                .order_by(Project.plan_year.desc(), Project.name).all())
    proj = None
    if t.project:
        proj = {"budget": project_budget(t.project), "remaining": project_remaining(t.project)}
    groups = {}
    for s in students:
        groups.setdefault(f"{s.level}/{s.room}" if s.room else (s.level or "ไม่ระบุชั้น"), []).append(s)
    return templates.TemplateResponse("general_trip.html", {
        "request": request, "school": school, "t": t, "c": c, "msg": msg,
        "total": ft.total_cost(t), "amounts": {x.id: ft.cost_amount(x, c) for x in t.costs},
        "warnings": ft.warnings(t), "types": ft.TRIP_TYPES, "status": ft.STATUS,
        "checklist": ft.checklist_items(t), "done": ft.checklist_done(t),
        "basis": ft.COST_BASIS, "persons": persons, "groups": groups,
        "picked": {s.student_id for s in t.students}, "staff_ids": [s.person_id for s in t.staff],
        "projects": projects, "proj": proj, "approver": ft.approver_title(t, school),
        "d": be_date_input, "reg": ft.REG_NAME})


@router.post("/general/trips/{tid}/save")
async def trip_save(tid: int, request: Request, db: Session = Depends(get_db)):
    import json
    from app.models import Person, Student, FieldTripStaff, FieldTripStudent, FieldTripCost
    from app.services import fieldtrip as ft
    t = _trip_or_404(db, tid)
    f = await request.form()

    def g(k):
        return (f.get(k) or "").strip()

    for k in ("title", "purpose", "place", "province", "route", "vehicle", "lodging", "request_to",
              "principle", "objectives", "targets", "steps", "responsible", "emergency_plan",
              "result", "result_detail"):
        setattr(t, k, g(k))
    t.trip_type = g("trip_type") if g("trip_type") in ft.TRIP_TYPES else "day"
    t.depart_at = _dt(g("depart_date"), g("depart_time"))
    t.return_at = _dt(g("return_date"), g("return_time"))
    t.request_date = _dt(g("request_date"))
    t.report_date = _dt(g("report_date"))
    t.project_id = int(g("project_id")) if g("project_id").isdigit() else None
    t.controller_id = int(g("controller_id")) if g("controller_id").isdigit() else None
    keys = {k for k, _, _ in ft.checklist_items(t)}
    t.checklist = json.dumps([k for k in f.getlist("check") if k in keys])

    # ผู้ช่วยผู้ควบคุม (ไม่ซ้ำกับผู้ควบคุม)
    want = [int(x) for x in f.getlist("staff") if str(x).isdigit() and int(x) != t.controller_id]
    t.staff.clear()
    db.flush()
    for i, pid in enumerate(dict.fromkeys(want)):
        p = db.get(Person, pid)
        if p:
            t.staff.append(FieldTripStaff(person_id=p.id, name=p.name, position=p.position or "", seq=i))

    # นักเรียน: คงผลยินยอมเดิมของคนที่ยังอยู่ในรายชื่อ
    want_st = [int(x) for x in f.getlist("student") if str(x).isdigit()]
    old = {s.student_id: s.consent for s in t.students}
    t.students.clear()
    db.flush()
    for i, sid in enumerate(dict.fromkeys(want_st)):
        s = db.get(Student, sid)
        if s:
            t.students.append(FieldTripStudent(student_id=s.id, name=s.name, sex=s.sex or "",
                                               level=s.level or "", room=s.room or "", seq=i,
                                               consent=old.get(s.id, "")))

    # ค่าใช้จ่าย
    t.costs.clear()
    db.flush()
    rows = zip(f.getlist("cost_item"), f.getlist("cost_basis"), f.getlist("cost_rate"), f.getlist("cost_times"))
    for i, (item, basis, rate, times) in enumerate(rows):
        item = (item or "").strip()
        if item:
            t.costs.append(FieldTripCost(seq=i, item=item, basis=basis if basis in ft.COST_BASIS else "student",
                                         rate=_float(rate), times=_float(times, 1.0)))
    db.commit()
    return RedirectResponse(f"/general/trips/{tid}?msg=บันทึกแล้ว", status_code=303)


@router.post("/general/trips/{tid}/consent")
async def trip_consent(tid: int, request: Request, db: Session = Depends(get_db)):
    t = _trip_or_404(db, tid)
    f = await request.form()
    for s in t.students:
        v = f.get(f"c{s.id}", "")
        s.consent = v if v in ("yes", "no") else ""
    db.commit()
    return RedirectResponse(f"/general/trips/{tid}?msg=บันทึกผลการตอบรับแล้ว#consent", status_code=303)


@router.post("/general/trips/{tid}/drop-refused")
def trip_drop_refused(tid: int, db: Session = Depends(get_db)):
    t = _trip_or_404(db, tid)
    for s in [s for s in t.students if s.consent == "no"]:
        t.students.remove(s)
    db.commit()
    return RedirectResponse(f"/general/trips/{tid}?msg=นำนักเรียนที่ผู้ปกครองไม่อนุญาตออกแล้ว#consent",
                            status_code=303)


@router.post("/general/trips/{tid}/status")
def trip_status(tid: int, db: Session = Depends(get_db), status: str = Form("")):
    from app.services import fieldtrip as ft
    t = _trip_or_404(db, tid)
    if status in ft.STATUS:
        t.status = status
        db.commit()
    return RedirectResponse(f"/general/trips/{tid}", status_code=303)


@router.post("/general/trips/{tid}/delete")
def trip_delete(tid: int, db: Session = Depends(get_db)):
    t = _trip_or_404(db, tid)
    db.delete(t)
    db.commit()
    return RedirectResponse("/general/trips", status_code=303)


@router.get("/general/trips/{tid}/doc/{kind}.docx")
def trip_doc(tid: int, kind: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    from app.routers.pages import serve_generated
    from app.services import fieldtrip_doc as fd
    t = _trip_or_404(db, tid)
    fn = {"request": fd.render_request, "parents": fd.render_parent_letters,
          "report": fd.render_report, "project": fd.render_project}.get(kind)
    if not fn:
        raise HTTPException(404)
    return serve_generated(fn(t, get_school(db)), _DOCX, count=False)


@router.post("/general/trips/{tid}/order")
def trip_order(tid: int, db: Session = Depends(get_db)):
    """ออกคำสั่งแต่งตั้งผู้ควบคุม/ผู้ช่วยผู้ควบคุม -> เก็บเป็นคำสั่งโรงเรียน (เลขจากทะเบียนเลขกลาง)"""
    from app.models import SchoolOrder
    from app.services.doc_number import suggest_doc_no, commit_doc_no
    from app.services.fieldtrip_doc import order_body
    from app.thai_utils import current_fiscal_year
    t = _trip_or_404(db, tid)
    o = db.get(SchoolOrder, t.order_id) if t.order_id else None
    subject = f"แต่งตั้งผู้ควบคุมและผู้ช่วยผู้ควบคุมการพานักเรียนไปนอกสถานศึกษา ({t.title})"
    if not o:
        fy = current_fiscal_year()
        o = SchoolOrder(fiscal_year=fy, date=datetime.now(), subject=subject)
        db.add(o)
        db.flush()
        o.order_no = suggest_doc_no(db, "command", fy)
        commit_doc_no(db, "command", fy, o.order_no, source="admin", ref_id=o.id, subject=subject, date=o.date)
        t.order_id = o.id
    o.subject = subject
    o.body = order_body(t, get_school(db))
    db.commit()
    return RedirectResponse(f"/general/trips/{tid}?msg=ออกคำสั่งเลขที่ {o.order_no} แล้ว", status_code=303)


@router.get("/general/trips/{tid}/order.docx")
def trip_order_doc(tid: int, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    from app.models import SchoolOrder
    from app.routers.pages import serve_generated
    from app.services.office_doc import render_order
    t = _trip_or_404(db, tid)
    o = db.get(SchoolOrder, t.order_id) if t.order_id else None
    if not o:
        raise HTTPException(404)
    return serve_generated(render_order(o, get_school(db)), _DOCX, count=False)


@router.post("/general/trips/{tid}/project-report")
def trip_project_report(tid: int, db: Session = Depends(get_db)):
    """สร้าง/เปิดรายงานโครงการ (ระบบรายงานผลโครงการเดิม) เติมข้อมูลจากการไปทัศนศึกษาให้"""
    import json
    from app.models import ProjectReport
    from app.services import fieldtrip as ft
    t = _trip_or_404(db, tid)
    if not t.project_id:
        return RedirectResponse(f"/general/trips/{tid}?msg=เลือกโครงการในแผนก่อน จึงจะทำรายงานโครงการได้",
                                status_code=303)
    rep = db.get(ProjectReport, t.report_id) if t.report_id else None
    if not rep:
        c = ft.counts(t)

        def lines(s):
            return [x.strip() for x in (s or "").splitlines() if x.strip()]

        qty = lines(t.targets) or [f"นักเรียน จำนวน {c['students']} คน ครูควบคุม จำนวน {c['staff']} คน"]
        rep = ProjectReport(
            project_id=t.project_id, title=t.title or "", date_start=t.depart_at, date_end=t.return_at,
            location=" จังหวัด".join(x for x in (t.place, t.province) if x),
            responsible=t.controller.name if t.controller else "",
            responsible_pos=(t.controller.position or "") if t.controller else "",
            principles=t.principle or "",
            objectives=json.dumps(lines(t.objectives), ensure_ascii=False),
            target_qty=json.dumps(qty, ensure_ascii=False),
            steps_items=json.dumps([{"act": s, "period": "", "who": ""} for s in lines(t.steps)],
                                   ensure_ascii=False),
            budget_planned=ft.total_cost(t), budget_note="ทัศนศึกษา")
        db.add(rep)
        db.flush()
        t.report_id = rep.id
        db.commit()
    return RedirectResponse(f"/project-reports/{rep.id}", status_code=303)
