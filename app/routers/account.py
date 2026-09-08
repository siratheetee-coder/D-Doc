# -*- coding: utf-8 -*-
"""
account.py - จัดการบัญชีผู้ใช้ของตัวเอง (โปรไฟล์ + เปลี่ยนรหัสผ่าน)
ใช้ได้ทั้งผู้ใช้โรงเรียนและ superadmin (ไม่พึ่งฐานข้อมูลโรงเรียน -> ทำงานได้แม้ยังไม่เลือกโรงเรียน)
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import (change_password, mark_welcomed, set_display_name,
                          sync_seen_modules)
from app.templating import templates

router = APIRouter()


@router.post("/welcome/seen")
def welcome_seen(request: Request):
    """ปิดการ์ดต้อนรับ (ล็อกอินครั้งแรก) - ไม่เด้งอีก + ตั้ง baseline งานที่รับรู้ (กันแบนเนอร์ซื้อเพิ่มเด้งซ้ำงานเดิม)"""
    uid = request.session.get("uid")
    if uid:
        mark_welcomed(uid)
        sync_seen_modules(uid)
        request.session["welcomed"] = True
    return {"ok": True}


@router.post("/modules/seen")
def modules_seen(request: Request):
    """ไอดีหลักกดรับรู้แบนเนอร์ 'มีงานที่ซื้อเพิ่ม' -> ไม่เด้งอีกจนกว่าจะซื้อเพิ่มอีก"""
    uid = request.session.get("uid")
    if uid:
        sync_seen_modules(uid)
    return {"ok": True}


@router.get("/account/password", response_class=HTMLResponse)
def password_page(request: Request, error: str | None = None, saved: str | None = None):
    if not request.session.get("uid"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("change_password.html", {
        "request": request, "error": error, "saved": saved,
        "must_change": request.session.get("must_change", False),
        "name": request.session.get("name", ""),
        "is_super": request.session.get("role") == "superadmin",
    })


@router.post("/account/password")
def password_submit(request: Request, current: str = Form(""),
                    new1: str = Form(""), new2: str = Form("")):
    uid = request.session.get("uid")
    if not uid:
        return RedirectResponse("/login", status_code=303)
    if new1 != new2:
        return templates.TemplateResponse("change_password.html", {
            "request": request, "error": "รหัสผ่านใหม่สองช่องไม่ตรงกัน",
            "must_change": request.session.get("must_change", False),
            "name": request.session.get("name", ""),
            "is_super": request.session.get("role") == "superadmin",
        }, status_code=400)
    ok, msg = change_password(uid, current, new1)
    if not ok:
        return templates.TemplateResponse("change_password.html", {
            "request": request, "error": msg,
            "must_change": request.session.get("must_change", False),
            "name": request.session.get("name", ""),
            "is_super": request.session.get("role") == "superadmin",
        }, status_code=400)
    # สำเร็จ -> ปลดธงบังคับเปลี่ยน แล้วพาไปหน้าหลักตามบทบาท
    request.session["must_change"] = False
    from app.routers.auth import _safe_next
    purchase_next = _safe_next(request.session.pop("purchase_next", ""))
    if purchase_next:
        return RedirectResponse(purchase_next, status_code=303)
    dest = "/admin-console" if request.session.get("role") == "superadmin" else "/"
    return RedirectResponse(dest, status_code=303)


def _profile_ctx(request, **extra):
    ctx = {
        "request": request,
        "name": request.session.get("name", ""),
        "username": request.session.get("username", ""),
        "is_super": request.session.get("role") == "superadmin",
        "is_owner": request.session.get("owner", False),
        "is_teacher": bool(request.session.get("person_id")),
        "error": None, "saved": False,
    }
    ctx.update(extra)
    return ctx


@router.get("/account/profile", response_class=HTMLResponse)
def profile_page(request: Request, saved: str = ""):
    if not request.session.get("uid"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("account_profile.html",
                                      _profile_ctx(request, saved=bool(saved)))


@router.post("/account/profile", response_class=HTMLResponse)
def profile_submit(request: Request, name: str = Form("")):
    uid = request.session.get("uid")
    if not uid:
        return RedirectResponse("/login", status_code=303)
    r = set_display_name(uid, name)
    if r.get("error"):
        return templates.TemplateResponse(
            "account_profile.html",
            _profile_ctx(request, error=r["error"], name=name), status_code=400)
    request.session["name"] = r["name"]      # แถบบนเปลี่ยนทันที ไม่ต้องล็อกอินใหม่
    return RedirectResponse("/account/profile?saved=1", status_code=303)
