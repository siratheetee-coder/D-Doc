# -*- coding: utf-8 -*-
"""
admin.py - งานธุรการ
หน้าหลักธุรการ + ทะเบียนหนังสือรับ/ส่ง + บันทึกข้อความ + คำสั่งโรงเรียน (ออก Word) + นำเข้า Excel
เลขบันทึกข้อความ/คำสั่ง ใช้ชุดเลขกลางร่วมกับทุกงาน (suggest_doc_no/commit_doc_no)
"""
import re
import uuid
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, get_data_dir
from app.models import (
    School, IncomingLetter, OutgoingLetter, OfficeMemo, SchoolOrder, Person, Department,
    OfficialLetter, CertificateBatch, Student, IssuedDocNo, LetterRecipient,
)
from app.services import file_upload
from app.services.doc_number import (
    suggest_next, commit_number, suggest_doc_no, commit_doc_no, check_doc_no, format_doc_no, doc_year,
    parse_seq, remove_issued,
)
from app.services.office_doc import render_memo, render_order, render_official_letter
from app.services.admin_io import build_admin_template, import_admin_workbook, export_admin_register
from app.services.pdf_extract import extract_letter_fields
from app.thai_utils import current_fiscal_year, parse_be_date, be_date_input, SCHOOL_LEVELS
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated
from app.thai_utils import fiscal_year_options

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PDF = "application/pdf"


def _ai_key() -> str:
    """AI key กลาง (หลังบ้าน) เฉพาะสมาชิก - คืน '' ถ้าไม่ใช่สมาชิก/ไม่ได้ตั้ง key"""
    from app.tenancy import current_school_id
    from app.accounts import ai_key_for
    return ai_key_for(current_school_id.get())

# ใช้ฟังก์ชันกลางจาก file_upload (alias ชื่อเดิมเพื่อความเข้ากันได้)
from app.services.file_upload import (
    SAFE_FILE_NAME as _SAFE_FILE_NAME, uploads_dir as _uploads_dir,
    detect_ext as _detect_ext, save_upload as _save_upload, fetch_file as _fetch_file,
)


def _ai_read_fields(data: bytes, ext: str) -> dict:
    """อ่านฟิลด์หนังสือด้วย AI (vision) สำหรับ PDF/รูป; docx หรือไม่มี key -> อ่านแบบข้อความ
    คืน dict คีย์เดียวกับ extract_letter_fields เสมอ (มี fallback ให้ใช้งานได้เสมอ)"""
    key = _ai_key()
    if key and ext in ("pdf", "png", "jpg", "webp"):
        from app.services.ai_extract import read_letter_fields_ai
        r = read_letter_fields_ai(data, ext, key)
        if r.get("ok"):
            return r
    # สำรอง: docx / ไม่มี key / AI พลาด -> อ่านจากข้อความตามเดิม
    return None


def _read_and_confirm(request, db, kind: str, data: bytes, ext: str, use_ai: bool):
    """เซฟไฟล์ + อ่านฟิลด์ (AI ถ้า use_ai ไม่งั้นข้อความ) + แสดงหน้าตรวจก่อนบันทึก"""
    name = _save_upload(data, ext)
    fields = None
    if use_ai:
        fields = _ai_read_fields(data, ext)
    if fields is None:
        fields = extract_letter_fields(str(_uploads_dir() / name))
    return _render_letter_confirm(request, db, kind, name, fields)


def _render_letter_confirm(request, db, kind: str, pending_file: str, fields: dict):
    """หน้ายืนยันลงทะเบียน (เติมค่าจากการอ่านไฟล์ให้แล้ว) - รองรับ incoming/outgoing/memo"""
    fy = current_fiscal_year()
    ctx = {
        "request": request, "kind": kind, "fiscal_year": fy,
        "pending_file": pending_file, "fields": fields,
        "letter_date_be": be_date_input(fields.get("letter_date")),
        "is_pdf": pending_file.lower().endswith(".pdf"),
        "is_img": pending_file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")),
    }
    if kind == "incoming":
        ctx["sug_recv"] = suggest_next(db, "incoming", fy)
    elif kind == "outgoing":
        school = get_school(db)
        seq = suggest_next(db, "outgoing", fy)
        ctx["sug_no"] = f"{school.doc_prefix or 'ศธ'} {seq}/{doc_year('outgoing', fy)}"
    elif kind == "memo":
        ctx["school"] = get_school(db)
        ctx["sug_memo"] = suggest_doc_no(db, "memo", fy)
    else:  # order
        ctx["school"] = get_school(db)
        ctx["sug_order"] = suggest_doc_no(db, "command", fy)
    return templates.TemplateResponse("letter_confirm.html", ctx)


# ---------------- Dashboard ----------------
@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    fy = current_fiscal_year()
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "n_in": db.query(IncomingLetter).filter_by(fiscal_year=fy).count(),
        "n_out": db.query(OutgoingLetter).filter_by(fiscal_year=fy).count(),
        "n_memo": db.query(OfficeMemo).filter_by(fiscal_year=fy).count(),
        "n_order": db.query(SchoolOrder).filter_by(fiscal_year=fy).count(),
        "recent_memos": db.query(OfficeMemo).order_by(OfficeMemo.id.desc()).limit(5).all(),
        "recent_orders": db.query(SchoolOrder).order_by(SchoolOrder.id.desc()).limit(5).all(),
        "setup": _admin_setup(db, get_school(db)),
    })


def _admin_setup(db, school):
    from app.services.module_setup import admin_steps
    return admin_steps(db, school)


# ---------------- ทะเบียนหนังสือรับ ----------------
@router.get("/admin/incoming", response_class=HTMLResponse)
def incoming_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    rows = (db.query(IncomingLetter).filter_by(fiscal_year=fy)
            .order_by(IncomingLetter.recv_no).all())
    years = fiscal_year_options(
        [r[0] for r in db.query(IncomingLetter.fiscal_year).distinct()], fy)
    return templates.TemplateResponse("incoming.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "years": years,
        "sug_recv": suggest_next(db, "incoming", fy),
    })


