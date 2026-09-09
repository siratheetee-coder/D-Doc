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
from urllib.parse import urlencode
import math

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_data_dir
from app.modules import modules_from_label
from app.accounts import TRIAL_DAYS, add_lead, register_account, get_lead, attach_lead_slip, get_secret_key
from app.seller_config import SELLER, price_for
from app.templating import templates
from app.services.slip_upload import read_slip, SlipError

router = APIRouter()

def _purchase_target(next: str, packages: str = "") -> str:
    if not isinstance(next, str):
        return ""
    if next == "checkout":
        return "/checkout?" + urlencode({"packages": packages})
    target = next if next.startswith("/") and not next.startswith("//") and not any(c in next for c in "\\\r\n") else ""
    if target == "/checkout" or target.startswith("/checkout?"):
        return target
    if re.fullmatch(r"/pay/[A-Za-z0-9_.-]+", target):
        return target
    return ""

def _registration_flow(email: str, next: str, packages: str) -> str:
    from itsdangerous import URLSafeTimedSerializer
    destination = _purchase_target(next, packages)
    if not destination:
        return ""
    return URLSafeTimedSerializer(get_secret_key(), salt="registration-flow").dumps(
        {"email": email.strip().lower(), "packages": packages, "destination": destination})

def _registration_destination(flow: str, email: str) -> str:
    from itsdangerous import URLSafeTimedSerializer, BadData
    from urllib.parse import urlencode
    try:
        data = URLSafeTimedSerializer(get_secret_key(), salt="registration-flow").loads(
            flow, max_age=7 * 24 * 60 * 60)
        if isinstance(data, dict) and data.get("email") == email.strip().lower():
            if "destination" in data:
                return _purchase_target(data["destination"]) or "/"
            return "/checkout?" + urlencode({"packages": data.get("packages", "")})
    except (BadData, TypeError, ValueError):
        pass
    return "/"


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


# ---------------- ลิงก์ชำระเงินสาธารณะ (จากอีเมลใบเสนอราคา) ----------------
def _pay_serializer():
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(str(get_secret_key()), salt="pay-link")


def make_pay_token(lead_id: int) -> str:
    """โทเคนเซ็นลายเซ็นของ lead_id สำหรับลิงก์ /pay/<token> (กันเดา/ปลอม)"""
    return _pay_serializer().dumps(int(lead_id))


def _parse_pay_token(token: str):
    from itsdangerous import BadSignature
    try:
        return int(_pay_serializer().loads(token))
    except (BadSignature, ValueError, TypeError):
        return None


@router.get("/pay/{token}", response_class=HTMLResponse)
def pay_page(token: str, request: Request):
    from app.accounts import purchase_account
    lid = _parse_pay_token(token)
    lead = get_lead(lid) if lid else None
    account = purchase_account(request.session.get("uid"))
    switch_account = bool(request.session.get("uid") and not account)
    change_password = bool(switch_account and request.session.get("must_change"))
    if change_password:
        request.session["purchase_next"] = f"/pay/{token}"
    bound = bool(lead and account and lead.get("tenant_id") == account["tenant_id"])
    conflict = bool(lead and lead.get("tenant_id") and not bound)
    return templates.TemplateResponse("pay.html", {
        "request": request, "token": token, "lead": lead,
        "seller": _seller_ctx() if bound else None,
        "account": account, "bound": bound, "conflict": conflict,
        "switch_account": switch_account, "change_password": change_password,
        "login_url": ("/logout?" if switch_account else "/login?") + urlencode({"next": f"/pay/{token}"}),
        "register_url": "/register?" + urlencode({"next": f"/pay/{token}"}),
        "amount": float(lead.get("amount") or 0) if lead else 0,
        "valid_amount": bool(lead and math.isfinite(float(lead.get("amount") or 0)) and float(lead.get("amount") or 0) > 0),
        "paid": bool(lead and lead.get("slip_file")),
        "approved": bool(lead and lead.get("status") == "ต่ออายุแล้ว"),
    })


