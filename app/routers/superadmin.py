# -*- coding: utf-8 -*-
"""
superadmin.py - คอนโซลผู้ดูแลระบบ (ผู้ขาย)
จัดการโรงเรียน: สร้าง/ต่ออายุ/ระงับ/เพิ่มผู้ใช้/รีเซ็ตรหัสผ่าน
(เข้าถึงได้เฉพาะ role superadmin - บังคับโดย middleware ใน main.py)
"""
import re
from pathlib import Path
from datetime import date

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from datetime import datetime

from app.accounts import (acc_session, Tenant, Account, hash_password, provision_tenant,
                          list_leads, set_lead_status, get_lead, issue_sale_doc,
                          renew_lead)
from app.database import get_data_dir
from app.seller_config import SELLER
from app.templating import templates

_DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def require_superadmin(request: Request):
    """ป้องกันชั้นที่สอง (นอกเหนือจาก middleware): ทุก route ในคอนโซลต้องเป็น superadmin เท่านั้น"""
    if request.session.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลระบบเท่านั้น")


# dependencies ระดับ router -> บังคับกับทุก endpoint ใต้ /admin-console โดยอัตโนมัติ
router = APIRouter(dependencies=[Depends(require_superadmin)])


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "school"


def _parse_date(s: str):
    s = (s or "").strip()
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


@router.get("/admin-console", response_class=HTMLResponse)
def console(request: Request, msg: str | None = None):
    db = acc_session()
    try:
        today = date.today()
        tenants = db.query(Tenant).order_by(Tenant.id.desc()).all()
        rows = []
        summ = {"total": 0, "active": 0, "trial": 0, "member": 0, "expired": 0, "expiring": 0}
        for t in tenants:
            users = db.query(Account).filter_by(tenant_id=t.id).all()
            expired = bool(t.expiry_date and t.expiry_date < today)
            plan = t.plan or "member"
            days_left = (t.expiry_date - today).days if t.expiry_date else None
            docs_limit = t.docs_limit or 0
            docs_used = t.docs_used or 0
            rows.append({
                "t": t, "users": users, "expired": expired, "plan": plan,
                "days_left": days_left, "docs_used": docs_used, "docs_limit": docs_limit,
                "docs_left": max(0, docs_limit - docs_used),
                "unverified": sum(1 for u in users if not getattr(u, "verified", True)),
            })
            summ["total"] += 1
            if t.active and not expired:
                summ["active"] += 1
            if plan == "trial":
                summ["trial"] += 1
            else:
                summ["member"] += 1
            if expired:
                summ["expired"] += 1
            elif days_left is not None and 0 <= days_left <= 30:
                summ["expiring"] += 1
        return templates.TemplateResponse("superadmin.html", {
            "request": request, "rows": rows, "today": today, "summ": summ,
            "msg": msg, "admin_name": request.session.get("name", "ผู้ดูแลระบบ"),
        })
    finally:
        db.close()


# ---------------- คำขอจากหน้าเว็บ (ขอใบเสนอราคา / สั่งซื้อ) ----------------
@router.get("/admin-console/leads", response_class=HTMLResponse)
def leads_page(request: Request, kind: str | None = None):
    k = kind if kind in ("quote", "order", "trial", "support", "review") else None
    msg = request.session.pop("lead_msg", None)   # ผลการอนุมัติ/ต่ออายุ (แสดงครั้งเดียว)
    return templates.TemplateResponse("superadmin_leads.html", {
        "request": request, "leads": list_leads(k), "kind": k, "lead_msg": msg,
        "admin_name": request.session.get("name", "ผู้ดูแลระบบ"),
    })


@router.post("/admin-console/leads/{lid}/approve")
def approve_lead(lid: int, request: Request, kind: str = Form("")):
    """(B) อนุมัติคำสั่งซื้อ -> ต่ออายุบัญชีเดิมของลูกค้า 1 ปี (อีเมลเดิม รหัสเดิม)"""
    res = renew_lead(lid)
    if res and res.get("error"):
        from urllib.parse import quote
        request.session["lead_msg"] = {"ok": False, "text": res["error"]}
    elif res:
        request.session["lead_msg"] = {"ok": True,
            "text": f"ต่ออายุบัญชี {res['username']} แล้ว ใช้งานได้ถึง {res['expiry']}"}
    q = f"?kind={kind}" if kind in ("quote", "order", "trial", "support", "review") else ""
    return RedirectResponse(f"/admin-console/leads{q}", status_code=303)


