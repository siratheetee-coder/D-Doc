# -*- coding: utf-8 -*-
"""
superadmin.py — คอนโซลผู้ดูแลระบบ (ผู้ขาย)
จัดการโรงเรียน: สร้าง/ต่ออายุ/ระงับ/เพิ่มผู้ใช้/รีเซ็ตรหัสผ่าน
(เข้าถึงได้เฉพาะ role superadmin — บังคับโดย middleware ใน main.py)
"""
import re
from pathlib import Path
from datetime import date

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from datetime import datetime

from app.accounts import (acc_session, Tenant, Account, hash_password, provision_tenant,
                          list_leads, set_lead_status, get_lead, issue_sale_doc,
                          renew_lead)
from app.database import get_data_dir
from app.seller_config import SELLER
from app.templating import templates

_DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def require_superadmin(request: Request):
    """ป้องกันชั้นที่สอง (นอกเหนือจาก middleware): ทุก route ในคอนโซลต้องเป็น superadmin เท่านั้น"""
    if request.session.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลระบบเท่านั้น")


# dependencies ระดับ router -> บังคับกับทุก endpoint ใต้ /admin-console โดยอัตโนมัติ
router = APIRouter(dependencies=[Depends(require_superadmin)])


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "school"


def _parse_date(s: str):
    s = (s or "").strip()
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


@router.get("/admin-console", response_class=HTMLResponse)
def console(request: Request, msg: str | None = None):
    db = acc_session()
    try:
        tenants = db.query(Tenant).order_by(Tenant.id.desc()).all()
        rows = []
        for t in tenants:
            users = db.query(Account).filter_by(tenant_id=t.id).all()
            rows.append({"t": t, "users": users,
                         "expired": bool(t.expiry_date and t.expiry_date < date.today())})
        return templates.TemplateResponse("superadmin.html", {
            "request": request, "rows": rows, "today": date.today(),
            "msg": msg, "admin_name": request.session.get("name", "ผู้ดูแลระบบ"),
        })
    finally:
        db.close()


# ---------------- คำขอจากหน้าเว็บ (ขอใบเสนอราคา / สั่งซื้อ) ----------------
@router.get("/admin-console/leads", response_class=HTMLResponse)
def leads_page(request: Request, kind: str | None = None):
    k = kind if kind in ("quote", "order", "trial") else None
    msg = request.session.pop("lead_msg", None)   # ผลการอนุมัติ/ต่ออายุ (แสดงครั้งเดียว)
    return templates.TemplateResponse("superadmin_leads.html", {
        "request": request, "leads": list_leads(k), "kind": k, "lead_msg": msg,
        "admin_name": request.session.get("name", "ผู้ดูแลระบบ"),
    })


@router.post("/admin-console/leads/{lid}/approve")
def approve_lead(lid: int, request: Request, kind: str = Form("")):
    """(B) อนุมัติคำสั่งซื้อ -> ต่ออายุบัญชีเดิมของลูกค้า 1 ปี (อีเมลเดิม รหัสเดิม)"""
    res = renew_lead(lid)
    if res and res.get("error"):
        from urllib.parse import quote
        request.session["lead_msg"] = {"ok": False, "text": res["error"]}
    elif res:
        request.session["lead_msg"] = {"ok": True,
            "text": f"ต่ออายุบัญชี {res['username']} แล้ว ใช้งานได้ถึง {res['expiry']}"}
    q = f"?kind={kind}" if kind in ("quote", "order", "trial") else ""
    return RedirectResponse(f"/admin-console/leads{q}", status_code=303)


@router.post("/admin-console/leads/{lid}/status")
def lead_status(lid: int, status: str = Form(""), kind: str = Form("")):
    if status.strip():
        set_lead_status(lid, status.strip())
    q = f"?kind={kind}" if kind in ("quote", "order") else ""
    return RedirectResponse(f"/admin-console/leads{q}", status_code=303)


def _issue_doc(kind: str, lid: int, fmt: str = "docx"):
    """ออกใบเสนอราคา/ใบเสร็จจาก lead (Word หรือ PDF) -> คืน path (หรือ None ถ้าไม่พบ lead)"""
    from app.services import sale_doc
    lead = get_lead(lid)
    if not lead:
        return None
    be_year = datetime.now().year + 543
    info = issue_sale_doc(kind, lid, be_year)
    doc_date = lead.get("created_at") if kind == "receipt" else datetime.now()
    renderers = {
        ("quotation", "docx"): sale_doc.render_quotation, ("receipt", "docx"): sale_doc.render_receipt,
        ("quotation", "pdf"): sale_doc.render_quotation_pdf, ("receipt", "pdf"): sale_doc.render_receipt_pdf,
    }
    return renderers[(kind, fmt)](lead, SELLER, info["doc_no"], doc_date)


