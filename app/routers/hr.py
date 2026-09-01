# -*- coding: utf-8 -*-
"""
hr.py - งานบุคคล (บริหารงานบุคคล)
เฟส 1: ทะเบียนบุคลากร + ทะเบียนวันลา (คำนวณวันลาคงเหลือ) + ใบลา + หนังสือรับรอง
ทะเบียนบุคลากรใช้ตาราง Person ร่วมกับทั้งระบบ (เพิ่มฟิลด์งานบุคคล)
"""
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Person, LeaveRecord, LeaveEntitlement, TravelRecord,
                        Decoration, RankHistory, LeaveRequest, TravelRequest,
                        ClassroomVisit, Supervision)
from app.thai_utils import parse_be_date, be_date_input, thai_date, current_academic_year
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
# สิทธิ์ลาต่อปีตามระเบียบราชการ (วันทำการ) - กดปุ่มตั้งให้อัตโนมัติได้
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


# ==================== ประวัติบุคลากร (ก.พ.7) ====================
@router.get("/hr/staff/{pid}", response_class=HTMLResponse)
def hr_profile(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Person, pid)
    if not p:
        return RedirectResponse("/hr/staff", status_code=303)
    leaves = sorted(p.leaves, key=lambda l: (l.start_date or datetime.min), reverse=True)
    travels = sorted(p.travels, key=lambda t: (t.start_date or datetime.min), reverse=True)
    return templates.TemplateResponse("hr_profile.html", {
        "request": request, "school": get_school(db), "p": p,
        "leave_types": LEAVE_TYPES, "leaves": leaves[:20], "travels": travels[:20],
        "decorations": sorted(p.decorations, key=lambda d: (d.year or 0)),
        "rank_history": sorted(p.rank_history, key=lambda r: (r.date or datetime.min)),
        "leave_days": sum(l.days or 0 for l in p.leaves),
        "travel_days": sum(t.days or 0 for t in p.travels),
    })


@router.post("/hr/staff/{pid}/decoration/add")
def hr_decoration_add(pid: int, db: Session = Depends(get_db), name: str = Form(""),
                      year: str = Form(""), ref: str = Form("")):
    if db.get(Person, pid) and name.strip():
        db.add(Decoration(person_id=pid, name=name.strip(),
                          year=_to_int(year, 0) or None, ref=ref.strip()))
        db.commit()
    return RedirectResponse(f"/hr/staff/{pid}", status_code=303)


@router.post("/hr/decoration/{did}/delete")
def hr_decoration_delete(did: int, db: Session = Depends(get_db)):
    d = db.get(Decoration, did)
    pid = d.person_id if d else None
    if d:
        db.delete(d); db.commit()
    return RedirectResponse(f"/hr/staff/{pid}" if pid else "/hr/staff", status_code=303)


@router.post("/hr/staff/{pid}/rank/add")
def hr_rank_add(pid: int, db: Session = Depends(get_db), date: str = Form(""),
                position: str = Form(""), rank: str = Form(""), doc_no: str = Form(""),
                note: str = Form("")):
    if db.get(Person, pid) and (position.strip() or rank.strip()):
        db.add(RankHistory(person_id=pid, date=parse_be_date(date), position=position.strip(),
                           rank=rank.strip(), doc_no=doc_no.strip(), note=note.strip()))
        db.commit()
    return RedirectResponse(f"/hr/staff/{pid}", status_code=303)


@router.post("/hr/rank/{rid}/delete")
def hr_rank_delete(rid: int, db: Session = Depends(get_db)):
    r = db.get(RankHistory, rid)
    pid = r.person_id if r else None
    if r:
        db.delete(r); db.commit()
    return RedirectResponse(f"/hr/staff/{pid}" if pid else "/hr/staff", status_code=303)


@router.get("/hr/staff/{pid}/kp7.docx")
def hr_kp7_docx(pid: int, db: Session = Depends(get_db)):
    from app.services.hr_doc import render_kp7
    p = db.get(Person, pid)
    if not p:
        return RedirectResponse("/hr/staff", status_code=303)
    path = render_kp7(get_school(db), p)
    return serve_generated(path, _DOCX)