@router.post("/pay/{token}/bind")
def pay_bind(token: str, request: Request):
    from app.accounts import bind_payment_account
    lid = _parse_pay_token(token)
    if not lid:
        raise HTTPException(404, "ไม่พบใบเสนอราคา")
    if not request.session.get("uid"):
        return RedirectResponse("/login?" + urlencode({"next": f"/pay/{token}"}), status_code=303)
    if not bind_payment_account(lid, request.session["uid"]):
        raise HTTPException(403, "ไม่สามารถผูกใบเสนอราคากับบัญชีนี้ กรุณาตรวจสอบบัญชีหรือติดต่อเจ้าหน้าที่")
    return RedirectResponse(f"/pay/{token}", status_code=303)


@router.post("/pay/{token}/slip")
async def pay_slip(token: str, request: Request, slip: UploadFile = File(None)):
    from app.accounts import purchase_account
    lid = _parse_pay_token(token)
    lead = get_lead(lid) if lid else None
    if not lead:
        return RedirectResponse("/pay/" + token, status_code=303)
    account = purchase_account(request.session.get("uid"))
    if not account or lead.get("tenant_id") != account["tenant_id"]:
        return RedirectResponse(f"/pay/{token}", status_code=303)
    if lead.get("slip_file") or lead.get("status") == "ต่ออายุแล้ว":
        return RedirectResponse(f"/pay/{token}", status_code=303)
    if not math.isfinite(float(lead.get("amount") or 0)) or float(lead.get("amount") or 0) <= 0:
        raise HTTPException(400, "กรุณาติดต่อเจ้าหน้าที่เพื่อตรวจสอบยอดใบเสนอราคา")
    if not (slip and slip.filename):
        return RedirectResponse(f"/pay/{token}?err=noslip", status_code=303)
    try:
        data, ext = await read_slip(slip)
    except SlipError as exc:
        return RedirectResponse(f"/pay/{token}?err={exc.code}", status_code=303)
    _LEADS_DIR.mkdir(parents=True, exist_ok=True)
    slip_name = f"slip_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(4)}{ext}"
    (_LEADS_DIR / slip_name).write_bytes(data)
    info = attach_lead_slip(lid, slip_name, tenant_id=account["tenant_id"])
    if not info:
        (_LEADS_DIR / slip_name).unlink(missing_ok=True)
        return RedirectResponse(f"/pay/{token}", status_code=303)
    try:
        from app.services.mailer import send_order_notice
        send_order_notice("order", school=(info or {}).get("school_name", ""),
                          contact=(info or {}).get("contact_name", ""), email=(info or {}).get("email", ""),
                          phone=(info or {}).get("phone", ""), packages=(info or {}).get("packages", ""),
                          amount=float((info or {}).get("amount") or 0), ref=lid, has_slip=True,
                          note="ลูกค้าชำระผ่านลิงก์ใบเสนอราคา")
    except Exception:
        pass
    return RedirectResponse(f"/pay/{token}?done=1", status_code=303)


@router.get("/checkout/promptpay.png")
def checkout_promptpay(amount: str = ""):
    """สร้าง QR PromptPay ตามยอดเงิน (dynamic) - สแกนแล้วยอดขึ้นตามราคาที่เลือก"""
    from fastapi.responses import Response as _Resp
    from app.services.promptpay import promptpay_png
    pid = (SELLER.get("promptpay_id") or "").strip()
    if not pid:
        return _Resp(status_code=404)
    amt = _to_float(amount, 0.0)
    if not math.isfinite(amt) or amt <= 0:
        return _Resp(status_code=400)
    png = promptpay_png(pid, amt)
    return _Resp(content=png, media_type="image/png",
                 headers={"Cache-Control": "no-store"})


# ---------------- ขอใบเสนอราคา ----------------
def _quote_price(request, selected):
    from app.accounts import purchase_account, tenant_billing
    from app.modules import parse_modules, MODULE_KEYS
    from app.seller_config import price_addon
    account = purchase_account(request.session.get("uid"))
    bill = tenant_billing(account["tenant_id"]) if account else None
    owned = parse_modules((bill or {}).get("modules"))
    days = (bill or {}).get("days_left") or 0
    addon = bool(bill and bill["plan"] == "member" and days > 0 and owned and owned != set(MODULE_KEYS))
    pf = price_addon(set(selected) - owned, days) if addon else price_for(selected)
    return pf, account, addon