@router.post("/admin-console/leads/{lid}/status")
def lead_status(lid: int, status: str = Form(""), kind: str = Form("")):
    if status.strip():
        set_lead_status(lid, status.strip())
    q = f"?kind={kind}" if kind in ("quote", "order") else ""
    return RedirectResponse(f"/admin-console/leads{q}", status_code=303)


def _issue_doc(kind: str, lid: int, fmt: str = "docx"):
    """ออกใบเสนอราคา/ใบเสร็จจาก lead (Word หรือ PDF) -> คืน path (หรือ None ถ้าไม่พบ lead)"""
    from app.services import sale_doc
    lead = get_lead(lid)
    if not lead:
        return None
    be_year = datetime.now().year + 543
    info = issue_sale_doc(kind, lid, be_year)
    doc_date = lead.get("created_at") if kind == "receipt" else datetime.now()
    renderers = {
        ("quotation", "docx"): sale_doc.render_quotation, ("receipt", "docx"): sale_doc.render_receipt,
        ("quotation", "pdf"): sale_doc.render_quotation_pdf, ("receipt", "pdf"): sale_doc.render_receipt_pdf,
    }
    return renderers[(kind, fmt)](lead, SELLER, info["doc_no"], doc_date)


@router.get("/admin-console/leads/{lid}/quotation.docx")
def lead_quotation(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("quotation", lid, "docx")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, _DOCX_MT)


@router.get("/admin-console/leads/{lid}/receipt.docx")
def lead_receipt(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("receipt", lid, "docx")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, _DOCX_MT)


@router.get("/admin-console/leads/{lid}/quotation.pdf")
def lead_quotation_pdf(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("quotation", lid, "pdf")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, "application/pdf", inline=True)


@router.get("/admin-console/leads/{lid}/receipt.pdf")
def lead_receipt_pdf(lid: int):
    from app.routers.pages import serve_generated
    path = _issue_doc("receipt", lid, "pdf")
    if not path:
        return RedirectResponse("/admin-console/leads", status_code=303)
    return serve_generated(path, "application/pdf", inline=True)


def _doc_email_draft(kind: str, lead: dict) -> tuple:
    """ร่างหัวข้อ + เนื้อความอีเมลส่งใบเสนอราคา/ใบเสร็จให้ลูกค้า (แก้ไขได้ก่อนส่ง)"""
    school = (lead.get("school_name") or "").strip()
    who = (lead.get("contact_name") or "").strip() or school or "ผู้ติดต่อ"
    packages = lead.get("packages") or "ครบทุกงาน"
    amount = f"{float(lead.get('amount') or 0):,.0f}"
    sname = SELLER.get("name") or "Easy Ekkasan"
    phone = SELLER.get("phone") or ""
    email = SELLER.get("email") or ""
    sign = f"ขอแสดงความนับถือ\n{sname}\nEasy Ekkasan\nโทร {phone}  อีเมล {email}"
    if kind == "receipt":
        subject = f"ใบเสร็จรับเงิน ระบบ Easy Ekkasan - {school}"
        body = (f"เรียน {who}\n\n"
                "ขอบคุณที่ใช้บริการระบบจัดการเอกสารและพัสดุโรงเรียน Easy Ekkasan "
                "ทางเราได้รับชำระเงินเรียบร้อยแล้ว และขอส่งใบเสร็จรับเงินตามไฟล์แนบมาพร้อมนี้\n\n"
                f"รายการ: {packages}\nยอดชำระ: {amount} บาท\n\n"
                "บัญชีของท่านเปิดใช้งานเรียบร้อยแล้ว หากมีข้อสงสัยติดต่อกลับได้ตลอดครับ\n\n" + sign)
    else:
        subject = f"ใบเสนอราคา ระบบ Easy Ekkasan - {school}"
        body = (f"เรียน {who}\n\n"
                "ตามที่ท่านสนใจใช้บริการระบบจัดการเอกสารและพัสดุโรงเรียน Easy Ekkasan "
                "ทางเราขอส่งใบเสนอราคาตามไฟล์แนบมาพร้อมนี้\n\n"
                f"รายการ: {packages}\nยอดรวม: {amount} บาท (สิทธิ์ใช้งาน 1 ปี)\n\n"
                "หากต้องการสั่งซื้อ สามารถชำระผ่าน PromptPay แล้วแจ้งสลิปกลับมาได้เลย "
                "หรือสอบถามเพิ่มเติมได้ตลอดครับ\n\n" + sign)
    return subject, body