# ==================== ทะเบียนไปราชการ ====================
@router.get("/hr/travel", response_class=HTMLResponse)
def hr_travel(request: Request, db: Session = Depends(get_db), year: int | None = None):
    year = year or _cur_year()
    records = (db.query(TravelRecord).filter(TravelRecord.year == year)
               .order_by(TravelRecord.start_date.desc(), TravelRecord.id.desc()).all())
    persons = db.query(Person).filter(Person.active == True).order_by(Person.id).all()  # noqa: E712
    # สรุปวันไปราชการต่อคน
    by_person = {}
    for r in records:
        by_person.setdefault(r.person_id, {"days": 0.0, "n": 0, "budget": 0.0})
        by_person[r.person_id]["days"] += r.days or 0
        by_person[r.person_id]["n"] += 1
        by_person[r.person_id]["budget"] += r.budget or 0
    summary = [{"p": p, **by_person[p.id]} for p in persons if p.id in by_person]
    years = sorted({year} | {r[0] for r in db.query(TravelRecord.year).distinct()}, reverse=True)
    # record_id ที่มีไฟล์บันทึกซึ่งครูแนบมาตอนยื่นคำขอ (โชว์ปุ่มเปิดไฟล์จริงแทนบันทึกที่ระบบสร้าง)
    rids = [r.id for r in records]
    req_atts = {}
    if rids:
        req_atts = {q.record_id: q.attachment_name for q in
                    db.query(TravelRequest).filter(TravelRequest.record_id.in_(rids),
                                                   TravelRequest.attachment_name != "").all()}
    return templates.TemplateResponse("hr_travel.html", {
        "request": request, "school": get_school(db), "year": year, "years": years,
        "records": records, "persons": persons, "summary": summary,
        "req_atts": req_atts,
        "total_days": sum(r.days or 0 for r in records),
        "total_budget": sum(r.budget or 0 for r in records),
    })


@router.post("/hr/travel/add")
def hr_travel_add(db: Session = Depends(get_db), person_id: str = Form(""),
                  subject: str = Form(""), place: str = Form(""), start_date: str = Form(""),
                  end_date: str = Form(""), days: str = Form("0"), budget: str = Form("0"),
                  doc_no: str = Form(""), doc_date: str = Form(""), note: str = Form(""),
                  year: str = Form("")):
    pid = _to_int(person_id, 0)
    yr = _to_int(year, _cur_year())
    if pid and db.get(Person, pid):
        db.add(TravelRecord(person_id=pid, year=yr, subject=subject.strip(), place=place.strip(),
                            start_date=parse_be_date(start_date), end_date=parse_be_date(end_date),
                            days=_to_float(days, 0.0), budget=_to_float(budget, 0.0),
                            doc_no=doc_no.strip(), doc_date=parse_be_date(doc_date), note=note.strip()))
        db.commit()
    return RedirectResponse(f"/hr/travel?year={yr}", status_code=303)


@router.post("/hr/travel/{tid}/delete")
def hr_travel_delete(tid: int, db: Session = Depends(get_db)):
    r = db.get(TravelRecord, tid)
    yr = r.year if r else _cur_year()
    if r:
        db.delete(r); db.commit()
    return RedirectResponse(f"/hr/travel?year={yr}", status_code=303)


def _serve_blob(data: bytes, name: str):
    """ส่งไฟล์ BLOB (ครูแนบ) ให้เปิด/ดาวน์โหลด - RFC5987 กันชื่อไฟล์ไทย 500"""
    import mimetypes
    from urllib.parse import quote
    from fastapi.responses import Response
    ctype = mimetypes.guess_type(name or "")[0] or "application/octet-stream"
    fn = quote(name or "attachment")
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{fn}"})