@router.get("/quote", response_class=HTMLResponse)
def quote_page(request: Request, packages: str = "", amount: str = ""):
    pf, account, addon = _quote_price(request, modules_from_label(packages))
    prefill = {"packages": pf["label"] or packages, "amount": pf["total"] if pf["count"] else ""}
    return templates.TemplateResponse("quote.html", {"request": request, "prefill": prefill,
                                                     "account": account, "addon": addon})


@router.post("/quote")
def quote_submit(request: Request, school_name: str = Form(""), address: str = Form(""), tax_id: str = Form(""),
                 contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
                 mod: list[str] = Form([]), packages: str = Form(""), amount: str = Form(""),
                 qty_school: str = Form(""), note: str = Form("")):
    extra = (note or "").strip()
    if (qty_school or "").strip():
        extra = (f"จำนวนโรงเรียน: {qty_school.strip()}\n" + extra).strip()
    # ราคาคำนวณที่เซิร์ฟเวอร์เหมือนหน้าสั่งซื้อ · ถ้าไม่ได้ส่ง mod มา ลองแกะจากข้อความ packages เดิม
    pf, account, addon = _quote_price(request, set(mod or []) or modules_from_label(packages))
    if addon:
        extra = ("[ซื้อเพิ่มกลางรอบ prorate] " + extra).strip()
    if not pf["count"] or not school_name.strip() or not contact_name.strip() or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
        return templates.TemplateResponse("quote.html", {"request": request,
            "error": "กรุณาระบุแพ็กเกจ ชื่อโรงเรียน ผู้ติดต่อ และอีเมลให้ครบถ้วน",
            "account": account, "addon": addon,
            "prefill": {"school_name": school_name, "address": address, "tax_id": tax_id,
                        "contact_name": contact_name, "email": email, "phone": phone,
                        "packages": packages, "amount": pf["total"], "qty_school": qty_school, "note": note}}, status_code=400)
    lid = add_lead(kind="quote", school_name=school_name.strip(), address=address.strip(),
                   tax_id=tax_id.strip(), contact_name=contact_name.strip(), email=email.strip(),
                   phone=phone.strip(), packages=pf["label"] or packages.strip(),
                   modules=pf["modules"], amount=float(pf["total"]),
                   note=extra, tenant_id=account["tenant_id"] if account else None,
                   login_user=account["username"] if account else "")
    try:
        from app.services.mailer import send_order_notice
        send_order_notice("quote", school=school_name.strip(), contact=contact_name.strip(),
                          email=email.strip(), phone=phone.strip(),
                          packages=pf["label"] or packages.strip(),
                          amount=float(pf["total"]), ref=lid, note=extra)
    except Exception:
        pass
    return RedirectResponse(f"/sale-thanks?type=quote&ref={lid}", status_code=303)


# ---------------- สั่งซื้อ / ชำระเงิน ----------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, packages: str = "", amount: str = ""):
    # ต้องลงทะเบียน/เข้าสู่ระบบก่อน (ผูกคำสั่งซื้อกับบัญชีอีเมล)
    if not request.session.get("uid"):
        from urllib.parse import quote as _q
        return RedirectResponse(f"/register?next=checkout&packages={_q(packages)}&amount={amount}", status_code=303)
    return _render_checkout(request, packages)


