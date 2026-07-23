# -*- coding: utf-8 -*-
"""
sales.py - หน้าขายสาธารณะ (ไม่ต้องล็อกอิน)
  /quote     ขอใบเสนอราคา (เก็บคำขอ -> แอดมินส่งใบเสนอราคาทางอีเมล)
  /checkout  สั่งซื้อ/ชำระเงิน PromptPay + แจ้งสลิป
คำขอเก็บใน accounts.db (ตาราง lead) ผู้ขายดูได้ในคอนโซลผู้ดูแลระบบ
"""
import re
import secrets
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_data_dir
from app.modules import modules_from_label
from app.accounts import add_lead, register_account
from app.seller_config import SELLER, price_for
from app.templating import templates

router = APIRouter()

_LEADS_DIR = get_data_dir() / "leads"


def _to_float(v, d=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return d


def _seller_ctx() -> dict:
    """ข้อมูลผู้ขาย + สถานะ QR: promptpay_dynamic (สร้างตามยอด) / promptpay_qr_exists (รูปตายตัว)"""
    qr_rel = SELLER["promptpay_qr"].lstrip("/")
    qr_path = Path(__file__).resolve().parent.parent / qr_rel
    return {**SELLER,
            "promptpay_dynamic": bool((SELLER.get("promptpay_id") or "").strip()),
            "promptpay_qr_exists": qr_path.exists()}


@router.get("/checkout/promptpay.png")
def checkout_promptpay(amount: str = ""):
    """สร้าง QR PromptPay ตามยอดเงิน (dynamic) - สแกนแล้วยอดขึ้นตามราคาที่เลือก"""
    from fastapi.responses import Response as _Resp
    from app.services.promptpay import promptpay_png
    pid = (SELLER.get("promptpay_id") or "").strip()
    if not pid:
        return _Resp(status_code=404)
    amt = _to_float(amount, 0.0)
    png = promptpay_png(pid, amt if amt > 0 else None)
    return _Resp(content=png, media_type="image/png",
                 headers={"Cache-Control": "no-store"})


# ---------------- ขอใบเสนอราคา ----------------
@router.get("/quote", response_class=HTMLResponse)
def quote_page(request: Request, packages: str = "", amount: str = ""):
    prefill = {"packages": packages, "amount": (amount or "").replace(",", "")}
    return templates.TemplateResponse("quote.html", {"request": request, "prefill": prefill})


@router.post("/quote")
def quote_submit(school_name: str = Form(""), address: str = Form(""), tax_id: str = Form(""),
                 contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
                 mod: list[str] = Form([]), packages: str = Form(""), amount: str = Form(""),
                 qty_school: str = Form(""), note: str = Form("")):
    extra = (note or "").strip()
    if (qty_school or "").strip():
        extra = (f"จำนวนโรงเรียน: {qty_school.strip()}\n" + extra).strip()
    # ราคาคำนวณที่เซิร์ฟเวอร์เหมือนหน้าสั่งซื้อ · ถ้าไม่ได้ส่ง mod มา ลองแกะจากข้อความ packages เดิม
    pf = price_for(set(mod or []) or modules_from_label(packages))
    lid = add_lead(kind="quote", school_name=school_name.strip(), address=address.strip(),
                   tax_id=tax_id.strip(), contact_name=contact_name.strip(), email=email.strip(),
                   phone=phone.strip(), packages=pf["label"] or packages.strip(),
                   modules=pf["modules"], amount=float(pf["total"]),
                   note=extra)
    return RedirectResponse(f"/sale-thanks?type=quote&ref={lid}", status_code=303)


# ---------------- สั่งซื้อ / ชำระเงิน ----------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, packages: str = "", amount: str = ""):
    # ต้องลงทะเบียน/เข้าสู่ระบบก่อน (ผูกคำสั่งซื้อกับบัญชีอีเมล)
    if not request.session.get("uid"):
        from urllib.parse import quote as _q
        return RedirectResponse(f"/register?next=checkout&packages={_q(packages)}&amount={amount}", status_code=303)
    from app.seller_config import pricing_context
    return templates.TemplateResponse("checkout.html", {
        "request": request, "packages": packages,
        "amount": _to_float(amount, 0.0), "seller": _seller_ctx(),
        "acct_email": request.session.get("username", ""),
        "acct_school": request.session.get("name", ""),
        **pricing_context(),
    })


def _join_address(no, moo, tambon, amphoe, province, zipcode) -> str:
    """รวมช่องที่อยู่เป็นข้อความไทยสำหรับออกใบเสร็จ (ข้ามช่องที่เว้นว่าง)"""
    parts = []
    if (no or "").strip():
        parts.append("เลขที่ " + no.strip())
    if (moo or "").strip():
        parts.append("หมู่ " + moo.strip())
    if (tambon or "").strip():
        parts.append("ตำบล" + tambon.strip())
    if (amphoe or "").strip():
        parts.append("อำเภอ" + amphoe.strip())
    if (province or "").strip():
        parts.append("จังหวัด" + province.strip())
    if (zipcode or "").strip():
        parts.append(zipcode.strip())
    return " ".join(parts)


@router.post("/checkout")
async def checkout_submit(request: Request, school_name: str = Form(""), contact_name: str = Form(""),
                          phone: str = Form(""), mod: list[str] = Form([]),
                          packages: str = Form(""), amount: str = Form(""), note: str = Form(""),
                          addr_no: str = Form(""), addr_moo: str = Form(""), addr_tambon: str = Form(""),
                          addr_amphoe: str = Form(""), addr_province: str = Form(""), addr_zip: str = Form(""),
                          slip: UploadFile = File(None)):
    # ผูกคำสั่งซื้อกับบัญชีที่ล็อกอิน (อีเมล = username, tenant) เพื่อให้ "อนุมัติ" ต่ออายุบัญชีเดิม
    if not request.session.get("uid"):
        return RedirectResponse("/register?next=checkout", status_code=303)
    email = request.session.get("username", "")
    tid = request.session.get("tid")
    slip_name = ""
    if slip and slip.filename:
        ext = (Path(slip.filename).suffix or ".png").lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
            ext = ".png"
        _LEADS_DIR.mkdir(parents=True, exist_ok=True)
        slip_name = f"slip_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(4)}{ext}"
        (_LEADS_DIR / slip_name).write_bytes(await slip.read())
    address = _join_address(addr_no, addr_moo, addr_tambon, addr_amphoe, addr_province, addr_zip)
    # ราคา/รายการงาน คำนวณที่เซิร์ฟเวอร์เสมอ - ห้ามเชื่อ amount/packages ที่ส่งมาจากหน้าเว็บ
    # (ของเดิมรับ hidden field ตรง ๆ ทำให้โพสต์ "ครบทุกงาน ราคา 1 บาท" ได้)
    pf = price_for(set(mod or []))
    if not pf["count"]:                        # ไม่ได้เลือกงาน -> ถอยกลับไปหน้า checkout
        return RedirectResponse("/checkout?err=nomod", status_code=303)
    lid = add_lead(kind="order", school_name=school_name.strip() or request.session.get("name", ""),
                   contact_name=contact_name.strip(), email=email, phone=phone.strip(),
                   packages=pf["label"], modules=pf["modules"], amount=float(pf["total"]),
                   address=address,
                   slip_file=slip_name, tenant_id=tid, login_user=email, note=(note or "").strip())
    return RedirectResponse(f"/sale-thanks?type=order&ref={lid}", status_code=303)


# ---------------- ลงทะเบียน (อีเมล+รหัส) -> ทดลองใช้ทันที ----------------
@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "", packages: str = "", amount: str = ""):
    if request.session.get("uid"):   # ล็อกอินอยู่แล้ว
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("register.html", {
        "request": request, "form": {}, "error": None,
        "next": next, "packages": packages, "amount": amount})


