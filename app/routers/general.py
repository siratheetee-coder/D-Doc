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


def _project_label(p) -> str:
    return f"{p.name} ({p.plan_year})" if p.plan_year else p.name


def _project_from_text(db, text: str):
    """ช่องโครงการแบบพิมพ์ค้นหา: ตรงกับ 'ชื่อ (ปี)' หรือชื่อโครงการ (ถ้าชื่อซ้ำหลายปี เอาปีล่าสุด)"""
    from app.models import Project
    text = (text or "").strip()
    if not text:
        return None
    rows = db.query(Project).filter(Project.active == True).order_by(Project.plan_year.desc()).all()  # noqa: E712
    for p in rows:
        if _project_label(p) == text:
            return p.id
    for p in rows:
        if p.name == text:
            return p.id
    return None


def _person_by_name(db, name: str):
    from app.models import Person
    name = (name or "").strip()
    return db.query(Person).filter(Person.name == name).first() if name else None


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
    from app.services.fieldtrip import COST_KINDS
    for i, kind in enumerate(("bus", "meal", "entry", "insurance")):
        k = COST_KINDS[kind]
        t.costs.append(FieldTripCost(seq=i, kind=kind, item="", basis=k["basis"], pay_method=k["pay"],
                                     rate=0, times=1))
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
        "d": be_date_input, "reg": ft.REG_NAME,
        "kinds": ft.COST_KINDS, "pays": ft.PAY_METHODS, "vendors": _vendors(db),
        "groups_buy": [dict(g, labels=list(dict.fromkeys(ft.cost_label(x) for x in g["costs"])),
                            mismatch=ft.proc_mismatch(t, g)) for g in ft.procure_groups(t)],
        "travel_total": round(sum(ft.cost_amount(x, c) for x in ft.travel_costs(t)), 2),
        "cash": ft.cash_costs(t), "cash_labels": [ft.cost_label(x) for x in ft.cash_costs(t)],
        "cash_total": round(sum(ft.cost_amount(x, c) for x in ft.cash_costs(t)), 2),
        "project_label": _project_label(t.project) if t.project else "",
        "person_pos": {p.name: p.position or "" for p in persons},
        "need_assist": -(-c["students"] // ft.MAX_PER_ASSISTANT) if c["students"] else 0,
        "cost_warn": {x.id: ft.cost_warnings(x) for x in t.costs},
        "steps": ft.steps(t), "next": ft.next_actions(t), "loan": _loan(db, t),
        "has_proc": _has_module("procurement"), "has_fin": _has_module("finance"),
        "allow_total": sum(ft.cost_amount(x, c) for x in t.costs if x.pay_method == "allowance")})


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
    t.project_id = _project_from_text(db, g("project_text"))
    # ผู้ควบคุม: พิมพ์ชื่อเองหรือเลือกจากทะเบียน (ถ้าชื่อตรงกับทะเบียน ผูก Person ให้)
    t.controller_name, t.controller_pos = g("controller_name"), g("controller_pos")
    p = _person_by_name(db, t.controller_name)
    t.controller_id = p.id if p else None
    if p and not t.controller_pos:
        t.controller_pos = p.position or ""
    keys = {k for k, _, _ in ft.checklist_items(t)}
    t.checklist = json.dumps([k for k in f.getlist("check") if k in keys])

    # ผู้ช่วยผู้ควบคุม: รายชื่อพิมพ์เอง/เลือก (ไม่ซ้ำกันและไม่ซ้ำผู้ควบคุม)
    t.staff.clear()
    db.flush()
    seen = {t.controller_name}
    for i, (nm, pos) in enumerate(zip(f.getlist("staff_name"), f.getlist("staff_pos"))):
        nm, pos = (nm or "").strip(), (pos or "").strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        p = _person_by_name(db, nm)
        t.staff.append(FieldTripStaff(person_id=p.id if p else None, name=nm,
                                      position=pos or ((p.position or "") if p else ""), seq=i))

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

    # ค่าใช้จ่าย (คงลิงก์เรื่องจัดจ้างที่สร้างไปแล้วของแถวเดิม)
    old_proc = {x.id: x.procurement_id for x in t.costs}
    t.costs.clear()
    db.flush()
    rows = zip(f.getlist("cost_id"), f.getlist("cost_kind"), f.getlist("cost_item"), f.getlist("cost_basis"),
               f.getlist("cost_rate"), f.getlist("cost_times"), f.getlist("cost_pay"), f.getlist("cost_vendor"))
    for i, (cid, kind, item, basis, rate, times, pay, vendor) in enumerate(rows):
        kind = kind if kind in ft.COST_KINDS else "other"
        item = (item or "").strip()
        if kind == "other" and not item:
            continue
        pay = pay if pay in ft.PAY_METHODS else ft.COST_KINDS[kind]["pay"]
        vid = int(vendor) if str(vendor).isdigit() and pay == "procure" else None
        pid = old_proc.get(int(cid)) if str(cid).isdigit() else None
        t.costs.append(FieldTripCost(seq=i, kind=kind, item=item,
                                     basis=basis if basis in ft.COST_BASIS else ft.COST_KINDS[kind]["basis"],
                                     rate=_float(rate), times=_float(times, 1.0), pay_method=pay,
                                     vendor_id=vid, procurement_id=pid if vid else None))
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
          "report": fd.render_report, "project": fd.render_project,
          "allowance": fd.render_allowance, "travel": fd.render_travel_claim}.get(kind)
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
            responsible=t.ctrl_name, responsible_pos=t.ctrl_pos,
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



