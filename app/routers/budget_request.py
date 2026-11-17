# -*- coding: utf-8 -*-
"""คำขอใช้งบประมาณ (ช่วงที่ 1): แอดมินสร้าง/แก้ไข ออกบันทึก Word ครูผู้รับผิดชอบดูอย่างเดียว

/budget-requests/...    แอดมิน (สิทธิ์งานการเงินหรือพัสดุ กำหนดใน services/access.py)
/me/budget-requests/... ครูผู้รับผิดชอบ เห็นเฉพาะคำขอที่ผูกกับตัวเอง
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BudgetRequest, BudgetRequestLine, Person, Project
from app.services import budget_request as svc
from app.services.budget_memo import COST_TYPES
from app.services.doc_number import commit_doc_no, remove_issued, suggest_doc_no
from app.services.project_activity import activity_maps, valid_activity
from app.templating import templates
from app.thai_utils import current_fiscal_year, parse_be_date

router = APIRouter()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _form_ctx(db, req, fy):
    return {"r": req, "fy": fy, "cost_types": COST_TYPES, "methods": svc.METHODS,
            "projects": db.query(Project).order_by(Project.plan_year.desc(), Project.name).all(),
            "people": db.query(Person).order_by(Person.name).all(), "pj_acts": activity_maps(db),
            "sug_no": suggest_doc_no(db, "memo", fy)}


@router.get("/budget-requests")
def br_list(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    rows = (db.query(BudgetRequest).filter(BudgetRequest.fiscal_year == fy)
            .order_by(BudgetRequest.id.desc()).all())
    return templates.TemplateResponse("budget_request_list.html", {
        "request": request, "rows": rows, "fy": fy, "total": svc.total})


@router.get("/budget-requests/new")
def br_new(request: Request, db: Session = Depends(get_db), project: int | None = None,
           activity: int | None = None):
    fy = current_fiscal_year()
    req = BudgetRequest(fiscal_year=fy, project_id=project, activity_id=valid_activity(db, activity, project))
    proj = db.get(Project, project) if project else None
    if proj:
        req.owner = proj.responsible or ""
    ctx = _form_ctx(db, req, fy)
    ctx.update(request=request, is_new=True)
    return templates.TemplateResponse("budget_request_form.html", ctx)


def _save(db, req, form):
    lines = svc.clean_lines(form)
    if not lines:
        raise ValueError("กรุณาใส่รายการค่าใช้จ่ายอย่างน้อย 1 รายการ")
    fy = _int(form.get("fiscal_year"), req.fiscal_year or current_fiscal_year())
    no = (form.get("request_no") or "").strip() or suggest_doc_no(db, "memo", fy)
    req.fiscal_year, req.request_no = fy, no
    req.date = parse_be_date(form.get("date") or "")
    req.project_id = _int(form.get("project_id")) or None
    req.activity_id = valid_activity(db, form.get("activity_id"), req.project_id)
    req.owner_person_id = _int(form.get("owner_person_id")) or None
    owner = (form.get("owner") or "").strip()
    if not owner and req.owner_person_id:
        p = db.get(Person, req.owner_person_id)
        owner = p.name if p else ""
    req.owner = owner[:200]
    req.department = (form.get("department") or "").strip()[:200]
    req.activity_date = parse_be_date(form.get("activity_date") or "")
    req.purpose = (form.get("purpose") or "").strip()[:1000]
    req.inspectors = (form.get("inspectors") or "").strip()[:2000]
    req.status = "ส่งแล้ว" if form.get("status") == "ส่งแล้ว" else "ร่าง"
    keep = {ln.seq: ln for ln in req.lines}
    req.lines.clear()
    db.flush()
    for i, d in enumerate(lines):
        old = keep.get(i)   # ช่วงที่ 2 ผูกเอกสารปลายทางรายแถว: เก็บลิงก์เดิมไว้ตามลำดับแถว
        req.lines.append(BudgetRequestLine(seq=i, procurement_id=old.procurement_id if old else None,
                                           loan_id=old.loan_id if old else None,
                                           disburse_id=old.disburse_id if old else None, **d))
    db.flush()
    remove_issued(db, "budget_request", req.id, "memo")
    proj = db.get(Project, req.project_id) if req.project_id else None
    subj = "ขออนุมัติใช้งบประมาณ " + ((proj.name if proj else "") or req.purpose or "")
    commit_doc_no(db, "memo", fy, no, source="budget_request", ref_id=req.id, date=req.date,
                  subject=subj.strip())


@router.post("/budget-requests/new")
async def br_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    req = BudgetRequest(fiscal_year=current_fiscal_year())
    db.add(req)
    try:
        _save(db, req, form)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    db.commit()
    return RedirectResponse(f"/budget-requests/{req.id}?saved=1", 303)


def _get(db, rid):
    req = db.get(BudgetRequest, rid)
    if not req:
        raise HTTPException(404, "ไม่พบคำขอใช้งบประมาณ")
    return req


def _detail_ctx(request, db, req, readonly):
    groups = svc.groups(db, req)
    if not readonly:
        for g in groups:
            g["candidates"] = svc.candidates(db, req, g["kind"]) if g["pending"] else []
    return {"request": request, "r": req, "readonly": readonly, "groups": groups,
            "total": svc.total(req), "nums": svc.budget_numbers(db, req), "steps": svc.STEPS,
            "step": svc.step_of(req, db),
            "doc_href": f"/me/budget-requests/{req.id}/doc.docx" if readonly else f"/budget-requests/{req.id}/doc.docx"}


@router.get("/budget-requests/{rid}")
def br_detail(rid: int, request: Request, db: Session = Depends(get_db)):
    req = _get(db, rid)
    return templates.TemplateResponse("budget_request_detail.html", _detail_ctx(request, db, req, False))


@router.get("/budget-requests/{rid}/edit")
def br_edit(rid: int, request: Request, db: Session = Depends(get_db)):
    req = _get(db, rid)
    ctx = _form_ctx(db, req, req.fiscal_year)
    ctx.update(request=request, is_new=False)
    return templates.TemplateResponse("budget_request_form.html", ctx)


@router.post("/budget-requests/{rid}/edit")
async def br_update(rid: int, request: Request, db: Session = Depends(get_db)):
    req = _get(db, rid)
    form = await request.form()
    try:
        _save(db, req, form)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    db.commit()
    return RedirectResponse(f"/budget-requests/{rid}?saved=1", 303)


@router.post("/budget-requests/{rid}/delete")
def br_delete(rid: int, db: Session = Depends(get_db)):
    req = _get(db, rid)
    fy = req.fiscal_year
    remove_issued(db, "budget_request", req.id, "memo")
    db.delete(req)
    db.commit()
    return RedirectResponse(f"/budget-requests?year={fy}", 303)


# ---------------- ช่วงที่ 2: สร้าง/ผูกเอกสารปลายทาง ----------------
def _method(m):
    if m not in svc.METHODS:
        raise HTTPException(400, "วิธีเบิกไม่ถูกต้อง")
    return m


@router.get("/budget-requests/{rid}/go")
def br_go(rid: int, m: str, db: Session = Depends(get_db)):
    """ปุ่มสร้างเอกสารปลายทาง: เปิดฟอร์มเดิมของงานนั้นพร้อมเติมข้อมูลจากคำขอ"""
    req = _get(db, rid)
    m = _method(m)
    if not svc.pending_lines(req, m, db):
        return RedirectResponse(f"/budget-requests/{rid}", 303)
    kind = svc.TARGET[m][1]
    q = f"br={rid}&br_m={quote(m)}"
    url = {"proc": f"/procurement/new?{q}", "loan": f"/finance/loans?year={req.fiscal_year}&{q}#new",
           "disburse": f"/finance/disburse?year={req.fiscal_year}&{q}"}[kind]
    return RedirectResponse(url, 303)


@router.post("/budget-requests/{rid}/link")
def br_link(rid: int, m: str = Form(...), target_id: int = Form(0), db: Session = Depends(get_db)):
    req = _get(db, rid)
    try:
        svc.link(db, req, _method(m), target_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return RedirectResponse(f"/budget-requests/{rid}?linked=1", 303)


@router.post("/budget-requests/{rid}/unlink")
def br_unlink(rid: int, m: str = Form(...), target_id: int = Form(0), db: Session = Depends(get_db)):
    req = _get(db, rid)
    svc.unlink(db, req, _method(m), target_id)
    db.commit()
    return RedirectResponse(f"/budget-requests/{rid}", 303)


def link_from_form(db, form, target_id):
    """เรียกจากฟอร์มปลายทางหลังสร้างเอกสาร (hidden from_br/from_br_m) คืน id คำขอ หรือ None"""
    rid = _int(form.get("from_br"))
    m = form.get("from_br_m") or ""
    req = db.get(BudgetRequest, rid) if rid else None
    if not req or m not in svc.METHODS:
        return None
    svc.link(db, req, m, target_id)
    return req.id


def br_source(db, br, br_m):
    """คำขอ+วิธีเบิกจาก query ของฟอร์มปลายทาง -> (req, method, prefill) หรือ None"""
    req = db.get(BudgetRequest, _int(br)) if br else None
    if not req or br_m not in svc.METHODS or not svc.pending_lines(req, br_m, db):
        return None
    return req, br_m, svc.prefill(req, br_m, db)


def _docx(db, req):
    from app.routers.pages import get_school, serve_generated
    return serve_generated(svc.render_docx(db, req, get_school(db)), DOCX)


@router.get("/budget-requests/{rid}/doc.docx")
def br_docx(rid: int, db: Session = Depends(get_db)):
    return _docx(db, _get(db, rid))


# ---------------- ครูผู้รับผิดชอบ: ดูอย่างเดียว ----------------
def _mine(request, db, rid):
    req = _get(db, rid)
    pid = request.session.get("person_id")
    if not pid or req.owner_person_id != pid:
        raise HTTPException(403, "คำขอนี้ไม่ได้อยู่ในความรับผิดชอบของท่าน")
    return req


@router.get("/me/budget-requests/{rid}")
def me_detail(rid: int, request: Request, db: Session = Depends(get_db)):
    req = _mine(request, db, rid)
    return templates.TemplateResponse("budget_request_detail.html", _detail_ctx(request, db, req, True))


@router.get("/me/budget-requests/{rid}/doc.docx")
def me_docx(rid: int, request: Request, db: Session = Depends(get_db)):
    return _docx(db, _mine(request, db, rid))