@router.post("/register")
def register_submit(request: Request, email: str = Form(""), password: str = Form(""),
                    school_name: str = Form(""), contact_name: str = Form(""), phone: str = Form(""),
                    next: str = Form(""), packages: str = Form(""), amount: str = Form("")):
    res = register_account(email, password, school_name, contact_name, phone, trial_days=14)
    if res.get("error"):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": res["error"],
            "form": {"email": email, "school_name": school_name,
                     "contact_name": contact_name, "phone": phone},
            "next": next, "packages": packages, "amount": amount})
    # เปิด SMTP -> ต้องยืนยันอีเมลก่อน (ยังไม่ล็อกอิน)
    if res.get("needs_verify"):
        from app.services.mailer import send_verify_email
        send_verify_email(res["email"], _verify_link(request, res["verify_token"]))
        return templates.TemplateResponse("register_sent.html", {
            "request": request, "email": res["email"]})
    # ไม่เปิด SMTP -> ล็อกอินอัตโนมัติ เข้าใช้งานทันที
    request.session.clear()
    request.session["uid"] = res["uid"]
    request.session["username"] = res["username"]
    request.session["role"] = "user"
    request.session["tid"] = res["tenant_id"]
    request.session["name"] = res["display_name"]
    request.session["must_change"] = False
    # ถ้ามาจากปุ่มสั่งซื้อ -> พาไปหน้า checkout ต่อ
    if next == "checkout":
        from urllib.parse import quote as _q
        return RedirectResponse(f"/checkout?packages={_q(packages)}&amount={amount}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/trial")
def trial_redirect():
    return RedirectResponse("/register", status_code=307)


def _verify_link(request: Request, token: str) -> str:
    base = (SELLER.get("base_url") or "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/verify?token={token}"


@router.get("/verify", response_class=HTMLResponse)
def verify_email_route(request: Request, token: str = ""):
    from app.accounts import verify_email
    res = verify_email(token)
    if not res:
        return templates.TemplateResponse("register_sent.html", {
            "request": request, "email": "", "bad": True})
    # ยืนยันแล้ว -> ล็อกอินอัตโนมัติ เข้าใช้งานทันที
    request.session.clear()
    request.session["uid"] = res["uid"]
    request.session["username"] = res["username"]
    request.session["role"] = res.get("role", "user")
    request.session["tid"] = res["tenant_id"]
    request.session["name"] = res["display_name"]
    request.session["must_change"] = False
    return RedirectResponse("/", status_code=303)


@router.post("/register/resend")
def register_resend(request: Request, email: str = Form("")):
    from app.accounts import new_verify_token
    from app.services.mailer import send_verify_email
    token = new_verify_token(email)
    if token:
        send_verify_email(email.strip().lower(), _verify_link(request, token))
    return templates.TemplateResponse("register_sent.html", {
        "request": request, "email": email.strip().lower(), "resent": True})


@router.get("/trial-limit", response_class=HTMLResponse)
def trial_limit_page(request: Request):
    from app.accounts import tenant_status
    st = tenant_status(request.session.get("tid"))
    return templates.TemplateResponse("trial_limit.html", {"request": request, "st": st})


@router.get("/sale-thanks", response_class=HTMLResponse)
def sale_thanks(request: Request, type: str = "quote", ref: str = ""):
    return templates.TemplateResponse("sale_thanks.html", {
        "request": request, "kind": ("order" if type == "order" else "quote"),
        "ref": ref if re.fullmatch(r"\d+", ref or "") else "",
    })