@router.get("/hr/travel/{tid}/request.docx")
def hr_travel_request_docx(tid: int, db: Session = Depends(get_db)):
    """บันทึกขออนุญาตไปราชการ - ถ้าครูแนบไฟล์ตอนยื่นคำขอ ให้เปิดไฟล์นั้น
    (ไฟล์ที่เซ็นสมบูรณ์) มิฉะนั้น fallback เป็นบันทึกที่ระบบสร้างให้"""
    from app.services.hr_doc import render_travel_request
    r = db.get(TravelRecord, tid)
    if not r:
        return RedirectResponse("/hr/travel", status_code=303)
    q = db.query(TravelRequest).filter_by(record_id=tid).first()
    if q and q.attachment:
        return _serve_blob(q.attachment, q.attachment_name)
    return serve_generated(render_travel_request(get_school(db), r.person, r), _DOCX)


@router.get("/hr/travel/{tid}/order.docx")
def hr_travel_order_docx(tid: int, db: Session = Depends(get_db)):
    from app.services.hr_doc import render_travel_order
    r = db.get(TravelRecord, tid)
    if not r:
        return RedirectResponse("/hr/travel", status_code=303)
    path = render_travel_order(get_school(db), r.person, r)
    return serve_generated(path, _DOCX)


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
def hr_certificate_docx(pid: int, db: Session = Depends(get_db)):
    """หนังสือรับรองบุคลากร (ฟอร์มราชการ + ลายเซ็น ผอ.)"""
    from app.services.hr_doc import render_certificate
    p = db.get(Person, pid)
    if not p:
        return RedirectResponse("/hr/staff", status_code=303)
    path = render_certificate(get_school(db), p)
    return serve_generated(path, _DOCX)


# ==================== ใบลาที่ครูส่งเข้าระบบ (อนุมัติ + แจ้งผล) ====================
@router.get("/hr/leave-requests", response_class=HTMLResponse)
def leave_requests_page(request: Request, db: Session = Depends(get_db), msg: str = "", err: str = ""):
    reqs = db.query(LeaveRequest).all()
    reqs.sort(key=lambda r: (r.status != "pending", r.submitted_at or datetime.min), reverse=False)
    # pending ก่อน แล้วเรียงใหม่->เก่า
    reqs.sort(key=lambda r: (r.status != "pending", -(r.submitted_at.timestamp() if r.submitted_at else 0)))
    n_pending = sum(1 for r in reqs if r.status == "pending")
    return templates.TemplateResponse("hr_leave_requests.html", {
        "request": request, "school": get_school(db), "reqs": reqs,
        "n_pending": n_pending, "be_date": be_date_input, "msg": msg, "err": err,
    })


# แปลงประเภทลา (ป้ายไทยจากใบลา) -> คีย์ในทะเบียนวันลา
_LEAVE_KEY = {"ลาป่วย": "sick", "ลากิจส่วนตัว": "personal", "ลากิจ": "personal",
              "ลาพักผ่อน": "vacation", "ลาคลอดบุตร": "maternity",
              "ลาอุปสมบท": "ordain", "ลาอุปสมบท/ประกอบพิธีทางศาสนา": "ordain"}


def _notify(to, subject, html):
    to = (to or "").strip()
    if not to:
        return
    try:
        from app.services.mailer import send_email
        send_email(to, subject, html)
    except Exception:
        pass


