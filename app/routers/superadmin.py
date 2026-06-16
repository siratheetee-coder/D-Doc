# -*- coding: utf-8 -*-
"""
superadmin.py — คอนโซลผู้ดูแลระบบ (ผู้ขาย)
จัดการโรงเรียน: สร้าง/ต่ออายุ/ระงับ/เพิ่มผู้ใช้/รีเซ็ตรหัสผ่าน
(เข้าถึงได้เฉพาะ role superadmin — บังคับโดย middleware ใน main.py)
"""
import re
from datetime import date

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import acc_session, Tenant, Account, hash_password, provision_tenant
from app.templating import templates

router = APIRouter()


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