@router.get("/admin-console/leads/{lid}/email", response_class=HTMLResponse)
def lead_email_compose(lid: int, request: Request, kind: str = "quotation"):
    """หน้าเด้งร่างอีเมล (แก้ไขได้) ก่อนส่งใบเสนอราคา/ใบเสร็จให้ลูกค้า"""
    kind = "receipt" if kind == "receipt" else "quotation"
    lead = get_lead(lid)
    if not lead:
        return RedirectResponse("/admin-console/leads", status_code=303)
    subject, body = _doc_email_draft(kind, lead)
    doc_label = "ใบเสร็จรับเงิน" if kind == "receipt" else "ใบเสนอราคา"
    return templates.TemplateResponse("email_compose.html", {
        "request": request, "lid": lid, "kind": kind, "doc_label": doc_label,
        "to": lead.get("email") or "", "subject": subject, "body": body,
        "school": lead.get("school_name") or "", "smtp_ok": bool((SELLER.get("smtp_host") or "").strip()),
    })


@router.post("/admin-console/leads/{lid}/email")
def lead_email_send(lid: int, request: Request, kind: str = Form("quotation"),
                    to: str = Form(""), subject: str = Form(""), body: str = Form("")):
    """ส่งอีเมลจริง + แนบ PDF ใบเสนอราคา/ใบเสร็จ"""
    kind = "receipt" if kind == "receipt" else "quotation"
    to = (to or "").strip()
    if not to:
        request.session["lead_msg"] = {"ok": False, "text": "ไม่ได้ระบุอีเมลผู้รับ"}
        return RedirectResponse("/admin-console/leads", status_code=303)
    pdf_path = _issue_doc(kind, lid, "pdf")
    if not pdf_path:
        request.session["lead_msg"] = {"ok": False, "text": "ออกไฟล์เอกสารไม่สำเร็จ"}
        return RedirectResponse("/admin-console/leads", status_code=303)
    import html as _html
    html_body = "<div style='font-family:sans-serif;font-size:15px;white-space:pre-wrap;'>" \
        + _html.escape(body) + "</div>"
    # ใบเสนอราคา: แนบปุ่ม "ชำระเงิน" ไปหน้าเว็บชำระของใบนี้ (ลิงก์เฉพาะ ไม่ต้องล็อกอิน)
    if kind == "quotation":
        base = (SELLER.get("base_url") or "").rstrip("/")
        if base:
            from app.routers.sales import make_pay_token
            pay_url = f"{base}/pay/{make_pay_token(lid)}"
            html_body += (
                "<div style='margin-top:22px; text-align:center;'>"
                f"<a href='{pay_url}' style='background:#16b364; color:#fff; text-decoration:none;"
                " padding:13px 30px; border-radius:11px; font-weight:700; font-size:16px; display:inline-block;'>"
                "ชำระเงินออนไลน์</a>"
                "<div style='color:#94a3b8; font-size:12px; margin-top:8px;'>สแกน PromptPay + อัปโหลดสลิปได้ในลิงก์เดียว</div></div>")
    from app.services.mailer import send_email
    ok = send_email(to, subject or "เอกสารจาก Easy Ekkasan", html_body, attachments=[pdf_path])
    doc_label = "ใบเสร็จ" if kind == "receipt" else "ใบเสนอราคา"
    request.session["lead_msg"] = ({"ok": True, "text": f"ส่ง{doc_label}ไปที่ {to} แล้ว"}
                                   if ok else {"ok": False, "text": "ส่งอีเมลไม่สำเร็จ (ตรวจ SMTP)"})
    return RedirectResponse("/admin-console/leads", status_code=303)