# ---------------- เชื่อมงานพัสดุ / การเงิน ----------------
def _be_year() -> int:
    return datetime.now().year + 543


def _vendors(db):
    from app.models import Vendor
    return db.query(Vendor).order_by(Vendor.name).all()


def _loan(db, t):
    from app.models import MoneyLoan
    return db.get(MoneyLoan, t.loan_id) if t.loan_id else None


def _has_module(key: str) -> bool:
    """โรงเรียนนี้ใช้งานพัสดุ/การเงินได้ไหม (ทัศนศึกษาฟรี แต่ปุ่มสร้างเรื่องต้องใช้งานนั้น)"""
    try:
        from app.tenancy import current_school_id
        from app.accounts import can_use_module
        return bool(can_use_module(current_school_id.get(), key))
    except Exception:
        return True


_UNITS = {"bus": "คัน", "meal": "ชุด", "snack": "ชุด", "lodging": "คน/คืน", "insurance": "คน"}


@router.post("/general/trips/{tid}/vendor")
def trip_vendor_add(tid: int, db: Session = Depends(get_db), name: str = Form(""), owner_name: str = Form(""),
                    tax_id: str = Form(""), phone: str = Form(""), address: str = Form("")):
    """เพิ่มผู้ขาย/ผู้รับจ้างรายใหม่จากหน้าทัศนศึกษา (ทะเบียนผู้ขายเดียวกับงานพัสดุ)"""
    from app.models import Vendor
    _trip_or_404(db, tid)
    if name.strip():
        db.add(Vendor(name=name.strip(), owner_name=owner_name.strip(), tax_id=tax_id.strip(),
                      phone=phone.strip(), address=address.strip()))
        db.commit()
        return RedirectResponse(f"/general/trips/{tid}?msg=เพิ่มผู้ขายแล้ว เลือกได้ในตารางค่าใช้จ่าย#sec-cost",
                                status_code=303)
    return RedirectResponse(f"/general/trips/{tid}#sec-cost", status_code=303)


@router.post("/general/trips/{tid}/procure")
def trip_procure(tid: int, db: Session = Depends(get_db), vendor_id: int = Form(0), inspector_id: int = Form(0)):
    """สร้างเรื่องจัดซื้อ/จัดจ้างในงานพัสดุ 1 เรื่องต่อผู้ขาย จากรายการค่าใช้จ่ายของทัศนศึกษา (สถานะร่าง)"""
    from app.models import Procurement, ProcurementItem, Committee, CommitteeMember, Person
    from app.services import fieldtrip as ft
    from app.thai_utils import current_fiscal_year
    t = _trip_or_404(db, tid)
    back = f"/general/trips/{tid}"
    if not _has_module("procurement"):
        return RedirectResponse(back + "?msg=ต้องใช้งานพัสดุจึงจะสร้างเรื่องจัดซื้อจัดจ้างได้#sec-buy", status_code=303)
    grp = next((g for g in ft.procure_groups(t) if g["vendor_id"] == vendor_id), None)
    if not grp:
        return RedirectResponse(back + "?msg=ไม่พบรายการของผู้ขายนี้#sec-buy", status_code=303)
    if grp["proc"]:
        return RedirectResponse(f"/procurement/{grp['proc'].id}", status_code=303)
    insp = db.get(Person, inspector_id) if inspector_id else None
    if not insp:
        return RedirectResponse(back + "?msg=เลือกผู้ตรวจรับก่อนสร้างเรื่อง#sec-buy", status_code=303)
    c = ft.counts(t)
    ptype = grp["proc_type"]
    labels = [ft.cost_label(x) for x in grp["costs"]]
    subject = f"{ptype}{' '.join(dict.fromkeys(labels))} {t.title or 'ทัศนศึกษา'}".strip()
    when = t.depart_at or datetime.now()
    proc = Procurement(
        fiscal_year=current_fiscal_year(when), subject=subject, proc_type=ptype, proc_case="normal",
        project_id=t.project_id, project_name=t.project.name if t.project else "",
        purpose=(f"เพื่อใช้ในการพานักเรียนไปนอกสถานศึกษา {t.purpose or ''} ณ {t.place or ''} "
                 f"จำนวนนักเรียน {c['students']} คน ครู {c['staff']} คน").strip(),
        total_amount=grp["total"], vendor_id=vendor_id, status="ร่าง",
        request_date=datetime.now(), delivery_due_date=t.depart_at, inspection_mode="single",
        delivery_days=max(1, (when.date() - datetime.now().date()).days) if t.depart_at else 7)
    for x in grp["costs"]:
        heads = {"student": c["students"], "person": c["people"], "staff": c["staff"]}.get(x.basis, 1)
        qty = round(heads * (x.times or 1), 2)
        proc.items.append(ProcurementItem(name=ft.cost_label(x), quantity=qty,
                                          unit=_UNITS.get(x.kind, "รายการ"), unit_price=x.rate or 0))
    ins = Committee(kind="inspect", mode="single")
    ins.members.append(CommitteeMember(name=insp.name, position=insp.position or "ครู",
                                       role="ผู้ตรวจรับพัสดุ", seq=1))
    proc.committees.append(ins)
    db.add(proc)
    db.flush()
    for x in grp["costs"]:
        x.procurement_id = proc.id
    db.commit()
    return RedirectResponse(f"/procurement/{proc.id}", status_code=303)


