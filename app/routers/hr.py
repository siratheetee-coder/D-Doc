# -*- coding: utf-8 -*-
"""
hr.py — งานบุคคล (บริหารงานบุคคล)
เฟส 1: ทะเบียนบุคลากร + ทะเบียนวันลา (คำนวณวันลาคงเหลือ) + ใบลา + หนังสือรับรอง
ทะเบียนบุคลากรใช้ตาราง Person ร่วมกับทั้งระบบ (เพิ่มฟิลด์งานบุคคล)
"""
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Person, LeaveRecord, LeaveEntitlement
from app.thai_utils import parse_be_date, be_date_input, thai_date
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PERSON_TYPES = ["ครู", "ผู้บริหาร", "ธุรการ", "นักการภารโรง", "อื่นๆ"]

# ประเภทการลา (ตามระเบียบการลาของข้าราชการ)
LEAVE_TYPES = {
    "sick": "ลาป่วย",
    "personal": "ลากิจส่วนตัว",
    "vacation": "ลาพักผ่อน",
    "maternity": "ลาคลอดบุตร",
    "ordain": "ลาอุปสมบท/ประกอบพิธีทางศาสนา",
}
# สิทธิ์ลาต่อปีตามระเบียบราชการ (วันทำการ) — กดปุ่มตั้งให้อัตโนมัติได้
STD_ENTITLEMENT = {"sick": 60, "personal": 45, "vacation": 10, "maternity": 90, "ordain": 120}


def _cur_year() -> int:
    """ปี พ.ศ. ปัจจุบัน (วันลานับตามปีปฏิทิน)"""
    return datetime.now().year + 543


# ==================== หน้าหลัก ====================
@router.get("/hr", response_class=HTMLResponse)
def hr_home(request: Request, db: Session = Depends(get_db)):
    year = _cur_year()
    persons = db.query(Person).filter(Person.active == True).all()  # noqa: E712
    leaves_year = db.query(LeaveRecord).filter(LeaveRecord.year == year).all()
    return templates.TemplateResponse("hr_home.html", {
        "request": request, "school": get_school(db), "year": year,
        "n_staff": len(persons), "n_leaves": len(leaves_year),
        "days_leaves": sum(l.days or 0 for l in leaves_year),
    })


# ==================== ทะเบียนบุคลากร ====================
@router.get("/hr/staff", response_class=HTMLResponse)
def hr_staff(request: Request, db: Session = Depends(get_db), edit: int | None = None):
    persons = db.query(Person).order_by(Person.active.desc(), Person.id).all()
    return templates.TemplateResponse("hr_staff.html", {
        "request": request, "school": get_school(db), "persons": persons,
        "person_types": PERSON_TYPES, "edit": db.get(Person, edit) if edit else None,
        "today_be": be_date_input(datetime.now()),
    })


def _apply_person_form(p: Person, f: dict):
    p.name = (f.get("name") or "").strip()
    p.position = (f.get("position") or "ครู").strip()
    p.person_type = (f.get("person_type") or "ครู").strip()
    p.rank = (f.get("rank") or "").strip()
    p.id_card = (f.get("id_card") or "").strip()
    p.birthdate = parse_be_date(f.get("birthdate") or "")
    p.start_date = parse_be_date(f.get("start_date") or "")
    p.phone = (f.get("phone") or "").strip()
    p.email = (f.get("email") or "").strip()
    p.salary = _to_float(f.get("salary"), 0.0)
    p.active = (f.get("active") or "1") == "1"