_SLIP_NAME = re.compile(r"^slip_\d{14}_[0-9a-f]{8}\.(png|jpg|jpeg|webp|pdf)$")


@router.get("/admin-console/leads/slip/{name}")
def lead_slip(name: str):
    if not _SLIP_NAME.match(name):
        raise HTTPException(status_code=404)
    path = get_data_dir() / "leads" / name
    if not path.exists():
        raise HTTPException(status_code=404)
    mt = "application/pdf" if name.endswith(".pdf") else "image/*"
    return FileResponse(str(path), media_type=mt, content_disposition_type="inline")


@router.post("/admin-console/backup-now")
def backup_now():
    """สำรองข้อมูลทันที + ทดสอบการอัปขึ้น R2 (โชว์ผลบนหน้าคอนโซล)"""
    from app.services.backup import manual_backup
    msg = manual_backup()
    from urllib.parse import quote
    return RedirectResponse(f"/admin-console?msg={quote(msg)}", status_code=303)


@router.post("/admin-console/tenant")
def create_tenant(name: str = Form(...), admin_user: str = Form(...),
                  admin_pw: str = Form(...), expiry: str = Form(""),
                  max_users: str = Form("3")):
    slug = _slugify(name)
    # กันชื่อผู้ใช้ซ้ำ
    db = acc_session()
    try:
        exists = db.query(Account).filter_by(username=admin_user.strip()).first()
        base_slug, n = slug, 1
        while db.query(Tenant).filter_by(slug=slug).first():
            n += 1; slug = f"{base_slug}-{n}"
    finally:
        db.close()
    if exists:
        return RedirectResponse("/admin-console?msg=ชื่อผู้ใช้นี้ถูกใช้แล้ว", status_code=303)
    try:
        mx = int(max_users)
    except ValueError:
        mx = 3
    provision_tenant(name, slug, admin_user, admin_pw,
                     expiry_date=_parse_date(expiry), max_users=mx)
    return RedirectResponse("/admin-console?msg=สร้างโรงเรียนเรียบร้อยแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/expiry")
def set_expiry(tid: int, expiry: str = Form("")):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            t.expiry_date = _parse_date(expiry)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=อัปเดตวันหมดอายุแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/toggle")
def toggle_active(tid: int):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            t.active = not t.active
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=เปลี่ยนสถานะแล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/adduser")
def add_user(tid: int, username: str = Form(...), password: str = Form(...)):
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if not t:
            return RedirectResponse("/admin-console?msg=ไม่พบโรงเรียน", status_code=303)
        n = db.query(Account).filter_by(tenant_id=tid).count()
        if n >= (t.max_users or 3):
            return RedirectResponse(f"/admin-console?msg=เกินจำนวนผู้ใช้สูงสุด ({t.max_users})", status_code=303)
        if db.query(Account).filter_by(username=username.strip()).first():
            return RedirectResponse("/admin-console?msg=ชื่อผู้ใช้นี้ถูกใช้แล้ว", status_code=303)
        db.add(Account(tenant_id=tid, username=username.strip(),
                       password_hash=hash_password(password), role="user",
                       display_name=t.name, must_change_password=True))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=เพิ่มผู้ใช้แล้ว", status_code=303)


@router.post("/admin-console/account/{aid}/reset")
def reset_password(aid: int, password: str = Form(...)):
    db = acc_session()
    try:
        a = db.get(Account, aid)
        if a:
            a.password_hash = hash_password(password)
            a.must_change_password = True   # ให้ผู้ใช้ตั้งรหัสของตัวเองหลังถูกรีเซ็ต
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=รีเซ็ตรหัสผ่านแล้ว", status_code=303)


@router.post("/admin-console/account/{aid}/delete")
def delete_user(aid: int):
    db = acc_session()
    try:
        a = db.get(Account, aid)
        if a and a.role != "superadmin":
            db.delete(a); db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin-console?msg=ลบผู้ใช้แล้ว", status_code=303)


