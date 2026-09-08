# -*- coding: utf-8 -*-
"""
account.py - จัดการบัญชีผู้ใช้ของตัวเอง (โปรไฟล์ + เปลี่ยนรหัสผ่าน)
ใช้ได้ทั้งผู้ใช้โรงเรียนและ superadmin (ไม่พึ่งฐานข้อมูลโรงเรียน -> ทำงานได้แม้ยังไม่เลือกโรงเรียน)
"""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.accounts import (audit, change_password, clear_avatar, get_avatar, has_avatar,
                          mark_welcomed, set_avatar, set_display_name, sync_seen_modules,
                          totp_begin, totp_confirm, totp_disable, totp_status)
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
    from app.accounts import audit
    audit("password.change", request=request)
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
        "has_avatar": has_avatar(request.session.get("uid")),
        # ยืนยัน 2 ชั้น: เปิดให้เฉพาะบัญชีผู้ดูแลระบบก่อน (บัญชีเดียวที่เข้าถึงได้ทุกโรงเรียน)
        "can_2fa": request.session.get("role") == "superadmin",
        "tfa": totp_status(request.session.get("uid")),
        "tfa_secret": None, "tfa_codes": None,
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


# ---------------- รูปโปรไฟล์ ----------------
@router.get("/account/avatar")
def avatar_me(request: Request):
    """รูปโปรไฟล์ของคนที่ล็อกอินอยู่ (ไม่เปิดให้ดูของคนอื่น)"""
    uid = request.session.get("uid")
    data = get_avatar(uid) if uid else None
    if not data:
        return Response(status_code=404)
    # no-cache: เปลี่ยนรูปแล้วต้องเห็นทันที ไม่ติดรูปเก่าในแคช
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-cache, must-revalidate"})


@router.post("/account/avatar", response_class=HTMLResponse)
async def avatar_upload(request: Request, file: UploadFile = File(...)):
    uid = request.session.get("uid")
    if not uid:
        return RedirectResponse("/login", status_code=303)
    r = set_avatar(uid, await file.read())
    if r.get("error"):
        return templates.TemplateResponse("account_profile.html",
                                          _profile_ctx(request, error=r["error"]),
                                          status_code=400)
    request.session["pic"] = True          # แถบบนสลับไปใช้รูปทันที
    return RedirectResponse("/account/profile?saved=pic", status_code=303)


@router.post("/account/avatar/delete")
def avatar_delete(request: Request):
    uid = request.session.get("uid")
    if uid:
        clear_avatar(uid)
    request.session["pic"] = False
    return RedirectResponse("/account/profile?saved=pic", status_code=303)


# ---------------- ยืนยันตัวตน 2 ชั้น (TOTP) · สมัครใจ ----------------
def _can_2fa(request) -> bool:
    return bool(request.session.get("uid")) and request.session.get("role") == "superadmin"


@router.post("/account/2fa/start", response_class=HTMLResponse)
def tfa_start(request: Request):
    """สร้างคีย์ลับ + แสดง QR ให้สแกน (ยังไม่เปิดใช้จนกว่าจะยืนยันรหัสสำเร็จ)"""
    if not _can_2fa(request):
        return RedirectResponse("/account/profile", status_code=303)
    secret = totp_begin(request.session.get("uid"))
    if not secret:
        return RedirectResponse("/account/profile", status_code=303)
    return templates.TemplateResponse("account_profile.html",
                                      _profile_ctx(request, tfa_secret=secret))


@router.get("/account/2fa/qr.png")
def tfa_qr(request: Request):
    """QR ของคีย์ที่กำลังตั้งค่า - เสิร์ฟเฉพาะเจ้าของ session และเฉพาะตอนที่ยังไม่เปิดใช้"""
    from app.accounts import acc_session, Account
    from app.services import totp as _t
    if not _can_2fa(request):
        return Response(status_code=404)
    db = acc_session()
    try:
        a = db.get(Account, request.session.get("uid"))
        if not a or not a.totp_secret or a.totp_enabled:
            return Response(status_code=404)
        png = _t.qr_png(_t.uri(a.totp_secret, a.username))
    finally:
        db.close()
    if not png:
        return Response(status_code=404)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/account/2fa/enable", response_class=HTMLResponse)
def tfa_enable(request: Request, code: str = Form("")):
    if not _can_2fa(request):
        return RedirectResponse("/account/profile", status_code=303)
    r = totp_confirm(request.session.get("uid"), code)
    if r.get("error"):
        from app.accounts import acc_session, Account
        db = acc_session()
        try:
            a = db.get(Account, request.session.get("uid"))
            secret = a.totp_secret if a else None
        finally:
            db.close()
        return templates.TemplateResponse(
            "account_profile.html",
            _profile_ctx(request, error=r["error"], tfa_secret=secret), status_code=400)
    audit("2fa.enable", request=request)
    # โชว์รหัสสำรองครั้งเดียวตรงนี้ (เก็บใน DB เป็น sha256 ย้อนดูไม่ได้อีก)
    return templates.TemplateResponse("account_profile.html",
                                      _profile_ctx(request, tfa_codes=r["codes"]))


@router.post("/account/2fa/disable", response_class=HTMLResponse)
def tfa_disable(request: Request, password: str = Form("")):
    if not _can_2fa(request):
        return RedirectResponse("/account/profile", status_code=303)
    r = totp_disable(request.session.get("uid"), password)
    if r.get("error"):
        return templates.TemplateResponse("account_profile.html",
                                          _profile_ctx(request, error=r["error"]),
                                          status_code=400)
    audit("2fa.disable", request=request)
    return RedirectResponse("/account/profile?saved=2fa-off", status_code=303)
