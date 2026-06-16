# -*- coding: utf-8 -*-
"""
account.py — จัดการบัญชีผู้ใช้ของตัวเอง (เปลี่ยนรหัสผ่าน)
ใช้ได้ทั้งผู้ใช้โรงเรียนและ superadmin (ไม่พึ่งฐานข้อมูลโรงเรียน -> ทำงานได้แม้ยังไม่เลือกโรงเรียน)
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import change_password
from app.templating import templates

router = APIRouter()


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
    dest = "/admin-console" if request.session.get("role") == "superadmin" else "/"
    return RedirectResponse(dest, status_code=303)
