# -*- coding: utf-8 -*-
"""
sales.py — หน้าขายสาธารณะ (ไม่ต้องล็อกอิน)
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
from app.accounts import add_lead
from app.seller_config import SELLER
from app.templating import templates

router = APIRouter()

_LEADS_DIR = get_data_dir() / "leads"


def _to_float(v, d=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return d


def _seller_ctx() -> dict:
    """ข้อมูลผู้ขาย + เช็กว่ามีไฟล์ QR จริงไหม (ไม่มี -> แสดงกล่องบอกให้วางไฟล์)"""
    qr_rel = SELLER["promptpay_qr"].lstrip("/")
    qr_path = Path(__file__).resolve().parent.parent / qr_rel
    return {**SELLER, "promptpay_qr_exists": qr_path.exists()}


# ---------------- ขอใบเสนอราคา ----------------
@router.get("/quote", response_class=HTMLResponse)
def quote_page(request: Request, packages: str = "", amount: str = ""):
    prefill = {"packages": packages, "amount": (amount or "").replace(",", "")}
    return templates.TemplateResponse("quote.html", {"request": request, "prefill": prefill})


@router.post("/quote")
def quote_submit(school_name: str = Form(""), address: str = Form(""), tax_id: str = Form(""),
                 contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
                 packages: str = Form(""), amount: str = Form(""), qty_school: str = Form(""),
                 note: str = Form("")):
    extra = (note or "").strip()
    if (qty_school or "").strip():
        extra = (f"จำนวนโรงเรียน: {qty_school.strip()}\n" + extra).strip()
    lid = add_lead(kind="quote", school_name=school_name.strip(), address=address.strip(),
                   tax_id=tax_id.strip(), contact_name=contact_name.strip(), email=email.strip(),
                   phone=phone.strip(), packages=packages.strip(), amount=_to_float(amount),
                   note=extra)
    return RedirectResponse(f"/sale-thanks?type=quote&ref={lid}", status_code=303)


# ---------------- สั่งซื้อ / ชำระเงิน ----------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, packages: str = "", amount: str = ""):
    return templates.TemplateResponse("checkout.html", {
        "request": request, "packages": packages,
        "amount": _to_float(amount, 0.0), "seller": _seller_ctx(),
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
async def checkout_submit(school_name: str = Form(""), contact_name: str = Form(""),
                          email: str = Form(""), phone: str = Form(""), packages: str = Form(""),
                          amount: str = Form(""), note: str = Form(""),
                          addr_no: str = Form(""), addr_moo: str = Form(""), addr_tambon: str = Form(""),
                          addr_amphoe: str = Form(""), addr_province: str = Form(""), addr_zip: str = Form(""),
                          slip: UploadFile = File(None)):
    slip_name = ""
    if slip and slip.filename:
        ext = (Path(slip.filename).suffix or ".png").lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
            ext = ".png"
        _LEADS_DIR.mkdir(parents=True, exist_ok=True)
        slip_name = f"slip_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(4)}{ext}"
        (_LEADS_DIR / slip_name).write_bytes(await slip.read())
    address = _join_address(addr_no, addr_moo, addr_tambon, addr_amphoe, addr_province, addr_zip)
    lid = add_lead(kind="order", school_name=school_name.strip(), contact_name=contact_name.strip(),
                   email=email.strip(), phone=phone.strip(), packages=packages.strip(),
                   amount=_to_float(amount), address=address, slip_file=slip_name,
                   note=(note or "").strip())
    return RedirectResponse(f"/sale-thanks?type=order&ref={lid}", status_code=303)


@router.get("/sale-thanks", response_class=HTMLResponse)
def sale_thanks(request: Request, type: str = "quote", ref: str = ""):
    return templates.TemplateResponse("sale_thanks.html", {
        "request": request, "kind": ("order" if type == "order" else "quote"),
        "ref": ref if re.fullmatch(r"\d+", ref or "") else "",
    })