@router.get("/admin-console/leads/{lid}/quotation.docx")
def lead_quotation(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("quotation", lid, "docx")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, _DOCX_MT)


@router.get("/admin-console/leads/{lid}/receipt.docx")
def lead_receipt(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("receipt", lid, "docx")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, _DOCX_MT)


@router.get("/admin-console/leads/{lid}/quotation.pdf")
def lead_quotation_pdf(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("quotation", lid, "pdf")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, "application/pdf", inline=True)


@router.get("/admin-console/leads/{lid}/receipt.pdf")
def lead_receipt_pdf(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("receipt", lid, "pdf")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, "application/pdf", inline=True)


_SLIP_NAME = re.compile(r"^slip_\d{14}_[0-9a-f]{8}\.(png|jpg|jpeg|webp|pdf)$")


@router.get("/admin-console/leads/slip/{name}")
def lead_slip(name: str):
    if not _SLIP_NAME.match(name):
        raise HTTPException(status_code=404)
    path = get_data_dir() / "leads" / name
    if not path.exists():
        raise HTTPException(status_code=404)
    mt = "application/pdf" if name.endswith(".pdf") else "image/*"
    return FileResponse(str(path), media_type=mt, content_disposition_type="inline")


@router.post("/admin-console/backup-now")
def backup_now():
    """สำรองข้อมูลทันที + ทดสอบการอัปขึ้น R2 (โชว์ผลบนหน้าคอนโซล)"""
    from app.services.backup import manual_backup
    msg = manual_backup()
    from urllib.parse import quote
    return RedirectResponse(f"/admin-console?msg={quote(msg)}", status_code=303)


@router.post("/admin-console/tenant")
def create_tenant(name: str = Form(...), admin_user: str = Form(...),
                  admin_pw: str = Form(...), expiry: str = Form(""),
                  max_users: str = Form("3")):
    slug = _slugify(name)
    # กันชื่อผู้ใช้ซ้ำ
    db = acc_session()
    try:
        exists = db.query(Account).filter_by(username=admin_user.strip()).first()
        base_slug, n = slug, 1
        while db.query(Tenant).filter_by(slug=slug).first():
            n += 1; slug = f"{base_slug}-{n}"
    finally:
        db.close()
    if exists:
        return RedirectResponse("/admin-console?msg=ชื่อผู้ใช้นี้ถูกใช้แล้ว", status_code=303)
    try:
        mx = int(max_users)
    except ValueError:
        mx = 3
    provision_tenant(name, slug, admin_user, admin_pw,
                     expiry_date=_parse_date(expiry), max_users=mx)
    return RedirectResponse("/admin-console?msg=สร้างโรงเรียนเรียบร้อยแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/expiry")
def set_expiry(tid: int, expiry: str = Form("")):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            t.expiry_date = _parse_date(expiry)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=อัปเดตวันหมดอายุแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/toggle")
def toggle_active(tid: int):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            t.active = not t.active
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=เปลี่ยนสถานะแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/adduser")
def add_user(tid: int, username: str = Form(...), password: str = Form(...)):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if not t:
            return RedirectResponse("/admin-console?msg=ไม่พบโรงเรียน", status_code=303)
        n = db.query(Account).filter_by(tenant_id=tid).count()
        if n >= (t.max_users or 3):
            return RedirectResponse(f"/admin-console?msg=เกินจำนวนผู้ใช้สูงสุด ({t.max_users})", status_code=303)
        if db.query(Account).filter_by(username=username.strip()).first():
            return RedirectResponse("/admin-console?msg=ชื่อผู้ใช้นี้ถูกใช้แล้ว", status_code=303)
        db.add(Account(tenant_id=tid, username=username.strip(),
                       password_hash=hash_password(password), role="user",
                       display_name=t.name, must_change_password=True))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=เพิ่มผู้ใช้แล้ว", status_code=303)


@router.post("/admin-console/account/{aid}/reset")
def reset_password(aid: int, password: str = Form(...)):
    db = acc_session()
    try:
        a = db.get(Account, aid)
        if a:
            a.password_hash = hash_password(password)
            a.must_change_password = True   # ให้ผู้ใช้ตั้งรหัสของตัวเองหลังถูกรีเซ็ต
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=รีเซ็ตรหัสผ่านแล้ว", status_code=303)


@router.post("/admin-console/account/{aid}/delete")
def delete_user(aid: int):
    db = acc_session()
    try:
        a = db.get(Account, aid)
        if a and a.role != "superadmin":
            db.delete(a); db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=ลบผู้ใช้แล้ว", status_code=303)