@router.post("/general/trips/{tid}/loan")
def trip_loan(tid: int, db: Session = Depends(get_db), borrower_id: int = Form(0)):
    """สร้างสัญญายืมเงิน (แบบ 8500) สำหรับรายการที่จ่ายเป็นเงินสดระหว่างทาง"""
    import json
    from app.models import MoneyLoan, Person
    from app.services import fieldtrip as ft
    from app.thai_utils import current_fiscal_year
    t = _trip_or_404(db, tid)
    back = f"/general/trips/{tid}"
    if not _has_module("finance"):
        return RedirectResponse(back + "?msg=ต้องใช้งานการเงินจึงจะสร้างสัญญายืมเงินได้#sec-buy", status_code=303)
    if t.loan_id and db.get(MoneyLoan, t.loan_id):
        return RedirectResponse("/finance/loans", status_code=303)
    who = db.get(Person, borrower_id) if borrower_id else None
    if not who:
        return RedirectResponse(back + "?msg=เลือกผู้ยืมเงินก่อน#sec-buy", status_code=303)
    c = ft.counts(t)
    items = [{"name": ft.cost_label(x), "amount": ft.cost_amount(x, c)} for x in ft.cash_costs(t)]
    school = get_school(db)
    name = (school.name or "").strip()
    ln = MoneyLoan(fiscal_year=current_fiscal_year(t.depart_at or datetime.now()), date=datetime.now(),
                   borrower=who.name, position=who.position or "ครู",
                   submit_to="ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else "ผู้อำนวยการโรงเรียน",
                   fund_from=(t.project.name if t.project else ""),
                   purpose=f"พานักเรียนไปนอกสถานศึกษา {t.title or ''} ณ {t.place or ''}".strip(),
                   items=json.dumps(items, ensure_ascii=False),
                   amount=round(sum(i["amount"] for i in items), 2), within_days=15,
                   note=f"ทัศนศึกษา #{t.id}")
    db.add(ln)
    db.flush()
    t.loan_id = ln.id
    db.commit()
    return RedirectResponse(back + "?msg=สร้างสัญญายืมเงินแล้ว ดาวน์โหลด/บันทึกส่งใช้ได้ที่งานการเงิน#sec-buy",
                            status_code=303)



@router.post("/general/trips/{tid}/procure-sync")
def trip_procure_sync(tid: int, db: Session = Depends(get_db), vendor_id: int = Form(0)):
    """อัปเดตเรื่องจัดจ้าง (ที่ยังเป็นร่าง) ให้ตรงกับทัศนศึกษา: รายการ ยอด วันส่งมอบ โครงการ
    เรื่องที่อนุมัติแล้วไม่แตะรายการ/ยอด (อาจเป็นราคาจริงตามใบเสนอราคา) แก้แค่วันและโครงการ"""
    from app.models import ProcurementItem
    from app.services import fieldtrip as ft
    t = _trip_or_404(db, tid)
    g = next((g for g in ft.procure_groups(t) if g["vendor_id"] == vendor_id and g["proc"]), None)
    if not g:
        return RedirectResponse(f"/general/trips/{tid}#sec-buy", status_code=303)
    proc = g["proc"]
    proc.delivery_due_date = t.depart_at or proc.delivery_due_date
    proc.project_id = t.project_id
    proc.project_name = t.project.name if t.project else ""
    if proc.status == "ร่าง":
        c = ft.counts(t)
        proc.items.clear()
        for x in g["costs"]:
            heads = {"student": c["students"], "person": c["people"], "staff": c["staff"]}.get(x.basis, 1)
            proc.items.append(ProcurementItem(name=ft.cost_label(x), quantity=round(heads * (x.times or 1), 2),
                                              unit=_UNITS.get(x.kind, "รายการ"), unit_price=x.rate or 0))
        proc.total_amount = g["total"]
    db.commit()
    return RedirectResponse(f"/general/trips/{tid}?msg=อัปเดตเรื่อง{g['proc_type']}กับ {g['vendor'].name} แล้ว#sec-buy",
                            status_code=303)