@router.post("/hr/leave-requests/{lid}/decide")
def leave_request_decide(lid: int, request: Request, db: Session = Depends(get_db),
                         status: str = Form(""), comment: str = Form("")):
    r = db.get(LeaveRequest, lid)
    if r and status in ("approved", "rejected"):
        r.status = status
        r.comment = (comment or "").strip()
        r.decided_at = datetime.now()
        # อนุมัติแล้วลงทะเบียนวันลาอัตโนมัติ (ครั้งเดียว - กันลงซ้ำด้วย record_id)
        if status == "approved" and not r.record_id:
            yr = (r.start_date.year + 543) if r.start_date else _cur_year()
            rec = LeaveRecord(person_id=r.person_id, year=yr,
                              leave_type=_LEAVE_KEY.get((r.leave_type or "").strip(), "personal"),
                              start_date=r.start_date, end_date=r.end_date,
                              days=r.days or 0, reason=r.reason or "", contact=r.contact or "")
            db.add(rec); db.flush(); r.record_id = rec.id
        res = "อนุมัติ" if status == "approved" else "ไม่อนุมัติ"
        from app.services.nav import create_notice
        create_notice(db, r.person_id, f"ผลใบลา: {res}",
                      reason=f"{r.leave_type} {be_date_input(r.start_date)}-{be_date_input(r.end_date)}"
                             + (f" · {r.comment}" if r.comment else ""),
                      link="/me/leave",
                      level=("info" if status == "approved" else "warn"))
        db.commit()
        # แจ้งผลกลับครูทางอีเมล (ถ้ามีอีเมลในทะเบียนบุคลากร)
        person = db.get(Person, r.person_id)
        if person and (person.email or "").strip():
            _notify(person.email, f"[ผลใบลา] {r.leave_type} - {res}",
                    f"<p>ใบลา ({r.leave_type} {be_date_input(r.start_date)} ถึง {be_date_input(r.end_date)}) "
                    f"ได้รับการพิจารณาแล้ว: <b>{res}</b></p>"
                    f"<p>ความเห็น: {r.comment or '-'}</p>")
    return RedirectResponse("/hr/leave-requests?msg=บันทึกผลการพิจารณาแล้ว", status_code=303)


@router.post("/hr/leave-requests/{lid}/delete")
def leave_request_delete(lid: int, db: Session = Depends(get_db)):
    """ลบคำขอใบลา · ถ้าเคยอนุมัติแล้ว (มี record_id) ลบรายการในทะเบียนวันลาที่ผูกกันด้วย"""
    r = db.get(LeaveRequest, lid)
    if r:
        if r.record_id:
            rec = db.get(LeaveRecord, r.record_id)
            if rec:
                db.delete(rec)
        db.delete(r); db.commit()
    return RedirectResponse("/hr/leave-requests?msg=ลบคำขอใบลาแล้ว", status_code=303)


# ==================== ขอไปราชการที่ครูส่งเข้าระบบ (อนุมัติ + ลงทะเบียน + แจ้ง) ====================
@router.get("/hr/travel-requests", response_class=HTMLResponse)
def travel_requests_page(request: Request, db: Session = Depends(get_db), msg: str = "", err: str = ""):
    reqs = db.query(TravelRequest).all()
    reqs.sort(key=lambda r: (r.status != "pending",
                             -(r.submitted_at.timestamp() if r.submitted_at else 0)))
    n_pending = sum(1 for r in reqs if r.status == "pending")
    return templates.TemplateResponse("hr_travel_requests.html", {
        "request": request, "school": get_school(db), "reqs": reqs,
        "n_pending": n_pending, "be_date": be_date_input, "msg": msg, "err": err,
    })


@router.post("/hr/travel-requests/{tid}/decide")
def travel_request_decide(tid: int, request: Request, db: Session = Depends(get_db),
                          status: str = Form(""), comment: str = Form("")):
    from datetime import datetime as _dt
    r = db.get(TravelRequest, tid)
    if r and status in ("approved", "rejected"):
        r.status = status
        r.comment = (comment or "").strip()
        r.decided_at = _dt.now()
        # อนุมัติแล้วลงทะเบียนไปราชการอัตโนมัติ (ครั้งเดียว)
        if status == "approved" and not r.record_id:
            yr = (r.start_date.year + 543) if r.start_date else _cur_year()
            sd = _dt(r.start_date.year, r.start_date.month, r.start_date.day) if r.start_date else None
            ed = _dt(r.end_date.year, r.end_date.month, r.end_date.day) if r.end_date else None
            rec = TravelRecord(person_id=r.person_id, year=yr, subject=r.subject or "",
                               place=r.place or "", start_date=sd, end_date=ed,
                               days=r.days or 0, budget=r.budget or 0, note=r.note or "")
            db.add(rec); db.flush(); r.record_id = rec.id
        res = "อนุมัติ" if status == "approved" else "ไม่อนุมัติ"
        from app.services.nav import create_notice
        create_notice(db, r.person_id, f"ผลขอไปราชการ: {res}",
                      reason=(r.subject or "") + (f" · {r.comment}" if r.comment else ""),
                      link="/me/travel",
                      level=("info" if status == "approved" else "warn"))
        db.commit()
        person = db.get(Person, r.person_id)
        if person and (person.email or "").strip():
            _notify(person.email, f"[ผลขอไปราชการ] {r.subject} - {res}",
                    f"<p>คำขอไปราชการ ({r.subject}) ได้รับการพิจารณาแล้ว: <b>{res}</b></p>"
                    f"<p>ความเห็น: {r.comment or '-'}</p>")
    return RedirectResponse("/hr/travel-requests?msg=บันทึกผลการพิจารณาแล้ว", status_code=303)