@router.post("/hr/staff/add")
async def hr_staff_add(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    if (f.get("name") or "").strip():
        p = Person()
        _apply_person_form(p, f)
        db.add(p); db.commit()
    return RedirectResponse("/hr/staff", status_code=303)


@router.post("/hr/staff/{pid}/update")
async def hr_staff_update(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if p:
        f = await request.form()
        if (f.get("name") or "").strip():
            _apply_person_form(p, f)
            db.commit()
    return RedirectResponse("/hr/staff", status_code=303)


@router.post("/hr/staff/{pid}/delete")
def hr_staff_delete(pid: int, db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if p:
        db.delete(p); db.commit()
    return RedirectResponse("/hr/staff", status_code=303)


# ==================== ทะเบียนวันลา ====================
def _entitlements(db, year) -> dict:
    ent = {e.leave_type: (e.days or 0) for e in
           db.query(LeaveEntitlement).filter(LeaveEntitlement.year == year).all()}
    return {k: ent.get(k, 0) for k in LEAVE_TYPES}


@router.get("/hr/leave", response_class=HTMLResponse)
def hr_leave(request: Request, db: Session = Depends(get_db), year: int | None = None):
    year = year or _cur_year()
    ent = _entitlements(db, year)
    records = (db.query(LeaveRecord).filter(LeaveRecord.year == year)
               .order_by(LeaveRecord.start_date.desc(), LeaveRecord.id.desc()).all())
    persons = db.query(Person).filter(Person.active == True).order_by(Person.id).all()  # noqa: E712
    # สรุปวันลาต่อคน แยกประเภท (ใช้ไป / คงเหลือ)
    used = {}   # {person_id: {leave_type: days}}
    for r in records:
        used.setdefault(r.person_id, {}).setdefault(r.leave_type, 0.0)
        used[r.person_id][r.leave_type] += r.days or 0
    summary = []
    for p in persons:
        u = used.get(p.id, {})
        rows = {lt: {"used": u.get(lt, 0.0), "remain": (ent.get(lt, 0) - u.get(lt, 0.0))}
                for lt in LEAVE_TYPES}
        summary.append({"p": p, "rows": rows, "total_used": sum(u.values())})
    years = sorted({year} | {r[0] for r in db.query(LeaveRecord.year).distinct()}, reverse=True)
    return templates.TemplateResponse("hr_leave.html", {
        "request": request, "school": get_school(db), "year": year, "years": years,
        "leave_types": LEAVE_TYPES, "ent": ent, "records": records, "persons": persons,
        "summary": summary, "std": STD_ENTITLEMENT, "today_be": be_date_input(datetime.now()),
    })


@router.post("/hr/leave/add")
def hr_leave_add(db: Session = Depends(get_db), person_id: str = Form(""),
                 leave_type: str = Form("sick"), start_date: str = Form(""),
                 end_date: str = Form(""), days: str = Form("0"),
                 reason: str = Form(""), contact: str = Form(""),
                 doc_no: str = Form(""), year: str = Form("")):
    pid = _to_int(person_id, 0)
    yr = _to_int(year, _cur_year())
    lt = leave_type if leave_type in LEAVE_TYPES else "sick"
    if pid and db.get(Person, pid):
        db.add(LeaveRecord(person_id=pid, year=yr, leave_type=lt,
                           start_date=parse_be_date(start_date), end_date=parse_be_date(end_date),
                           days=_to_float(days, 0.0), reason=reason.strip(),
                           contact=contact.strip(), doc_no=doc_no.strip()))
        db.commit()
    return RedirectResponse(f"/hr/leave?year={yr}", status_code=303)


@router.post("/hr/leave/{lid}/delete")
def hr_leave_delete(lid: int, db: Session = Depends(get_db)):
    r = db.get(LeaveRecord, lid)
    yr = r.year if r else _cur_year()
    if r:
        db.delete(r); db.commit()
    return RedirectResponse(f"/hr/leave?year={yr}", status_code=303)


def _set_entitlement(db, year, mapping):
    for lt in LEAVE_TYPES:
        e = (db.query(LeaveEntitlement)
             .filter(LeaveEntitlement.year == year, LeaveEntitlement.leave_type == lt).first())
        if not e:
            e = LeaveEntitlement(year=year, leave_type=lt)
            db.add(e)
        e.days = float(mapping.get(lt, 0) or 0)
    db.commit()


@router.post("/hr/leave/entitlement")
async def hr_leave_entitlement(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    year = _to_int(f.get("year"), _cur_year())
    _set_entitlement(db, year, {lt: _to_float(f.get(f"ent_{lt}"), 0.0) for lt in LEAVE_TYPES})
    return RedirectResponse(f"/hr/leave?year={year}", status_code=303)


@router.post("/hr/leave/entitlement/standard")
def hr_leave_entitlement_std(db: Session = Depends(get_db), year: str = Form("")):
    yr = _to_int(year, _cur_year())
    _set_entitlement(db, yr, STD_ENTITLEMENT)
    return RedirectResponse(f"/hr/leave?year={yr}", status_code=303)


# ==================== เอกสาร (Word) ====================
@router.get("/hr/leave/{lid}/form.docx")
def hr_leave_form_docx(lid: int, db: Session = Depends(get_db)):
    from app.services.hr_doc import render_leave_form
    r = db.get(LeaveRecord, lid)
    if not r:
        return RedirectResponse("/hr/leave", status_code=303)
    path = render_leave_form(get_school(db), r.person, r, LEAVE_TYPES.get(r.leave_type, r.leave_type))
    return serve_generated(path, _DOCX)


@router.get("/hr/staff/{pid}/certificate.docx")
def hr_certificate_docx(pid: int, db: Session = Depends(get_db), kind: str = "status"):
    from app.services.hr_doc import render_certificate
    p = db.get(Person, pid)
    if not p:
        return RedirectResponse("/hr/staff", status_code=303)
    path = render_certificate(get_school(db), p, kind)
    return serve_generated(path, _DOCX)
