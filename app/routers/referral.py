# -*- coding: utf-8 -*-
"""
referral.py - หน้า "แนะนำเพื่อน" (ไอดีหลัก) + ลิงก์สาธารณะ /r/<รหัส>
กติกาและการให้วันใช้ฟรีอยู่ที่ app/services/referral.py
"""
import io

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.services import referral as rf
from app.templating import templates

router = APIRouter()


def _base(request: Request) -> str:
    from app.seller_config import SELLER
    return (SELLER.get("base_url") or "").strip().rstrip("/") or str(request.base_url).rstrip("/")


@router.get("/r/{code}")
def invite_link(code: str):
    """ลิงก์ที่เพื่อนส่งมา: จำรหัสไว้ 60 วัน แล้วพาไปหน้าแนะนำระบบ (สมัครเมื่อไหร่ก็ผูกให้)"""
    if not rf.referrer_by_code(code):
        return RedirectResponse("/landing", status_code=303)
    resp = RedirectResponse("/landing", status_code=303)
    resp.set_cookie(rf.COOKIE, rf.clean_code(code), max_age=rf.COOKIE_AGE, samesite="lax", httponly=True)
    return resp


def _owner_only(request: Request):
    if not request.session.get("owner"):
        return RedirectResponse("/", status_code=303)
    return None


@router.get("/referral", response_class=HTMLResponse)
def referral_page(request: Request):
    deny = _owner_only(request)
    if deny:
        return deny
    tid = request.session.get("tid")
    sandbox = bool(request.session.get("sandbox"))
    code = "" if sandbox else rf.code_for(tid)
    from app.accounts import tenant_status
    st = tenant_status(tid) or {}
    return templates.TemplateResponse("referral.html", {
        "request": request, "sandbox": sandbox, "code": code,
        "link": f"{_base(request)}/r/{code}" if code else "",
        "days": rf.bonus_days(), "s": rf.status(tid) if not sandbox else None,
        "is_member": (st.get("plan") == "member"),
    })


@router.get("/referral/qr.png")
def referral_qr(request: Request):
    """QR ของลิงก์แนะนำ (พิมพ์ติดบอร์ด/ใส่สไลด์อบรม)"""
    deny = _owner_only(request)
    if deny or request.session.get("sandbox"):
        return Response(status_code=404)
    import qrcode
    img = qrcode.make(f"{_base(request)}/r/{rf.code_for(request.session.get('tid'))}", border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Content-Disposition": 'inline; filename="referral-qr.png"'})