def _checkout_account_required(request, packages=""):
    from app.accounts import acc_session, Account, Tenant
    target = '/checkout?' + urlencode({'packages': packages})
    db = acc_session()
    try:
        account = db.get(Account, request.session.get('uid')) if request.session.get('uid') else None
        if not account:
            request.session.clear()
            return RedirectResponse('/register?' + urlencode({'next': target}), status_code=303)
        tenant = db.get(Tenant, account.tenant_id) if account.tenant_id else None
        reason = 'unavailable'
        if account.role == 'superadmin':
            reason = 'admin'
        elif account.active and tenant and tenant.active:
            if not account.verified:
                reason = 'unverified'
            elif account.must_change_password:
                reason = 'password'
                request.session['purchase_next'] = target
                request.session['must_change'] = True
        email = account.username if reason == 'unverified' else ''
        return templates.TemplateResponse('checkout_account.html', {
            'request': request, 'reason': reason, 'email': email,
            'flow': _registration_flow(email, target, '') if email else '',
            'switch_url': '/logout?' + urlencode({'next': target}),
            'packages': packages,
        }, status_code=403)
    finally:
        db.close()


def _render_checkout(request, packages="", *, selected=None, form_data=None, error=""):
    from app.seller_config import pricing_context
    from app.accounts import tenant_billing, purchase_account
    from app.modules import MODULE_KEYS, MODULE_PRICE_KEY, parse_modules
    from app.thai_utils import thai_date
    from app.seller_config import price_addon
    account = purchase_account(request.session.get("uid"))
    if not account:
        return _checkout_account_required(request, packages)
    px = pricing_context()["prices"]
    bill = tenant_billing(account["tenant_id"])
    owned = parse_modules(bill["modules"]) if bill else set()
    days_left = (bill or {}).get("days_left") or 0
    # โหมด "ซื้อเพิ่มกลางรอบ": เป็นสมาชิกที่ยังไม่หมดอายุ + เคยซื้อบางงานแล้ว (ยังไม่ครบทุกงาน)
    addon = bool(bill and bill["plan"] == "member" and days_left > 0
                 and owned and owned != set(MODULE_KEYS))
    frac = max(0.0, min(1.0, days_left / 365.0)) if addon else 1.0
    addon_price = {k: int(round(px[MODULE_PRICE_KEY[k]] * frac)) for k in MODULE_KEYS}
    if selected is None:
        selected = modules_from_label(packages) if packages else (set() if addon else set(MODULE_KEYS))
    selected = set(selected) - owned if addon else set(selected)
    pf = price_addon(selected, days_left) if addon else price_for(selected)
    mode = "ซื้อเพิ่ม" if addon else ("ต่ออายุ" if bill and bill["plan"] == "member" else "สั่งซื้อ")
    return templates.TemplateResponse("checkout.html", {
        "request": request, "packages": packages,
        "amount": pf["total"], "seller": _seller_ctx(),
        "selected_mods": sorted(selected), "form": form_data or {}, "error": error,
        "mode": mode, "quote_url": "/quote?" + urlencode({"packages": pf["label"], "amount": pf["total"]}),
        "acct_email": account["username"],
        "acct_school": account["school_name"],
        "addon": addon, "owned_mods": sorted(owned), "days_left": days_left,
        "addon_frac": round(frac, 4), "addon_price": addon_price,
        "expiry_str": thai_date(bill["expiry_date"]) if (addon and bill.get("expiry_date")) else "",
        **pricing_context(),
    }, status_code=400 if error else 200)


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
                          slip: UploadFile = File(None), quoted_total: str = Form("")):
    # ผูกคำสั่งซื้อกับบัญชีที่ล็อกอิน (อีเมล = username, tenant) เพื่อให้ "อนุมัติ" ต่ออายุบัญชีเดิม
    if not request.session.get("uid"):
        return RedirectResponse("/register?next=checkout", status_code=303)
    from app.accounts import purchase_account
    account = purchase_account(request.session.get("uid"))
    if not account:
        from app.modules import label_for, parse_modules
        return _checkout_account_required(request, label_for(parse_modules(','.join(mod or []))))
    email, tid = account["username"], account["tenant_id"]
    form_data = {"school_name": school_name, "contact_name": contact_name, "phone": phone,
                 "addr_no": addr_no, "addr_moo": addr_moo, "addr_tambon": addr_tambon,
                 "addr_amphoe": addr_amphoe, "addr_province": addr_province, "addr_zip": addr_zip, "note": note}
    def invalid(message):
        return _render_checkout(request, selected=mod, form_data=form_data, error=message)
    address = _join_address(addr_no, addr_moo, addr_tambon, addr_amphoe, addr_province, addr_zip)
    # ราคา/รายการงาน คำนวณที่เซิร์ฟเวอร์เสมอ - ห้ามเชื่อ amount/packages ที่ส่งมาจากหน้าเว็บ
    # (ของเดิมรับ hidden field ตรง ๆ ทำให้โพสต์ "ครบทุกงาน ราคา 1 บาท" ได้)
    from app.accounts import tenant_billing
    from app.modules import parse_modules, MODULE_KEYS
    from app.seller_config import price_addon
    sel = parse_modules(",".join(mod or []))
    bill = tenant_billing(tid)
    owned = parse_modules(bill["modules"]) if bill else set()
    days_left = (bill or {}).get("days_left") or 0
    addon = bool(bill and bill["plan"] == "member" and days_left > 0
                 and owned and owned != set(MODULE_KEYS))
    if addon:
        new_mods = sel - owned                 # ซื้อเพิ่มเฉพาะงานใหม่ (งานที่มีอยู่แล้วไม่คิดซ้ำ)
        if not new_mods:
            return invalid("กรุณาเลือกงานที่ต้องการซื้อเพิ่ม")
        pf = price_addon(new_mods, days_left)   # prorate ตามวันที่เหลือ (co-term)
        note = ("[ซื้อเพิ่มกลางรอบ prorate] " + (note or "")).strip()
    else:
        pf = price_for(sel)                     # ซื้อใหม่/ต่ออายุ = ราคาเต็ม
        if not pf["count"]:
            return invalid("กรุณาเลือกแพ็กเกจก่อนชำระเงิน")
    if pf["total"] <= 0:
        return invalid("กรุณาตรวจสอบรายการและยอดชำระ")
    shown_total = _to_float(quoted_total, -1)
    if not math.isfinite(shown_total) or abs(shown_total - pf["total"]) > 0.005:
        return invalid("ยอดชำระมีการเปลี่ยนแปลง กรุณาตรวจสอบยอดใหม่ หากโอนแล้วโปรดติดต่อเจ้าหน้าที่ก่อนโอนเพิ่ม")
    required = (school_name, contact_name, phone, addr_no, addr_tambon, addr_amphoe, addr_province, addr_zip)
    if not all(v.strip() for v in required):
        return invalid("กรุณากรอกข้อมูลติดต่อและที่อยู่สำหรับออกใบเสร็จให้ครบ")
    if not (slip and slip.filename):
        return invalid("กรุณาแนบสลิปการโอน")
    try:
        data, ext = await read_slip(slip)
    except SlipError as exc:
        return invalid("ไฟล์สลิปต้องมีขนาดไม่เกิน 10 MB" if exc.code == "slipsize" else
                       "กรุณาเลือกไฟล์ PNG, JPEG, WebP หรือ PDF ที่เปิดอ่านได้ แล้วแนบสลิปอีกครั้ง")
    _LEADS_DIR.mkdir(parents=True, exist_ok=True)
    slip_name = f"slip_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(4)}{ext}"
    (_LEADS_DIR / slip_name).write_bytes(data)
    lid = add_lead(kind="order", school_name=school_name.strip() or request.session.get("name", ""),
                   contact_name=contact_name.strip(), email=email, phone=phone.strip(),
                   packages=pf["label"], modules=pf["modules"], amount=float(pf["total"]),
                   address=address,
                   slip_file=slip_name, tenant_id=tid, login_user=email, note=(note or "").strip())
    # แจ้งผู้ขายทันที (อีเมล) - ล้มเหลวก็ไม่กระทบการสั่งซื้อ
    try:
        from app.services.mailer import send_order_notice
        send_order_notice("order", school=school_name.strip() or request.session.get("name", ""),
                          contact=contact_name.strip(), email=email, phone=phone.strip(),
                          packages=pf["label"], amount=float(pf["total"]), ref=lid,
                          note=(note or "").strip(), has_slip=bool(slip_name))
    except Exception:
        pass
    return RedirectResponse(f"/sale-thanks?type=order&ref={lid}", status_code=303)


