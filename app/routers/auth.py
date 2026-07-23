# -*- coding: utf-8 -*-
"""
auth.py - ล็อกอิน/ออกจากระบบ (ระบบคลาวด์หลายโรงเรียน)
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


@router.get("/landing", response_class=HTMLResponse)
def landing_page(request: Request):
    """หน้า landing สาธารณะ (สำหรับแนะนำระบบ/ขาย) - ยังไม่ผูกโดเมนจริง ดูผ่าน /landing"""
    from app.seller_config import pricing_context
    return templates.TemplateResponse("landing.html", {"request": request, **pricing_context()})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None, ok: str | None = None):
    # ถ้าล็อกอินอยู่แล้ว ส่งไปหน้าที่เหมาะสม
    if request.session.get("uid"):
        dest = "/admin-console" if request.session.get("role") == "superadmin" else "/"
        return RedirectResponse(dest, status_code=303)
    msg = "ตั้งรหัสผ่านใหม่เรียบร้อยแล้ว เข้าสู่ระบบด้วยรหัสใหม่ได้เลย" if ok == "reset" else None
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "ok_msg": msg})


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
    if not user.get("verified", True):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "อีเมลนี้ยังไม่ได้ยืนยัน โปรดตรวจสอบลิงก์ยืนยันในอีเมลของท่านก่อน (ถ้าไม่พบ ลองดูในกล่อง Spam)",
            "unverified_email": user["username"],
        }, status_code=403)
    # ล็อกอินสำเร็จ - เก็บข้อมูลใน session
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


# ---------------- ลืมรหัสผ่าน / รีเซ็ต (ยืนยันผ่านลิงก์อีเมล) ----------------
def _abs_link(request: Request, path: str) -> str:
    from app.seller_config import SELLER
    base = (SELLER.get("base_url") or "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    return base + path


@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    return templates.TemplateResponse("forgot.html", {"request": request, "sent": False})


@router.post("/forgot", response_class=HTMLResponse)
def forgot_submit(request: Request, email: str = Form("")):
    from app.accounts import create_reset_token
    from app.services.mailer import send_reset_email, smtp_configured
    token = create_reset_token(email)
    if token:
        send_reset_email(email.strip().lower(), _abs_link(request, f"/reset?token={token}"))
    # แสดงข้อความเดียวกันเสมอ (ไม่บอกว่าอีเมลมีอยู่จริงไหม เพื่อกันการสแกนอีเมล)
    return templates.TemplateResponse("forgot.html", {
        "request": request, "sent": True, "email": email.strip().lower(),
        "no_smtp": not smtp_configured()})


@router.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, token: str = ""):
    from app.accounts import account_by_reset_token
    valid = account_by_reset_token(token)
    return templates.TemplateResponse("reset.html", {
        "request": request, "token": token, "valid": bool(valid), "error": None})


@router.post("/reset", response_class=HTMLResponse)
def reset_submit(request: Request, token: str = Form(""),
                 password: str = Form(""), password2: str = Form("")):
    if password != password2:
        return templates.TemplateResponse("reset.html", {
            "request": request, "token": token, "valid": True,
            "error": "รหัสผ่านทั้งสองช่องไม่ตรงกัน"})
    from app.accounts import reset_password_with_token
    res = reset_password_with_token(token, password)
    if res.get("error"):
        # โทเคนหมดอายุ -> valid=False (โชว์ให้ขอใหม่), รหัสสั้น -> valid=True (แก้ในฟอร์มเดิม)
        expired = "หมดอายุ" in res["error"]
        return templates.TemplateResponse("reset.html", {
            "request": request, "token": token, "valid": not expired, "error": res["error"]})
    return RedirectResponse("/login?ok=reset", status_code=303)