@router.post("/hr/travel-requests/{tid}/delete")
def travel_request_delete(tid: int, db: Session = Depends(get_db)):
    """ลบคำขอไปราชการ · ถ้าเคยอนุมัติแล้ว (มี record_id) ลบรายการในทะเบียนไปราชการที่ผูกกันด้วย"""
    r = db.get(TravelRequest, tid)
    if r:
        if r.record_id:
            rec = db.get(TravelRecord, r.record_id)
            if rec:
                db.delete(rec)
        db.delete(r); db.commit()
    return RedirectResponse("/hr/travel-requests?msg=ลบคำขอไปราชการแล้ว", status_code=303)


# ==================== การนิเทศภายในสถานศึกษา ====================
def _active_persons(db):
    return db.query(Person).filter(Person.active == True).order_by(Person.name).all()  # noqa: E712


def _director_name(school):
    return (getattr(school, "director_name", "") or "").strip()


@router.get("/hr/supervision", response_class=HTMLResponse)
def supervision_home(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("hr_supervision_home.html", {
        "request": request, "school": get_school(db),
        "n_visit": db.query(ClassroomVisit).count(),
        "n_sup": db.query(Supervision).count(),
    })


# ---------------- แบบการเยี่ยมชั้นเรียน ----------------
@router.get("/hr/classroom-visit", response_class=HTMLResponse)
def cv_page(request: Request, db: Session = Depends(get_db), edit: int | None = None, msg: str = "",
            year: int | None = None):
    from app.services.super_doc import VISIT_ITEMS
    rec = db.get(ClassroomVisit, edit) if edit else None
    years = sorted({y for (y,) in db.query(ClassroomVisit.year).distinct() if y}
                   | {current_academic_year()}, reverse=True)   # ปีการศึกษา (พ.ศ.) รอยต่อ พ.ค.
    q = db.query(ClassroomVisit)
    if year:
        q = q.filter(ClassroomVisit.year == year)
    return templates.TemplateResponse("hr_classroom_visit.html", {
        "request": request, "school": get_school(db), "msg": msg,
        "rows": q.order_by(ClassroomVisit.id.desc()).all(),
        "persons": _active_persons(db), "rec": rec, "items": VISIT_ITEMS,
        "years": years, "sel_year": year or 0, "default_year": current_academic_year(),
        "scores": (rec.scores.split(",") if rec and rec.scores else []),
        "be_date": be_date_input, "director": _director_name(get_school(db)),
    })


@router.post("/hr/classroom-visit/save")
async def cv_save(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    vid = _to_int(f.get("id"), 0)
    r = db.get(ClassroomVisit, vid) if vid else ClassroomVisit()
    r.person_id = _to_int(f.get("person_id"), 0) or None
    r.term = _to_int(f.get("term"), 1)
    r.year = _to_int(f.get("year"), 0) or None
    r.subject_group = (f.get("subject_group") or "").strip()
    r.topic = (f.get("topic") or "").strip()
    r.grade_level = (f.get("grade_level") or "").strip()
    r.period = (f.get("period") or "").strip()
    r.visit_time = (f.get("visit_time") or "").strip()
    r.visit_date = parse_be_date(f.get("visit_date") or "")
    r.visitor_name = (f.get("visitor_name") or "").strip()
    r.suggestion = (f.get("suggestion") or "").strip()
    r.scores = ",".join((f.get(f"score_{i}") or "").strip() for i in range(1, 11))
    if not vid:
        db.add(r)
    db.commit()
    return RedirectResponse(f"/hr/classroom-visit?edit={r.id}&msg=บันทึกแบบการเยี่ยมชั้นเรียนแล้ว",
                            status_code=303)


@router.post("/hr/classroom-visit/{vid}/delete")
def cv_delete(vid: int, db: Session = Depends(get_db)):
    r = db.get(ClassroomVisit, vid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/hr/classroom-visit", status_code=303)


@router.get("/hr/classroom-visit/{vid}/print.docx")
def cv_print(vid: int, db: Session = Depends(get_db)):
    from app.services.super_doc import render_classroom_visit
    r = db.get(ClassroomVisit, vid)
    if not r:
        return RedirectResponse("/hr/classroom-visit", status_code=303)
    return serve_generated(render_classroom_visit(get_school(db), r), _DOCX)


# ---------------- แบบบันทึกการนิเทศการจัดการเรียนรู้ ----------------
@router.get("/hr/supervision-form", response_class=HTMLResponse)
def sup_page(request: Request, db: Session = Depends(get_db), edit: int | None = None, msg: str = ""):
    from app.services.super_doc import SUP_DOMAINS
    rec = db.get(Supervision, edit) if edit else None
    return templates.TemplateResponse("hr_supervision_form.html", {
        "request": request, "school": get_school(db), "msg": msg,
        "rows": db.query(Supervision).order_by(Supervision.id.desc()).all(),
        "persons": _active_persons(db), "rec": rec, "domains": SUP_DOMAINS,
        "scores": (rec.scores.split(",") if rec and rec.scores else []),
        "be_date": be_date_input, "director": _director_name(get_school(db)),
    })


@router.post("/hr/supervision-form/save")
async def sup_save(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    vid = _to_int(f.get("id"), 0)
    r = db.get(Supervision, vid) if vid else Supervision()
    r.person_id = _to_int(f.get("person_id"), 0) or None
    r.subject_group = (f.get("subject_group") or "").strip()
    r.subject_taught = (f.get("subject_taught") or "").strip()
    r.subject_code = (f.get("subject_code") or "").strip()
    r.grade_class = (f.get("grade_class") or "").strip()
    r.round_no = _to_int(f.get("round_no"), 1)
    r.sup_date = parse_be_date(f.get("sup_date") or "")
    r.supervisor_name = (f.get("supervisor_name") or "").strip()
    r.note_found = (f.get("note_found") or "").strip()
    r.note_reflect = (f.get("note_reflect") or "").strip()
    r.note_impress = (f.get("note_impress") or "").strip()
    r.note_improve = (f.get("note_improve") or "").strip()
    r.scores = ",".join((f.get(f"score_{i}") or "").strip() for i in range(1, 26))
    if not vid:
        db.add(r)
    db.commit()
    return RedirectResponse(f"/hr/supervision-form?edit={r.id}&msg=บันทึกแบบนิเทศการจัดการเรียนรู้แล้ว",
                            status_code=303)


@router.post("/hr/supervision-form/{vid}/delete")
def sup_delete(vid: int, db: Session = Depends(get_db)):
    r = db.get(Supervision, vid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/hr/supervision-form", status_code=303)


@router.get("/hr/supervision-form/{vid}/print.docx")
def sup_print(vid: int, db: Session = Depends(get_db)):
    from app.services.super_doc import render_supervision
    r = db.get(Supervision, vid)
    if not r:
        return RedirectResponse("/hr/supervision-form", status_code=303)
    return serve_generated(render_supervision(get_school(db), r), _DOCX)