# ---------------- ลงทะเบียน (อีเมล+รหัส) -> ทดลองใช้ทันที ----------------
@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "", packages: str = "", amount: str = ""):
    next = _purchase_target(next, packages)
    if request.session.get("uid"):   # ล็อกอินอยู่แล้ว
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse("register.html", {
        "request": request, "form": {}, "error": None,
        "next": next, "packages": packages, "amount": amount})


@router.post("/register")
def register_submit(request: Request, email: str = Form(""), password: str = Form(""),
                    school_name: str = Form(""), contact_name: str = Form(""), phone: str = Form(""),
                    next: str = Form(""), packages: str = Form(""), amount: str = Form(""),
                    accept_policy: str = Form("")):
    next = _purchase_target(next, packages)
    # ต้องยอมรับนโยบายก่อนเสมอ - ตรวจฝั่งเซิร์ฟเวอร์ด้วย ไม่ใช่เชื่อป๊อปอัปฝั่งหน้าเว็บอย่างเดียว
    if not accept_policy:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "กรุณาอ่านและกดยอมรับนโยบายความเป็นส่วนตัวก่อนลงทะเบียน",
            "form": {"email": email, "school_name": school_name,
                     "contact_name": contact_name, "phone": phone},
            "next": next, "packages": packages, "amount": amount}, status_code=400)
    res = register_account(email, password, school_name, contact_name, phone, trial_days=TRIAL_DAYS)
    if res.get("tenant_id"):
        from app.accounts import record_policy_accept, client_ip
        record_policy_accept(res["tenant_id"], client_ip(request))
    if res.get('pending_verify'):
        email = email.strip().lower()
        return templates.TemplateResponse('register_sent.html', {
            'request': request, 'email': email, 'pending': True,
            'flow': _registration_flow(email, next, packages)})
    if res.get("error"):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": res["error"],
            "form": {"email": email, "school_name": school_name,
                     "contact_name": contact_name, "phone": phone},
            "next": next, "packages": packages, "amount": amount})
    # เปิด SMTP -> ต้องยืนยันอีเมลก่อน (ยังไม่ล็อกอิน)
    if res.get("needs_verify"):
        from app.services.mailer import send_verify_email
        flow = _registration_flow(res["email"], next, packages)
        send_verify_email(res["email"], _verify_link(request, res["verify_token"], flow))
        return templates.TemplateResponse("register_sent.html", {
            "request": request, "email": res["email"], "flow": flow})
    # ไม่เปิด SMTP -> ล็อกอินอัตโนมัติ เข้าใช้งานทันที
    request.session.clear()
    request.session["uid"] = res["uid"]
    request.session["username"] = res["username"]
    request.session["role"] = "user"
    request.session["tid"] = res["tenant_id"]
    request.session["name"] = res["display_name"]
    request.session["must_change"] = False
    # ถ้ามาจากปุ่มสั่งซื้อ -> พาไปหน้า checkout ต่อ
    if next:
        return RedirectResponse(next, status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/trial")
def trial_redirect():
    return RedirectResponse("/register", status_code=307)


def _verify_link(request: Request, token: str, flow: str = "") -> str:
    base = (SELLER.get("base_url") or "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    from urllib.parse import urlencode
    return base + "/verify?" + urlencode({"token": token, "flow": flow})


@router.get("/verify", response_class=HTMLResponse)
def verify_email_route(request: Request, token: str = "", flow: str = ""):
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
    return RedirectResponse(_registration_destination(flow, res["username"]), status_code=303)


@router.post("/register/resend")
def register_resend(request: Request, email: str = Form(""), flow: str = Form("")):
    from app.accounts import new_verify_token
    from app.services.mailer import send_verify_email
    token = new_verify_token(email)
    if token:
        send_verify_email(email.strip().lower(), _verify_link(request, token, flow))
    return templates.TemplateResponse("register_sent.html", {
        "request": request, "email": email.strip().lower(), "resent": True, "flow": flow})


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
