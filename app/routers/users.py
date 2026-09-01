# -*- coding: utf-8 -*-
"""
users.py - จัดการผู้ใช้ในโรงเรียน (เฉพาะ "ไอดีหลัก" ของโรงเรียน)
เพิ่มไอดีย่อย + กำหนดสิทธิ์งาน + รีเซ็ตรหัส + ปิด/เปิด + ลบ
สิทธิ์งานบังคับจริงที่ middleware (app/main.py) หน้านี้แค่ตั้งค่า
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import (
    list_tenant_users, add_tenant_user, set_user_modules, reset_user_password,
    toggle_user_active, toggle_user_director, delete_tenant_user, tenant_max_users,
    mark_welcomed, sync_seen_modules,
)
from app.templating import templates

router = APIRouter()


def _is_owner(request: Request) -> bool:
    """เฉพาะไอดีหลักของโรงเรียน (ไม่ใช่ superadmin ผู้ขาย)"""
    return bool(request.session.get("uid") and request.session.get("owner")
                and request.session.get("role") != "superadmin")


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, msg: str = "", err: str = ""):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    # เปิดหน้าจัดการผู้ใช้ = ผ่านการต้อนรับแล้ว (ไม่ต้องเด้งการ์ดต้อนรับอีก)
    uid = request.session.get("uid")
    if uid and not request.session.get("welcomed"):
        mark_welcomed(uid); sync_seen_modules(uid); request.session["welcomed"] = True
    tid = request.session.get("tid")
    return templates.TemplateResponse("users.html", {
        "request": request, "users": list_tenant_users(tid),
        "max_users": tenant_max_users(tid), "msg": msg, "err": err,
    })


def _back(msg: str = "", err: str = ""):
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse("/users" + ("?" + q if q else ""), status_code=303)


@router.post("/users/add")
def users_add(request: Request, username: str = Form(""), password: str = Form(""),
              display_name: str = Form(""), modules: list[str] = Form(default=[])):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = add_tenant_user(request.session.get("tid"), username, password,
                        ",".join(modules), display_name)
    return _back(err=r["error"]) if r.get("error") else _back(msg="เพิ่มผู้ใช้แล้ว")


@router.post("/users/{uid}/modules")
def users_modules(request: Request, uid: int, modules: list[str] = Form(default=[])):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = set_user_modules(request.session.get("tid"), uid, ",".join(modules))
    return _back(err=r["error"]) if r.get("error") else _back(msg="บันทึกสิทธิ์งานแล้ว")


@router.post("/users/{uid}/reset")
def users_reset(request: Request, uid: int, new_password: str = Form("")):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = reset_user_password(request.session.get("tid"), uid, new_password)
    return _back(err=r["error"]) if r.get("error") else _back(msg="ตั้งรหัสผ่านใหม่แล้ว")


@router.post("/users/{uid}/toggle")
def users_toggle(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = toggle_user_active(request.session.get("tid"), uid)
    if r.get("error"):
        return _back(err=r["error"])
    return _back(msg="เปิดใช้งานผู้ใช้แล้ว" if r.get("active") else "ปิดใช้งานผู้ใช้แล้ว")


@router.post("/users/{uid}/director")
def users_director(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = toggle_user_director(request.session.get("tid"), uid)
    if r.get("error"):
        return _back(err=r["error"])
    return _back(msg="ตั้งเป็น ผอ./รองผอ. แล้ว" if r.get("is_director") else "ยกเลิกสิทธิ์ ผอ. แล้ว")


@router.post("/users/{uid}/delete")
def users_delete(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = delete_tenant_user(request.session.get("tid"), uid)
    return _back(err=r["error"]) if r.get("error") else _back(msg="ลบผู้ใช้แล้ว")
