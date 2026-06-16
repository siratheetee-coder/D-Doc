# -*- coding: utf-8 -*-
"""
auth.py — ล็อกอิน/ออกจากระบบ (ระบบคลาวด์หลายโรงเรียน)
"""
import time

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import authenticate
from app.templating import templates

router = APIRouter()

# กันเดารหัสผ่าน: เก็บเวลา+จำนวนครั้งที่ล้มเหลวต่อ IP (ในหน่วยความจำ)
_fails: dict = {}
_MAX_FAILS = 8
_WINDOW = 300   # 5 นาที


def _too_many(ip: str) -> bool:
    n, ts = _fails.get(ip, (0, 0))
    if time.time() - ts > _WINDOW:
        return False
    return n >= _MAX_FAILS


def _record_fail(ip: str):
    n, ts = _fails.get(ip, (0, 0))
    if time.time() - ts > _WINDOW:
        n = 0
    _fails[ip] = (n + 1, time.time())


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    # ถ้าล็อกอินอยู่แล้ว ส่งไปหน้าที่เหมาะสม
    if request.session.get("uid"):
        dest = "/admin-console" if request.session.get("role") == "superadmin" else "/"
        return RedirectResponse(dest, status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
    ip = request.client.host if request.client else "?"
    if _too_many(ip):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "พยายามเข้าระบบบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่",
        }, status_code=429)
    user = authenticate(username, password)
    if not user:
        _record_fail(ip)
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
        }, status_code=401)
    # ล็อกอินสำเร็จ — เก็บข้อมูลใน session
    request.session.clear()
    request.session["uid"] = user["uid"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    request.session["tid"] = user["tenant_id"]
    request.session["name"] = user["display_name"] or user["username"]
    request.session["must_change"] = user.get("must_change", False)
    if user.get("must_change"):
        return RedirectResponse("/account/password", status_code=303)
    dest = "/admin-console" if user["role"] == "superadmin" else "/"
    return RedirectResponse(dest, status_code=303)


@router.get("/logout")
@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