@router.post("/admin-console/tenant/{tid}/delete")
def delete_tenant(tid: int):
    """ลบโรงเรียนออกจากระบบทั้งหมด: บัญชีผู้ใช้ + ข้อมูลกลาง + ไฟล์ฐานข้อมูลของโรงเรียน
    (ลบถาวร ใช้เมื่อโรงเรียนเลิกใช้/สร้างผิด)"""
    import shutil
    from urllib.parse import quote
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if not t:
            return RedirectResponse("/admin-console?msg=ไม่พบโรงเรียน", status_code=303)
        name = t.name
        db.query(Account).filter_by(tenant_id=tid).delete()
        db.delete(t)
        db.commit()
    finally:
        db.close()
    # ลบไฟล์ฐานข้อมูลของโรงเรียน (ปิด engine ก่อน)
    try:
        from app.tenancy import dispose_engine
        dispose_engine(tid)
        folder = get_data_dir() / "schools" / str(tid)
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass
    return RedirectResponse(f"/admin-console?msg={quote('ลบโรงเรียน ' + name + ' ออกจากระบบแล้ว')}", status_code=303)


@router.post("/admin-console/tenant/{tid}/modules")
def set_tenant_modules(tid: int, mod: list[str] = Form([])):
    """กำหนดว่าโรงเรียนนี้ "ซื้อ" งานไหนไว้บ้าง (ปุ่มแก้มือของผู้ขาย)

    ถ้าตั้งครบทุกงาน -> ปลดโควตาทดลอง (ไม่ต้องใช้แล้ว)
    ถ้าตั้งไม่ครบ + ยังไม่มีโควตา -> ให้โควตาทดลองไว้ใช้กับงานที่เหลือ
    """
    from urllib.parse import quote
    from app.modules import MODULE_KEYS, modules_csv, parse_modules
    from app.accounts import TRIAL_DOC_LIMIT
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if not t:
            return RedirectResponse("/admin-console?msg=ไม่พบโรงเรียน", status_code=303)
        mods = parse_modules(",".join(mod or []))
        t.modules = modules_csv(mods)
        if mods:
            t.plan = "member"
        if mods == set(MODULE_KEYS):
            t.docs_limit = 0                       # ซื้อครบ: ไม่ต้องใช้โควตาอีก
        elif not (t.docs_limit or 0):
            t.docs_limit = TRIAL_DOC_LIMIT         # ยังไม่ครบ: มีโควตาไว้ทดลองงานที่เหลือ
        db.commit()
        n = len(mods)
    finally:
        db.close()
    return RedirectResponse(f"/admin-console?msg={quote('ตั้งสิทธิ์เป็น %d งานแล้ว' % n)}", status_code=303)


@router.post("/admin-console/tenant/{tid}/renew")
def renew_tenant(tid: int, days: str = Form("365")):
    """ต่ออายุเป็นสมาชิก "ครบทุกงาน": ตั้ง plan=member, ให้สิทธิ์ครบ, ปลดโควตา, ต่อวันหมดอายุ
    (ถ้าต้องการขายเป็นรายงาน ใช้ปุ่มตั้งสิทธิ์รายงานแทน)"""
    from datetime import timedelta
    from urllib.parse import quote
    from app.modules import ALL_MODULES_CSV
    try:
        add = int(days)
    except ValueError:
        add = 365
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            base = max(date.today(), t.expiry_date) if t.expiry_date else date.today()
            t.expiry_date = base + timedelta(days=add)
            t.plan = "member"
            t.modules = ALL_MODULES_CSV
            t.docs_limit = 0
            db.commit()
            exp = t.expiry_date.isoformat()
        else:
            return RedirectResponse("/admin-console?msg=ไม่พบโรงเรียน", status_code=303)
    finally:
        db.close()
    return RedirectResponse(f"/admin-console?msg={quote('ต่ออายุเป็นสมาชิกถึง ' + exp)}", status_code=303)


@router.post("/admin-console/tenant/{tid}/quota")
def add_quota(tid: int, amount: str = Form("50")):
    """เพิ่มโควตาเอกสารช่วงทดลองใช้ (บวกเข้ากับ docs_limit เดิม)"""
    from urllib.parse import quote
    try:
        add = int(amount)
    except ValueError:
        add = 50
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        if t:
            t.plan = "trial"
            t.docs_limit = (t.docs_limit or 0) + add
            db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/admin-console?msg={quote('เพิ่มโควตาทดลองใช้ +' + str(add) + ' ฉบับ')}", status_code=303)