@router.post("/admin/incoming")
def incoming_add(db: Session = Depends(get_db), fiscal_year: int = Form(...),
                 recv_no: str = Form(""), recv_date: str = Form(""), letter_no: str = Form(""),
                 letter_date: str = Form(""), from_org: str = Form(""), to_person: str = Form(""),
                 subject: str = Form(""), action_note: str = Form(""), pending_file: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    rno = _to_int(recv_no, 0) or suggest_next(db, "incoming", fy)
    fp = pending_file.strip() if _SAFE_FILE_NAME.match(pending_file.strip()) else ""
    db.add(IncomingLetter(
        fiscal_year=fy, recv_no=rno, recv_date=parse_be_date(recv_date),
        letter_no=letter_no.strip(), letter_date=parse_be_date(letter_date),
        from_org=from_org.strip(), to_person=to_person.strip(),
        subject=subject.strip(), action_note=action_note.strip(), file_path=fp,
    ))
    commit_number(db, "incoming", fy, rno)
    db.commit()
    return RedirectResponse("/admin/incoming", status_code=303)


@router.post("/admin/incoming/upload")
async def incoming_upload(request: Request, db: Session = Depends(get_db),
                          file: UploadFile = File(...), ai: str = Form("")):
    data = await file.read()
    ext = _detect_ext(data, file.filename or "")
    if not ext:
        return RedirectResponse("/admin/incoming?err=notpdf", status_code=303)
    return _read_and_confirm(request, db, "incoming", data, ext, use_ai=bool(ai))


@router.post("/admin/incoming/fetch")
async def incoming_fetch(request: Request, db: Session = Depends(get_db), url: str = Form("")):
    data, ext, err = _fetch_file(url)
    if err:
        return RedirectResponse(f"/admin/incoming?err={err}", status_code=303)
    name = _save_upload(data, ext)
    fields = extract_letter_fields(str(_uploads_dir() / name))
    return _render_letter_confirm(request, db, "incoming", name, fields)


@router.post("/admin/incoming/{rid}/delete")
def incoming_delete(rid: int, db: Session = Depends(get_db)):
    r = db.get(IncomingLetter, rid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/admin/incoming", status_code=303)


# ---------------- เวียนหนังสือรับ: ธุรการเสนอ -> ผอ. สั่งการ -> ครูรับทราบ ----------------
_ROUTE_LABEL = {"": "ยังไม่เวียน", "director": "รอ ผอ. สั่งการ", "sent": "เวียนแล้ว"}


def _can_endorse(request) -> bool:
    """ผู้สั่งการได้ = ผอ./รองผอ. หรือไอดีหลัก (โรงเรียนเล็กที่ ผอ. ใช้ไอดีหลักเอง)"""
    s = request.session
    return bool(s.get("director") or s.get("owner"))


def _staff_options(db, tid):
    """บุคลากรที่เลือกเป็นผู้รับได้ + ธงว่ามีบัญชีเข้าระบบไหม (ไม่มีบัญชี = ธุรการบันทึกรับทราบแทน)"""
    from app.accounts import list_teacher_accounts
    linked = {a["person_id"] for a in list_teacher_accounts(tid) if a["active"]} if tid else set()
    people = db.query(Person).filter(Person.active == True).order_by(Person.id).all()  # noqa: E712
    return [{"id": p.id, "name": p.name, "position": p.position or "", "has_account": p.id in linked,
             "has_email": bool((p.email or "").strip())} for p in people]


def _pick_ids(form) -> list:
    out = []
    for v in form.getlist("pid"):
        n = _to_int(v, 0)
        if n and n not in out:
            out.append(n)
    return out


def _add_recipients(db, r, ids, notify=True) -> list:
    """เพิ่มผู้รับ (ข้ามคนที่มีอยู่แล้ว) คืนแถวที่เพิ่มจริง · notify = แจ้งกระดิ่งรายคนเลย"""
    have = {x.person_id for x in r.recipients}
    added = []
    for pid in ids:
        p = db.get(Person, pid)
        if not p or pid in have:
            continue
        rc = LetterRecipient(person_id=pid, name=p.name)
        r.recipients.append(rc)
        added.append(rc)
    db.flush()
    if notify:
        _notify(db, r, added)
    return added


def _notify(db, r, rows):
    from app.services.nav import create_notice
    for rc in rows:
        create_notice(db, rc.person_id, f"หนังสือเวียน: {r.subject or 'หนังสือรับ'}",
                      reason=(r.director_order or r.from_org or "")[:120],
                      link=f"/me/letters/{rc.id}", level="warn")
    _email_letter(db, r, rows)


_MAIL_ATTACH_MAX = 10 * 1024 * 1024     # ไฟล์ใหญ่กว่านี้ไม่แนบ ให้กดลิงก์เปิดในระบบแทน


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _letter_mail_html(school, r, rcid, attached) -> str:
    from app.seller_config import SELLER
    from urllib.parse import quote
    base = (SELLER.get("base_url") or "").rstrip("/")
    path = f"/me/letters/{rcid}"
    link = (base + "/login?next=" + quote(path, safe="")) if base else path
    who = f"{_esc(r.director_name)} สั่งการ" if r.director_name else "ข้อความจากธุรการ"
    order = (f'<div style="background:#eef2ff;border-radius:10px;padding:12px 14px;margin:14px 0">'
             f'<b style="color:#4338ca">{who}</b><br>{_esc(r.director_order).replace(chr(10), "<br>")}</div>'
             if r.director_order else "")
    note = "ไฟล์หนังสือแนบมากับอีเมลนี้" if attached else "เปิดอ่านตัวหนังสือได้ที่ปุ่มด้านล่าง"
    return f"""<div style="font-family:'Sarabun','Leelawadee UI','Segoe UI',Tahoma,sans-serif;max-width:620px;margin:0 auto;color:#334155;font-size:15px;line-height:1.6">
  <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;padding:16px 20px;border-radius:12px 12px 0 0">
    <div style="font-size:13px;opacity:.9">หนังสือเวียน {_esc(school)}</div>
    <h2 style="margin:4px 0 0;font-size:19px">{_esc(r.subject or 'หนังสือรับ')}</h2>
  </div>
  <div style="padding:16px 20px;background:#fff">
    จาก {_esc(r.from_org or '-')}{(' ที่ ' + _esc(r.letter_no)) if r.letter_no else ''}
    {order}
    <p style="margin:0">{note} อ่านแล้วกดปุ่มรับทราบในระบบด้วย</p>
    <p style="margin:18px 0"><a href="{link}" style="background:#16a34a;color:#fff;text-decoration:none;padding:11px 24px;border-radius:9px;font-weight:700;display:inline-block">เปิดหนังสือและกดรับทราบ</a></p>
  </div>
  <div style="padding:10px 20px;color:#7b8190;font-size:12.5px">อีเมลนี้ส่งอัตโนมัติจากระบบ Easy Ekkasan เพราะคุณใส่อีเมลไว้รับหนังสือเวียน</div>
</div>"""


def _email_letter(db, r, rows):
    """ส่งหนังสือเวียนเข้าอีเมลผู้รับที่ใส่อีเมลไว้ (เธรดแยก หน้าเว็บไม่ต้องรอ)"""
    jobs = []
    school = get_school(db).name or ""
    attach = None
    if r.file_path and _SAFE_FILE_NAME.match(r.file_path):
        f = _uploads_dir() / r.file_path
        try:
            if f.exists() and f.stat().st_size <= _MAIL_ATTACH_MAX:
                ext = Path(r.file_path).suffix
                attach = (f"หนังสือ{(' ' + r.recv_no) if r.recv_no else ''}{ext}", f.read_bytes())
        except OSError:
            attach = None
    for rc in rows:
        p = db.get(Person, rc.person_id)
        to = ((p.email if p else "") or "").strip()
        if to:
            jobs.append((to, f"[หนังสือเวียน] {r.subject or 'หนังสือรับ'}",
                         _letter_mail_html(school, r, rc.id, bool(attach))))
    if not jobs:
        return 0
    import contextvars
    import threading
    from app.services.mailer import send_email

    def run():
        for to, subject, html in jobs:
            try:
                send_email(to, subject, html, attachments=[attach] if attach else None)
            except Exception as e:      # noqa: BLE001
                print("[letter-mail] ส่งไม่สำเร็จ:", e)

    # copy_context: ให้เธรดรู้ว่าเป็นโรงเรียนไหน (ระบบตัวอย่างจะไม่ส่งอีเมลจริง)
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(run,), daemon=True).start()
    return len(jobs)


def _signer(db, request):
    """ชื่อ + ไฟล์ลายเซ็นของผู้สั่งการ: บัญชีที่ผูกบุคลากร > ชื่อ ผอ. ในตั้งค่า"""
    from app.services.signature import _norm
    p = db.get(Person, request.session.get("person_id") or 0)
    if p:
        return p.name, p.signature or ""
    name = (get_school(db).director_name or "").strip() or (request.session.get("name") or "")
    for q in db.query(Person).filter(Person.signature != "").all():
        if _norm(q.name) == _norm(name):
            return name, q.signature
    return name, ""


@router.get("/admin/incoming/{rid}", response_class=HTMLResponse)
def incoming_detail(rid: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    r = db.get(IncomingLetter, rid)
    if not r:
        return RedirectResponse("/admin/incoming", status_code=303)
    acked = sum(1 for x in r.recipients if x.ack_at)
    return templates.TemplateResponse("incoming_detail.html", {
        "request": request, "r": r, "msg": msg, "status_label": _ROUTE_LABEL.get(r.route_status or "", ""),
        "staff": _staff_options(db, request.session.get("tid")), "acked": acked,
        "picked": {x.person_id for x in r.recipients}, "can_endorse": _can_endorse(request),
        "director_name": get_school(db).director_name or "",
    })


@router.post("/admin/incoming/{rid}/route")
async def incoming_route(rid: int, request: Request, db: Session = Depends(get_db)):
    """ธุรการ: director = เสนอ ผอ. สั่งการ, send = เวียนเลย (ไม่ผ่าน ผอ.), add = เวียนเพิ่ม, recall = ดึงกลับ"""
    r = db.get(IncomingLetter, rid)
    if not r:
        return RedirectResponse("/admin/incoming", status_code=303)
    form = await request.form()
    action = form.get("action", "")
    note = (form.get("note") or "").strip()[:2000]
    ids = _pick_ids(form)
    back = f"/admin/incoming/{rid}"
    if action == "recall" and r.route_status == "director":
        r.route_status = ""
        db.commit()
        return RedirectResponse(back + "?msg=ดึงกลับจาก ผอ. แล้ว", status_code=303)
    if action == "director" and r.route_status != "sent":
        r.route_status, r.route_note = "director", note
        # ผู้รับที่ธุรการเลือก = ข้อเสนอ ผอ. แก้ได้ตอนสั่งการ (ยังไม่แจ้งครูจนกว่า ผอ. จะสั่ง)
        r.recipients = [x for x in r.recipients if x.person_id in ids]
        _add_recipients(db, r, ids, notify=False)
        db.commit()
        return RedirectResponse(back + "?msg=เสนอ ผอ. แล้ว รอ ผอ. สั่งการ", status_code=303)
    if action in ("send", "add"):
        if not ids:
            return RedirectResponse(back + "?msg=เลือกผู้รับอย่างน้อย 1 คน", status_code=303)
        if action == "send" and r.route_status != "sent":
            r.director_order = note or r.director_order
            r.route_status, r.sent_at = "sent", datetime.now()
            if note and not r.action_note:
                r.action_note = note[:200]
        n = len(_add_recipients(db, r, ids))
        db.commit()
        return RedirectResponse(back + f"?msg=เวียนถึง {n} คนแล้ว", status_code=303)
    return RedirectResponse(back, status_code=303)


@router.post("/admin/incoming/{rid}/endorse")
async def incoming_endorse(rid: int, request: Request, db: Session = Depends(get_db)):
    """ผอ. สั่งการ + เลือกผู้รับ -> เวียนถึงครูทันที"""
    if not _can_endorse(request):
        return RedirectResponse(f"/admin/incoming/{rid}", status_code=303)
    r = db.get(IncomingLetter, rid)
    if not r or r.route_status == "sent":
        return RedirectResponse("/approvals?err=หนังสือนี้สั่งการไปแล้ว", status_code=303)
    form = await request.form()
    order = (form.get("order") or "").strip()[:2000] or "ทราบ"
    ids = _pick_ids(form)
    r.director_order = order
    r.director_name, r.director_sig = _signer(db, request)
    r.director_at = r.sent_at = datetime.now()
    r.route_status = "sent"
    if not r.action_note:
        r.action_note = order[:200]
    r.recipients = [x for x in r.recipients if x.person_id in ids]
    _add_recipients(db, r, ids, notify=False)
    _notify(db, r, r.recipients)
    n = len(r.recipients)
    db.commit()
    dest = "/approvals" if request.session.get("director") and not request.session.get("owner") else f"/admin/incoming/{rid}"
    return RedirectResponse(dest + f"?msg=สั่งการแล้ว เวียนถึง {n} คน", status_code=303)


@router.post("/admin/incoming/{rid}/ack/{rcid}")
def incoming_ack_for(rid: int, rcid: int, request: Request, db: Session = Depends(get_db)):
    """ธุรการบันทึกรับทราบแทน (ครูที่ไม่มีบัญชี/ลงชื่อในกระดาษ) กดซ้ำ = ยกเลิก"""
    rc = db.get(LetterRecipient, rcid)
    if rc and rc.letter_id == rid:
        if rc.ack_at and rc.ack_by:
            rc.ack_at, rc.ack_by = None, ""
        elif not rc.ack_at:
            rc.ack_at, rc.ack_by = datetime.now(), (request.session.get("name") or "ธุรการ")
        db.commit()
    return RedirectResponse(f"/admin/incoming/{rid}#recipients", status_code=303)


# ---------------- บัญชีครู + อีเมลรับหนังสือ (หน้าในงานธุรการ) ----------------
_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(v) -> str | None:
    """คืนอีเมลที่ใช้ได้ / '' = ลบ / None = รูปแบบผิด"""
    v = (v or "").strip()[:200]
    if not v:
        return ""
    return v if _EMAIL_RX.match(v) else None


def _random_password() -> str:
    """รหัสอ่านออกเสียงได้ + ตัวเลข 3 หลัก (เกณฑ์เดียวกับปุ่มสุ่มหน้าบัญชีครู)"""
    import secrets
    from app.accounts import password_problem
    c, v = "bcdfghjkmnpqrstvwxz", "aeiou"
    while True:
        s = "".join(secrets.choice(c) + secrets.choice(v) for _ in range(3)).capitalize()
        s += "".join(secrets.choice("23456789") for _ in range(3))
        if not password_problem(s):
            return s


def _staff_accounts_ctx(request, db, **extra):
    from app.accounts import list_teacher_accounts
    tid = request.session.get("tid")
    acc = {a["person_id"]: a for a in list_teacher_accounts(tid)} if tid else {}
    people = db.query(Person).filter(Person.active == True).order_by(Person.id).all()  # noqa: E712
    rows = [{"p": p, "acc": acc.get(p.id)} for p in people]
    ctx = {"request": request, "rows": rows, "is_owner": bool(request.session.get("owner")),
           "n_none": sum(1 for x in rows if not x["acc"]),
           "n_email": sum(1 for x in rows if (x["p"].email or "").strip()),
           "msg": "", "err": "", "created": None}
    ctx.update(extra)
    return ctx


@router.get("/admin/staff-accounts", response_class=HTMLResponse)
def staff_accounts_page(request: Request, db: Session = Depends(get_db), msg: str = "", err: str = ""):
    return templates.TemplateResponse("staff_accounts.html", _staff_accounts_ctx(request, db, msg=msg, err=err))


@router.post("/admin/staff-accounts/create", response_class=HTMLResponse)
async def staff_accounts_create(request: Request, db: Session = Depends(get_db)):
    """ไอดีหลักกดสร้างบัญชีครูให้หลายคนทีเดียว ระบบตั้งไอดี+รหัสให้ แสดงรหัสครั้งเดียว"""
    if not request.session.get("owner"):
        return RedirectResponse("/admin/staff-accounts?err=ให้ไอดีหลักของโรงเรียนเป็นคนสร้างบัญชี", status_code=303)
    from app.accounts import add_teacher_account, audit
    tid = request.session.get("tid")
    created, failed = [], []
    for pid in _pick_ids(await request.form()):
        p = db.get(Person, pid)
        if not p or not p.active:
            continue
        pw = _random_password()
        res = add_teacher_account(tid, pid, f"kru{pid}", pw, display_name=p.name)
        if res.get("ok"):
            created.append({"name": p.name, "username": res["username"], "password": pw})
            audit("teacher.add", request=request, target=res["username"], detail=f"ผูกกับบุคลากร: {p.name}")
        else:
            failed.append(f"{p.name}: {res.get('error', '')}")
    if not created:
        return RedirectResponse("/admin/staff-accounts?err=" + ("ไม่ได้เลือกครู" if not failed else " ".join(failed)),
                                status_code=303)
    # เรนเดอร์ตรง (ไม่ redirect) รหัสผ่านอยู่ในหน้านี้ครั้งเดียว ไม่ผ่าน URL/session
    return templates.TemplateResponse("staff_accounts.html", _staff_accounts_ctx(
        request, db, created=created, err=" ".join(failed)))


@router.post("/admin/staff-accounts/email/{pid}")
def staff_email_set(pid: int, db: Session = Depends(get_db), email: str = Form("")):
    p = db.get(Person, pid)
    v = _clean_email(email)
    if not p:
        return RedirectResponse("/admin/staff-accounts", status_code=303)
    if v is None:
        return RedirectResponse(f"/admin/staff-accounts?err=อีเมลของ {p.name} ไม่ถูกรูปแบบ", status_code=303)
    p.email = v
    db.commit()
    return RedirectResponse(f"/admin/staff-accounts?msg=บันทึกอีเมลของ {p.name} แล้ว", status_code=303)


@router.post("/me/email")
def my_email_set(request: Request, db: Session = Depends(get_db), email: str = Form(""), back: str = Form("")):
    """ครูใส่อีเมลของตัวเอง ใช้รับหนังสือเวียนและแจ้งผลต่าง ๆ ทางอีเมล"""
    dest = back if back in ("/me/letters", "/account/profile") else "/me/letters"
    p = db.get(Person, request.session.get("person_id") or 0)
    v = _clean_email(email)
    if not p:
        return RedirectResponse(dest, status_code=303)
    if v is None:
        return RedirectResponse(dest + "?email=bad", status_code=303)
    p.email = v
    db.commit()
    return RedirectResponse(dest + ("?email=ok" if v else "?email=off"), status_code=303)


# ---------------- หนังสือถึงฉัน (ครูทุกบัญชีที่ผูกบุคลากร ไม่ขึ้นกับงานที่ซื้อ) ----------------
def _my_rc(db, request, rcid):
    rc = db.get(LetterRecipient, rcid)
    pid = request.session.get("person_id")
    ok = rc and pid and rc.person_id == pid and rc.letter.route_status == "sent"
    return rc if ok else None


@router.get("/me/letters", response_class=HTMLResponse)
def my_letters(request: Request, db: Session = Depends(get_db), email: str = ""):
    pid = request.session.get("person_id") or 0
    me = db.get(Person, pid) if pid else None
    rows = (db.query(LetterRecipient).join(IncomingLetter)
            .filter(LetterRecipient.person_id == pid, IncomingLetter.route_status == "sent")
            .order_by(LetterRecipient.ack_at.isnot(None), LetterRecipient.id.desc()).limit(300).all())
    return templates.TemplateResponse("my_letters.html", {
        "request": request, "rows": rows, "linked": bool(pid),
        "pending": sum(1 for x in rows if not x.ack_at),
        "my_email": (me.email or "") if me else "", "email_msg": email,
    })


@router.get("/me/letters/{rcid}", response_class=HTMLResponse)
def my_letter(rcid: int, request: Request, db: Session = Depends(get_db)):
    rc = _my_rc(db, request, rcid)
    if not rc:
        return RedirectResponse("/me/letters", status_code=303)
    return templates.TemplateResponse("my_letter.html", {"request": request, "rc": rc, "r": rc.letter})


@router.post("/me/letters/{rcid}/ack")
def my_letter_ack(rcid: int, request: Request, db: Session = Depends(get_db)):
    rc = _my_rc(db, request, rcid)
    if rc and not rc.ack_at:
        rc.ack_at, rc.ack_by = datetime.now(), ""
        db.commit()
    return RedirectResponse(f"/me/letters/{rcid}" if rc else "/me/letters", status_code=303)


@router.get("/me/letters/{rcid}/file")
def my_letter_file(rcid: int, request: Request, db: Session = Depends(get_db)):
    rc = _my_rc(db, request, rcid)
    if not rc or not rc.letter.file_path:
        return RedirectResponse("/me/letters", status_code=303)
    return serve_uploaded(rc.letter.file_path)


# ---------------- ทะเบียนหนังสือส่ง ----------------
@router.get("/admin/outgoing", response_class=HTMLResponse)
def outgoing_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    rows = (db.query(OutgoingLetter).filter_by(fiscal_year=fy)
            .order_by(OutgoingLetter.send_seq).all())
    years = fiscal_year_options(
        [r[0] for r in db.query(OutgoingLetter.fiscal_year).distinct()], fy)
    school = get_school(db)
    seq = suggest_next(db, "outgoing", fy)
    sug_no = f"{school.doc_prefix or 'ศธ'} {seq}/{doc_year('outgoing', fy)}"
    return templates.TemplateResponse("outgoing.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "years": years, "sug_no": sug_no,
    })


@router.post("/admin/outgoing")
def outgoing_add(db: Session = Depends(get_db), fiscal_year: int = Form(...),
                 send_no: str = Form(""), date: str = Form(""), to_org: str = Form(""),
                 subject: str = Form(""), pending_file: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    m = re.search(r"(\d+)", send_no or "")     # เลขลำดับ = กลุ่มตัวเลขแรก (ข้ามอักษรนำ ศธ)
    seq = (int(m.group(1)) if m else 0) or suggest_next(db, "outgoing", fy)
    fp = pending_file.strip() if _SAFE_FILE_NAME.match(pending_file.strip()) else ""
    db.add(OutgoingLetter(
        fiscal_year=fy, send_seq=seq, send_no=send_no.strip(),
        date=parse_be_date(date), to_org=to_org.strip(), subject=subject.strip(), file_path=fp,
    ))
    commit_number(db, "outgoing", fy, seq)
    db.commit()
    return RedirectResponse("/admin/outgoing", status_code=303)


@router.post("/admin/outgoing/upload")
async def outgoing_upload(request: Request, db: Session = Depends(get_db),
                          file: UploadFile = File(...), ai: str = Form("")):
    data = await file.read()
    ext = _detect_ext(data, file.filename or "")
    if not ext:
        return RedirectResponse("/admin/outgoing?err=notpdf", status_code=303)
    return _read_and_confirm(request, db, "outgoing", data, ext, use_ai=bool(ai))


@router.post("/admin/outgoing/fetch")
async def outgoing_fetch(request: Request, db: Session = Depends(get_db), url: str = Form("")):
    data, ext, err = _fetch_file(url)
    if err:
        return RedirectResponse(f"/admin/outgoing?err={err}", status_code=303)
    name = _save_upload(data, ext)
    fields = extract_letter_fields(str(_uploads_dir() / name))
    return _render_letter_confirm(request, db, "outgoing", name, fields)


# ---------------- เสิร์ฟไฟล์ PDF/Word ที่อัปโหลด/แนบ ----------------
@router.get("/admin/uploaded/{name}")
def serve_uploaded(name: str):
    if not _SAFE_FILE_NAME.match(name):     # กัน path traversal (รับ .pdf/.docx)
        return RedirectResponse("/admin", status_code=303)
    path = _uploads_dir() / name
    if not path.exists():
        return RedirectResponse("/admin", status_code=303)
    low = name.lower()
    if low.endswith(".pdf"):
        # PDF: inline ให้แสดงใน iframe/แท็บ ไม่บังคับดาวน์โหลด
        return FileResponse(str(path), media_type=_PDF, content_disposition_type="inline")
    img_mt = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
    for ext, mt in img_mt.items():
        if low.endswith(ext):                # รูป: inline ใช้พรีวิวเกียรติบัตร
            return FileResponse(str(path), media_type=mt, content_disposition_type="inline")
    # Word: ให้เปิด/ดาวน์โหลด (เบราว์เซอร์เปิด docx ใน iframe ไม่ได้)
    return FileResponse(str(path), media_type=_DOCX, filename=name)


@router.post("/admin/outgoing/{rid}/delete")
def outgoing_delete(rid: int, db: Session = Depends(get_db)):
    r = db.get(OutgoingLetter, rid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/admin/outgoing", status_code=303)


# ---------------- บันทึกข้อความ ----------------
_SOURCE_LABEL = {"procurement": "พัสดุ", "finance": "การเงิน", "lunch": "อาหารกลางวัน"}


def _external_issued(db: Session, doc_type: str):
    """เลขในทะเบียนกลางที่ออกโดยงานอื่น (ไม่ใช่ธุรการ) - โชว์อ่านอย่างเดียว + ลิงก์ดูต้นทาง
    เพื่อให้หน้าธุรการเห็นเลขทั้งหมดของประเภทนั้น ไม่ใช่แค่ที่ธุรการสร้างเอง"""
    rows = (db.query(IssuedDocNo)
            .filter(IssuedDocNo.doc_type == doc_type,
                    IssuedDocNo.source.isnot(None), IssuedDocNo.source != "",
                    IssuedDocNo.source != "admin")
            .order_by(IssuedDocNo.fiscal_year.desc(), IssuedDocNo.seq.desc()).all())
    def _href(r):
        if r.ref_id and r.source == "procurement":
            return f"/procurement/{r.ref_id}"
        if r.ref_id and r.source == "finance":
            return f"/finance/disburse/{r.ref_id}"
        return ""
    return [{"full_no": r.full_no, "subject": r.subject or "", "date": r.date,
             "source": r.source, "source_label": _SOURCE_LABEL.get(r.source, r.source),
             "href": _href(r)} for r in rows]


@router.get("/admin/memos", response_class=HTMLResponse)
def memos_page(request: Request, db: Session = Depends(get_db)):
    fy = current_fiscal_year()
    rows = db.query(OfficeMemo).order_by(OfficeMemo.id.desc()).all()
    school = get_school(db)
    return templates.TemplateResponse("memos.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "school": school,
        "sug_memo": suggest_doc_no(db, "memo", fy),
        "external": _external_issued(db, "memo"),
        "persons": db.query(Person).order_by(Person.name).all(),
        "departments": db.query(Department).order_by(Department.name).all(),
    })


@router.post("/admin/memos")
def memo_create(db: Session = Depends(get_db), fiscal_year: str = Form(""), memo_no: str = Form(""),
                date: str = Form(""), from_dept: str = Form(""), to_person: str = Form(""),
                subject: str = Form(""), body: str = Form(""),
                signer_name: str = Form(""), signer_position: str = Form(""),
                pending_file: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    no = memo_no.strip() or suggest_doc_no(db, "memo", fy)
    from app.services.doc_number import parse_seq
    fp = pending_file.strip() if _SAFE_FILE_NAME.match(pending_file.strip()) else ""
    m = OfficeMemo(fiscal_year=fy, memo_no=no, seq=parse_seq(no), date=parse_be_date(date),
                   from_dept=from_dept.strip(), to_person=to_person.strip(),
                   subject=subject.strip(), body=body, signer_name=signer_name.strip(),
                   signer_position=signer_position.strip(), file_path=fp)
    db.add(m); db.flush()
    commit_doc_no(db, "memo", fy, no, source="admin", ref_id=m.id, subject=m.subject, date=m.date)
    db.commit(); db.refresh(m)
    return RedirectResponse(f"/admin/memos/{m.id}", status_code=303)


@router.post("/admin/memos/upload")
async def memo_upload(request: Request, db: Session = Depends(get_db),
                      file: UploadFile = File(...), ai: str = Form("")):
    data = await file.read()
    ext = _detect_ext(data, file.filename or "")
    if not ext:
        return RedirectResponse("/admin/memos?err=notpdf", status_code=303)
    return _read_and_confirm(request, db, "memo", data, ext, use_ai=bool(ai))


@router.post("/admin/memos/fetch")
async def memo_fetch(request: Request, db: Session = Depends(get_db), url: str = Form("")):
    data, ext, err = _fetch_file(url)
    if err:
        return RedirectResponse(f"/admin/memos?err={err}", status_code=303)
    name = _save_upload(data, ext)
    fields = extract_letter_fields(str(_uploads_dir() / name))
    return _render_letter_confirm(request, db, "memo", name, fields)


@router.get("/admin/memos/{mid}", response_class=HTMLResponse)
def memo_detail(mid: int, request: Request, db: Session = Depends(get_db)):
    m = db.get(OfficeMemo, mid)
    if not m:
        return RedirectResponse("/admin/memos", status_code=303)
    return templates.TemplateResponse("memo_detail.html", {
        "request": request, "m": m, "school": get_school(db),
        "persons": db.query(Person).order_by(Person.name).all(),
        "departments": db.query(Department).order_by(Department.name).all(),
    })


@router.post("/admin/memos/{mid}/update")
def memo_update(mid: int, db: Session = Depends(get_db), memo_no: str = Form(""),
                date: str = Form(""), from_dept: str = Form(""), to_person: str = Form(""),
                subject: str = Form(""), body: str = Form(""),
                signer_name: str = Form(""), signer_position: str = Form("")):
    m = db.get(OfficeMemo, mid)
    if m:
        from app.services.doc_number import parse_seq
        m.memo_no = memo_no.strip(); m.seq = parse_seq(memo_no)
        m.date = parse_be_date(date); m.from_dept = from_dept.strip()
        m.to_person = to_person.strip(); m.subject = subject.strip(); m.body = body
        m.signer_name = signer_name.strip(); m.signer_position = signer_position.strip()
        remove_issued(db, "admin", m.id, "memo")   # ล้างเลขเก่า (กันค้างเมื่อเปลี่ยนเลข)
        commit_doc_no(db, "memo", m.fiscal_year, m.memo_no, source="admin", ref_id=m.id, subject=m.subject, date=m.date)
        db.commit()
    return RedirectResponse(f"/admin/memos/{mid}?saved=1", status_code=303)


@router.post("/admin/memos/{mid}/delete")
def memo_delete(mid: int, db: Session = Depends(get_db)):
    m = db.get(OfficeMemo, mid)
    if m:
        remove_issued(db, "admin", m.id, "memo")   # ลบเลขในทะเบียนกลางให้ตรงกัน
        db.delete(m); db.commit()
    return RedirectResponse("/admin/memos", status_code=303)


@router.get("/admin/memos/{mid}/generate")
def memo_generate(mid: int, db: Session = Depends(get_db)):
    m = db.get(OfficeMemo, mid)
    if not m:
        return RedirectResponse("/admin/memos", status_code=303)
    path = render_memo(m, get_school(db))
    return serve_generated(path, _DOCX)


# ---------------- คำสั่งโรงเรียน ----------------
@router.get("/admin/orders", response_class=HTMLResponse)
def orders_page(request: Request, db: Session = Depends(get_db)):
    fy = current_fiscal_year()
    rows = db.query(SchoolOrder).order_by(SchoolOrder.id.desc()).all()
    return templates.TemplateResponse("orders.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "school": get_school(db),
        "sug_order": suggest_doc_no(db, "command", fy),
        "external": _external_issued(db, "command"),
    })


@router.post("/admin/orders")
def order_create(db: Session = Depends(get_db), fiscal_year: str = Form(""), order_no: str = Form(""),
                 date: str = Form(""), subject: str = Form(""), body: str = Form(""),
                 pending_file: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    no = order_no.strip() or suggest_doc_no(db, "command", fy)
    from app.services.doc_number import parse_seq
    fp = pending_file.strip() if _SAFE_FILE_NAME.match(pending_file.strip()) else ""
    o = SchoolOrder(fiscal_year=fy, order_no=no, seq=parse_seq(no), date=parse_be_date(date),
                    subject=subject.strip(), body=body, file_path=fp)
    db.add(o); db.flush()
    commit_doc_no(db, "command", fy, no, source="admin", ref_id=o.id, subject=o.subject, date=o.date)
    db.commit(); db.refresh(o)
    return RedirectResponse(f"/admin/orders/{o.id}", status_code=303)


@router.post("/admin/orders/upload")
async def order_upload(request: Request, db: Session = Depends(get_db),
                       file: UploadFile = File(...), ai: str = Form("")):
    data = await file.read()
    ext = _detect_ext(data, file.filename or "")
    if not ext:
        return RedirectResponse("/admin/orders?err=notpdf", status_code=303)
    return _read_and_confirm(request, db, "order", data, ext, use_ai=bool(ai))


@router.post("/admin/orders/fetch")
async def order_fetch(request: Request, db: Session = Depends(get_db), url: str = Form("")):
    data, ext, err = _fetch_file(url)
    if err:
        return RedirectResponse(f"/admin/orders?err={err}", status_code=303)
    name = _save_upload(data, ext)
    fields = extract_letter_fields(str(_uploads_dir() / name))
    return _render_letter_confirm(request, db, "order", name, fields)


@router.get("/admin/orders/{oid}", response_class=HTMLResponse)
def order_detail(oid: int, request: Request, db: Session = Depends(get_db)):
    o = db.get(SchoolOrder, oid)
    if not o:
        return RedirectResponse("/admin/orders", status_code=303)
    return templates.TemplateResponse("order_detail.html", {
        "request": request, "o": o, "school": get_school(db),
    })


@router.post("/admin/orders/{oid}/update")
def order_update(oid: int, db: Session = Depends(get_db), order_no: str = Form(""),
                 date: str = Form(""), subject: str = Form(""), body: str = Form("")):
    o = db.get(SchoolOrder, oid)
    if o:
        from app.services.doc_number import parse_seq
        o.order_no = order_no.strip(); o.seq = parse_seq(order_no)
        o.date = parse_be_date(date); o.subject = subject.strip(); o.body = body
        remove_issued(db, "admin", o.id, "command")   # ล้างเลขเก่า (กันค้างเมื่อเปลี่ยนเลข)
        commit_doc_no(db, "command", o.fiscal_year, o.order_no, source="admin", ref_id=o.id, subject=o.subject, date=o.date)
        db.commit()
    return RedirectResponse(f"/admin/orders/{oid}?saved=1", status_code=303)


@router.post("/admin/orders/{oid}/delete")
def order_delete(oid: int, db: Session = Depends(get_db)):
    o = db.get(SchoolOrder, oid)
    if o:
        remove_issued(db, "admin", o.id, "command")   # ลบเลขคำสั่งในทะเบียนกลางให้ตรงกัน
        db.delete(o); db.commit()
    return RedirectResponse("/admin/orders", status_code=303)


@router.get("/admin/orders/{oid}/generate")
def order_generate(oid: int, db: Session = Depends(get_db)):
    o = db.get(SchoolOrder, oid)
    if not o:
        return RedirectResponse("/admin/orders", status_code=303)
    path = render_order(o, get_school(db))
    return serve_generated(path, _DOCX)


# ---------------- นำเข้า Excel (ทะเบียนหนังสือรับ/ส่ง) ----------------
@router.get("/admin/import", response_class=HTMLResponse)
def admin_import_page(request: Request, db: Session = Depends(get_db),
                      imported: str | None = None, import_err: str | None = None):
    lines = []
    if imported and imported != "none":
        for part in imported.split(","):
            if ":" in part:
                sheet, n = part.split(":", 1)
                lines.append(f"{sheet}: เพิ่ม {n} รายการ")
    err = {"type": "ไฟล์ต้องเป็น .xlsx เท่านั้น",
           "read": "อ่านไฟล์ไม่สำเร็จ ตรวจสอบว่าใช้เทมเพลตที่ถูกต้อง"}.get(import_err)
    return templates.TemplateResponse("admin_import.html", {
        "request": request, "import_lines": lines, "import_err": err,
    })


@router.get("/admin/letters/export.xlsx")
def admin_letters_export(db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    incoming = (db.query(IncomingLetter).filter_by(fiscal_year=fy)
                .order_by(IncomingLetter.recv_no).all())
    outgoing = (db.query(OutgoingLetter).filter_by(fiscal_year=fy)
                .order_by(OutgoingLetter.send_seq).all())
    path = export_admin_register(incoming, outgoing, fy)
    return serve_generated(path, _XLSX)


@router.get("/admin/template.xlsx")
def admin_template():
    path = build_admin_template()
    return serve_generated(path, _XLSX)


@router.post("/admin/import")
async def admin_import(db: Session = Depends(get_db), file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return RedirectResponse("/admin/import?import_err=type", status_code=303)
    content = await file.read()
    try:
        summary = import_admin_workbook(content, db)
    except Exception:
        return RedirectResponse("/admin/import?import_err=read", status_code=303)
    q = ",".join(f"{k}:{v}" for k, v in summary.items()) or "none"
    return RedirectResponse(f"/admin/import?imported={q}", status_code=303)


# ============================================================
# หนังสือราชการภายนอก (แม่แบบสำเร็จ + ออก Word)
# ============================================================
# แม่แบบสำเร็จ: key -> (label, เรื่อง, โครงร่างเนื้อความ)  ("…" = เว้นให้เติม)
LETTER_PRESETS = {
    "blank": ("ฟอร์มเปล่า", "", ""),
    "invite_meeting": ("เชิญประชุม", "ขอเชิญประชุม………………………",
        "ด้วย…………………………… กำหนดจัดประชุม…………………… ในวันที่…………… เวลา………… น. "
        "ณ…………………………………\n\nในการนี้ จึงขอเรียนเชิญท่านเข้าร่วมประชุมตามวัน เวลา และสถานที่ดังกล่าว "
        "จะเป็นพระคุณยิ่ง"),
    "invite_speaker": ("เชิญเป็นวิทยากร", "ขอเชิญเป็นวิทยากร",
        "ด้วย…………………………… กำหนดจัด…………………… ในวันที่…………… ณ……………………………\n\n"
        "ในการนี้ เห็นว่าท่านเป็นผู้มีความรู้ความสามารถ จึงขอเรียนเชิญท่านเป็นวิทยากรในหัวข้อ"
        "…………………………… จะเป็นพระคุณยิ่ง"),
    "ask_permission": ("ขออนุญาต", "ขออนุญาต……………………",
        "ด้วย…………………………… มีความประสงค์ขออนุญาต…………………… เนื่องด้วย……………………………\n\n"
        "จึงเรียนมาเพื่อโปรดพิจารณาอนุญาต"),
    "ask_support": ("ขอความอนุเคราะห์", "ขอความอนุเคราะห์……………………",
        "ด้วย…………………………… จึงใคร่ขอความอนุเคราะห์…………………… จากท่าน เพื่อ……………………………\n\n"
        "จึงเรียนมาเพื่อโปรดพิจารณาให้ความอนุเคราะห์"),
    "thanks": ("ขอบคุณ", "ขอขอบคุณ……………………",
        "ตามที่ท่านได้……………………………… นั้น\n\n…………………………… ขอขอบคุณในความอนุเคราะห์ของท่านมา ณ "
        "โอกาสนี้ และหวังเป็นอย่างยิ่งว่าจะได้รับความอนุเคราะห์จากท่านในโอกาสต่อไป"),
    "send_person": ("ส่งตัว", "ส่งตัว……………………",
        "ตามที่…………………………… นั้น\n\n…………………………… ขอส่งตัว…………………… เพื่อ……………………………"),
}


def _letter_ctx(db, extra=None):
    school = get_school(db)
    fy = current_fiscal_year()
    ctx = {
        "school": school, "fiscal_year": fy,
        "sug_no": suggest_doc_no(db, "outgoing", fy),
        "presets": LETTER_PRESETS,
        "persons": db.query(Person).order_by(Person.name).all(),
        "today_input": be_date_input(datetime.now()),
    }
    if extra:
        ctx.update(extra)
    return ctx


@router.get("/admin/letters", response_class=HTMLResponse)
def letters_page(request: Request, db: Session = Depends(get_db)):
    rows = db.query(OfficialLetter).order_by(OfficialLetter.id.desc()).all()
    return templates.TemplateResponse("official_letters.html",
                                      _letter_ctx(db, {"request": request, "rows": rows}))


@router.post("/admin/letters")
def letter_create(db: Session = Depends(get_db), fiscal_year: str = Form(""), doc_no: str = Form(""),
                  date: str = Form(""), subject: str = Form(""), to: str = Form(""),
                  ref: str = Form(""), enclosure: str = Form(""), body: str = Form(""),
                  closing: str = Form("ขอแสดงความนับถือ"), signer_name: str = Form(""),
                  signer_position: str = Form(""), preset: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    no = doc_no.strip() or suggest_doc_no(db, "outgoing", fy)
    lt = OfficialLetter(fiscal_year=fy, doc_no=no, seq=parse_seq(no), date=parse_be_date(date),
                        subject=subject.strip(), to=to.strip(), ref=ref.strip(),
                        enclosure=enclosure.strip(), body=body,
                        closing=closing.strip() or "ขอแสดงความนับถือ",
                        signer_name=signer_name.strip(), signer_position=signer_position.strip(),
                        preset=preset.strip())
    db.add(lt); db.flush()
    commit_doc_no(db, "outgoing", fy, no, source="admin", ref_id=lt.id, subject=lt.subject, date=lt.date)
    db.commit(); db.refresh(lt)
    return RedirectResponse(f"/admin/letters/{lt.id}", status_code=303)


@router.post("/admin/letters/ai-write")
def letter_ai_write(db: Session = Depends(get_db), subject: str = Form(""),
                    to: str = Form(""), points: str = Form(""), detail: str = Form("")):
    """ให้ AI ร่างเนื้อความหนังสือราชการจากข้อมูลสำคัญ -> คืน JSON {subject, body}"""
    from fastapi.responses import JSONResponse
    from app.services.ai_extract import write_official_letter
    school = get_school(db)
    key = _ai_key()
    if not key:
        return JSONResponse({"error": "ฟีเจอร์ AI สำหรับสมาชิกเท่านั้น - ต่ออายุ/เป็นสมาชิกเพื่อใช้งาน"}, status_code=400)
    res = write_official_letter({
        "school": school.name or "", "subject": subject, "to": to,
        "points": points, "detail": detail,
    }, key)
    if res.get("error"):
        return JSONResponse({"error": "AI เขียนไม่สำเร็จ" + (" สาเหตุ: " + res["detail"] if res.get("detail") else " ลองใหม่อีกครั้ง")}, status_code=502)
    return JSONResponse({"subject": res.get("subject", ""), "body": res.get("body", "")})


@router.post("/admin/memos/ai-write")
def memo_ai_write(db: Session = Depends(get_db), subject: str = Form(""),
                  from_dept: str = Form(""), to: str = Form(""), points: str = Form("")):
    """ให้ AI ร่างบันทึกข้อความ -> คืน JSON {subject, body}"""
    from fastapi.responses import JSONResponse
    from app.services.ai_extract import write_memo
    school = get_school(db)
    key = _ai_key()
    if not key:
        return JSONResponse({"error": "ฟีเจอร์ AI สำหรับสมาชิกเท่านั้น - ต่ออายุ/เป็นสมาชิกเพื่อใช้งาน"}, status_code=400)
    res = write_memo({"school": school.name or "", "subject": subject,
                      "from_dept": from_dept, "to": to, "points": points}, key)
    if res.get("error"):
        return JSONResponse({"error": "AI เขียนไม่สำเร็จ" + (" สาเหตุ: " + res["detail"] if res.get("detail") else " ลองใหม่อีกครั้ง")}, status_code=502)
    return JSONResponse({"subject": res.get("subject", ""), "body": res.get("body", "")})


@router.post("/admin/orders/ai-write")
def order_ai_write(db: Session = Depends(get_db), subject: str = Form(""), points: str = Form("")):
    """ให้ AI ร่างคำสั่งโรงเรียน -> คืน JSON {subject, body}"""
    from fastapi.responses import JSONResponse
    from app.services.ai_extract import write_order
    school = get_school(db)
    key = _ai_key()
    if not key:
        return JSONResponse({"error": "ฟีเจอร์ AI สำหรับสมาชิกเท่านั้น - ต่ออายุ/เป็นสมาชิกเพื่อใช้งาน"}, status_code=400)
    res = write_order({"school": school.name or "", "subject": subject, "points": points}, key)
    if res.get("error"):
        return JSONResponse({"error": "AI เขียนไม่สำเร็จ" + (" สาเหตุ: " + res["detail"] if res.get("detail") else " ลองใหม่อีกครั้ง")}, status_code=502)
    return JSONResponse({"subject": res.get("subject", ""), "body": res.get("body", "")})


@router.get("/admin/letters/{lid}", response_class=HTMLResponse)
def letter_detail(lid: int, request: Request, db: Session = Depends(get_db)):
    lt = db.get(OfficialLetter, lid)
    if not lt:
        return RedirectResponse("/admin/letters", status_code=303)
    return templates.TemplateResponse("official_letter_detail.html",
                                      _letter_ctx(db, {"request": request, "lt": lt}))


@router.post("/admin/letters/{lid}/update")
def letter_update(lid: int, db: Session = Depends(get_db), doc_no: str = Form(""),
                  date: str = Form(""), subject: str = Form(""), to: str = Form(""),
                  ref: str = Form(""), enclosure: str = Form(""), body: str = Form(""),
                  closing: str = Form("ขอแสดงความนับถือ"), signer_name: str = Form(""),
                  signer_position: str = Form("")):
    lt = db.get(OfficialLetter, lid)
    if lt:
        lt.doc_no = doc_no.strip(); lt.seq = parse_seq(doc_no)
        lt.date = parse_be_date(date); lt.subject = subject.strip(); lt.to = to.strip()
        lt.ref = ref.strip(); lt.enclosure = enclosure.strip(); lt.body = body
        lt.closing = closing.strip() or "ขอแสดงความนับถือ"
        lt.signer_name = signer_name.strip(); lt.signer_position = signer_position.strip()
        remove_issued(db, "admin", lt.id, "outgoing")   # ล้างเลขเก่า (กันค้างเมื่อเปลี่ยนเลข)
        commit_doc_no(db, "outgoing", lt.fiscal_year, lt.doc_no, source="admin",
                      ref_id=lt.id, subject=lt.subject, date=lt.date)
        db.commit()
    return RedirectResponse(f"/admin/letters/{lid}?saved=1", status_code=303)


@router.post("/admin/letters/{lid}/delete")
def letter_delete(lid: int, db: Session = Depends(get_db)):
    lt = db.get(OfficialLetter, lid)
    if lt:
        remove_issued(db, "admin", lt.id, "outgoing")   # ลบเลขหนังสือส่งในทะเบียนกลางให้ตรงกัน
        db.delete(lt); db.commit()
    return RedirectResponse("/admin/letters", status_code=303)


@router.get("/admin/letters/{lid}/generate")
def letter_generate(lid: int, db: Session = Depends(get_db)):
    lt = db.get(OfficialLetter, lid)
    if not lt:
        return RedirectResponse("/admin/letters", status_code=303)
    path = render_official_letter(lt, get_school(db))
    return serve_generated(path, _DOCX)


# ============================================================
# เกียรติบัตร (อัปโหลดพื้นหลัง + พิมพ์ชื่อทับ -> PDF หลายหน้า)
# ============================================================
from fastapi.responses import JSONResponse


@router.get("/admin/certificates", response_class=HTMLResponse)
def certificates_page(request: Request, db: Session = Depends(get_db)):
    batches = db.query(CertificateBatch).order_by(CertificateBatch.id.desc()).all()
    saved = [{
        "id": b.id, "title": b.title or f"ชุดที่ {b.id}", "bg_image": b.bg_image or "",
        "url": f"/admin/uploaded/{b.bg_image}" if b.bg_image else "",
        "name_x": b.name_x, "name_y": b.name_y, "name_size": b.name_size,
        "name_color": b.name_color or "#1a1a1a", "sub_text": b.sub_text or "",
        "cert_no_on": bool(getattr(b, "cert_no_on", 0)), "cert_no_prefix": getattr(b, "cert_no_prefix", "") or "",
        "cert_no_x": getattr(b, "cert_no_x", 50.0), "cert_no_y": getattr(b, "cert_no_y", 85.0),
        "cert_no_size": getattr(b, "cert_no_size", 26),
    } for b in batches if b.bg_image]
    # รายชื่อนักเรียนจากทะเบียนกลาง จัดกลุ่มตามชั้น/ห้อง (เรียงตามลำดับชั้นมาตรฐาน) ให้เลือกในหน้าเกียรติบัตร
    def _lvl_key(s):
        lv = (s.level or "").strip()
        try:
            i = SCHOOL_LEVELS.index(lv)
        except ValueError:
            i = len(SCHOOL_LEVELS) + 1
        return (i, lv, (s.room or "").strip())
    groups, order = {}, []
    for s in sorted(db.query(Student).all(), key=_lvl_key):
        if not (s.name or "").strip():
            continue
        lv, rm = (s.level or "").strip(), (s.room or "").strip()
        label = (lv + ("/" + rm if rm else "")) if lv else "ไม่ระบุชั้น"
        if label not in groups:
            groups[label] = []; order.append(label)
        groups[label].append(s.name.strip())
    class_list = [{"label": lbl, "names": groups[lbl]} for lbl in order]
    return templates.TemplateResponse("certificates.html", {
        "request": request, "school": get_school(db), "saved": saved,
        "class_list": class_list,
    })


@router.post("/admin/certificates/{bid}/delete")
def certificate_delete(bid: int, db: Session = Depends(get_db)):
    """ลบชุดเกียรติบัตรที่บันทึกไว้"""
    b = db.get(CertificateBatch, bid)
    if b:
        db.delete(b); db.commit()
    return RedirectResponse("/admin/certificates", status_code=303)


@router.post("/admin/certificates/bg")
async def certificate_bg(file: UploadFile = File(...)):
    """อัปโหลดรูปพื้นหลังเกียรติบัตร -> คืนชื่อไฟล์ + ขนาด (สำหรับพรีวิว/ปักตำแหน่ง)"""
    data = await file.read()
    ext = file_upload.detect_ext(data, file.filename or "")
    if ext not in ("png", "jpg", "webp"):
        return JSONResponse({"error": "ไฟล์ต้องเป็นรูปภาพ (png/jpg/webp)"})
    name = file_upload.save_upload(data, ext)
    try:
        from PIL import Image
        import io
        w, h = Image.open(io.BytesIO(data)).size
    except Exception:
        w = h = 0
    return JSONResponse({"file": name, "w": w, "h": h, "url": f"/admin/uploaded/{name}"})


@router.post("/admin/certificates/names-excel")
async def certificate_names_excel(file: UploadFile = File(...)):
    """อ่านรายชื่อจาก Excel (คอลัมน์แรก) -> คืนเป็นรายการ"""
    if not (file.filename or "").lower().endswith(".xlsx"):
        return JSONResponse({"error": "ไฟล์ต้องเป็น .xlsx"})
    data = await file.read()
    try:
        from openpyxl import load_workbook
        import io
        wb = load_workbook(io.BytesIO(data), data_only=True)
        ws = wb.active
        names = []
        for row in ws.iter_rows(values_only=True):
            if row and row[0] is not None:
                v = str(row[0]).strip()
                if v and v not in ("ชื่อ", "ชื่อ-นามสกุล", "รายชื่อ", "ลำดับ"):
                    names.append(v)
    except Exception:
        return JSONResponse({"error": "อ่านไฟล์ Excel ไม่สำเร็จ"})
    return JSONResponse({"names": names})


@router.post("/admin/certificates")
def certificate_generate(db: Session = Depends(get_db), title: str = Form(""),
                         sub_text: str = Form(""), bg_image: str = Form(""),
                         name_x: str = Form("50"), name_y: str = Form("45"),
                         name_size: str = Form("48"), name_color: str = Form("#1a1a1a"),
                         cert_no_on: str = Form(""), cert_no_prefix: str = Form(""),
                         cert_no_x: str = Form("50"), cert_no_y: str = Form("85"),
                         cert_no_size: str = Form("26"), names: str = Form("")):
    from app.services.cert_doc import render_certificates
    name_list = [n.strip() for n in (names or "").splitlines() if n.strip()]
    if not bg_image.strip() or not name_list:
        return RedirectResponse("/admin/certificates?err=1", status_code=303)
    use_no = cert_no_on in ("1", "on", "true")
    batch = CertificateBatch(
        title=title.strip(), sub_text=sub_text.strip(), bg_image=bg_image.strip(),
        name_x=_to_float(name_x, 50.0), name_y=_to_float(name_y, 45.0),
        name_size=_to_int(name_size, 48), name_color=name_color.strip() or "#1a1a1a",
        cert_no_on=1 if use_no else 0, cert_no_prefix=(cert_no_prefix or "").strip(),
        cert_no_x=_to_float(cert_no_x, 50.0), cert_no_y=_to_float(cert_no_y, 85.0),
        cert_no_size=_to_int(cert_no_size, 26),
        names="\n".join(name_list))
    db.add(batch); db.commit(); db.refresh(batch)
    # เลขที่เกียรติบัตร: รันต่อเนื่องต่อโรงเรียน/ปี (ใช้ตัวนับเดียวกับเลขหนังสือ doc_type=certificate)
    numbers = None
    if use_no:
        be_year = datetime.now().year + 543
        start = suggest_next(db, "certificate", be_year)
        prefix = (cert_no_prefix or "").strip()
        numbers = [f"{prefix}{start + i:04d}/{be_year}" for i in range(len(name_list))]
        commit_number(db, "certificate", be_year, start + len(name_list) - 1)
    path = render_certificates(batch, name_list, get_school(db), numbers=numbers)
    return serve_generated(path, _PDF)
