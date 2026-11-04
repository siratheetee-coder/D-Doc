# -*- coding: utf-8 -*-
"""ส่งเรื่องพัสดุ/การเงินให้ ผอ. อนุมัติ (services/approval.py)

ผู้ส่ง   POST /procurement/{pid}/approval  และ  POST /finance/approval   (อยู่ใต้ path ของงาน สิทธิ์งานเดิมคุมให้)
ผอ.     GET  /approvals/doc/{aid}           ดูเรื่อง + เปิดเอกสารฉบับที่จะลงนาม
        GET  /approvals/doc/{aid}/file      สร้างเอกสารให้ดู (GET ผอ. เปิดได้ ไม่ต้องเข้า allowlist)
        POST /approvals/doc/{aid}/decide    sign / approve / return  (อยู่ใน _DIRECTOR_WRITE_ALLOW)
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Approval, Person
from app.services import approval as ap
from app.templating import templates

router = APIRouter()
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _back(url: str, fallback: str) -> str:
    url = (url or "").strip()
    return url if url.startswith("/") and not url.startswith("//") else fallback


def _with(url: str, key: str, msg: str) -> str:
    base, _, frag = url.partition("#")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{key}={quote(msg)}" + (f"#{frag}" if frag else "")


def _notify_directors(db, a):
    try:
        from app.routers.hr import _notify_directors as notify
        spec = ap.KINDS[a.kind]
        notify(db, f"รออนุมัติ: {spec['label']}", f"{a.title} {a.amount:,.2f} บาท จาก {a.sent_by}",
               link=f"/approvals/doc/{a.id}")
    except Exception:
        pass


def _send_or_cancel(request, db, kind, ref_id, action, note, back):
    if not ap.enabled(db):
        return RedirectResponse(_with(back, "err", "ยังไม่ได้เปิดการส่ง ผอ. อนุมัติ (ไอดีหลักเปิดที่หน้าตั้งค่าโรงเรียน)"), 303)
    try:
        if action == "cancel":
            ap.cancel(db, kind, ref_id)
            db.commit()
            return RedirectResponse(_with(back, "msg", "ยกเลิกการส่ง ผอ. แล้ว"), 303)
        a = ap.send(db, kind, ref_id, request.session.get("name") or "", note,
                    by_pid=request.session.get("person_id"))
        db.flush()
        _notify_directors(db, a)
        db.commit()
    except ValueError as e:
        db.rollback()
        return RedirectResponse(_with(back, "err", str(e)), 303)
    return RedirectResponse(_with(back, "msg", "ส่ง ผอ. อนุมัติแล้ว"), 303)


@router.post("/procurement/{pid}/approval")
def proc_approval(pid: int, request: Request, db: Session = Depends(get_db), kind: str = Form(""),
                  action: str = Form("send"), note: str = Form(""), back: str = Form("")):
    if kind not in ap.PROC_STAGES:
        return RedirectResponse(f"/procurement/{pid}", 303)
    return _send_or_cancel(request, db, kind, pid, action, note,
                           _back(back, f"/procurement/{pid}") + "#approval")


@router.post("/finance/approval")
def finance_approval(request: Request, db: Session = Depends(get_db), kind: str = Form(""),
                     ref_id: int = Form(0), action: str = Form("send"), note: str = Form(""),
                     back: str = Form("")):
    if kind not in ("disburse", "loan"):
        return RedirectResponse("/finance", 303)
    return _send_or_cancel(request, db, kind, ref_id, action, note,
                           _back(back, ap.KINDS[kind]["link"](ref_id)))


# ---------------------------------------------------------------- ฝั่ง ผอ.
def _is_director(request) -> bool:
    from app.routers.pages import _is_director as isd
    return isd(request)


def _docs_of(db, a) -> list:
    """เอกสารของขั้นนี้ที่เรื่องนี้ออกได้จริง"""
    spec = ap.KINDS[a.kind]
    if a.kind in ap.PROC_STAGES:
        from app.services.render import doc_label, kinds_for
        obj = spec["get"](db, a.ref_id)
        if obj is None:
            return []
        have = set(kinds_for(obj))
        return [(d, doc_label(d, obj.proc_type)) for d in spec["docs"] if d in have]
    return [(d, d) for d in spec["docs"]]


def _director_sig_ok(db, request) -> bool:
    from app.models import School
    from app.services.signature import signature_full_path, signature_path_for
    pid = request.session.get("person_id")
    p = db.get(Person, pid) if pid else None
    if p and (p.signature or "").strip() and signature_full_path(p.signature):
        return True
    s = db.query(School).first()
    return bool(signature_path_for(db, (request.session.get("name") or "").strip())
                or (s and signature_path_for(db, s.director_name or "")))


@router.get("/approvals/doc/{aid}", response_class=HTMLResponse)
def approval_detail(aid: int, request: Request, db: Session = Depends(get_db), msg: str = "", err: str = ""):
    a = db.get(Approval, aid)
    if not a or a.kind not in ap.KINDS:
        return RedirectResponse("/approvals", 303)
    spec = ap.KINDS[a.kind]
    obj = spec["get"](db, a.ref_id)
    st = ap.state(db, a.kind, a.ref_id, obj) if obj is not None else None
    changed = bool(obj is not None and a.status == "pending" and a.fingerprint != ap.fingerprint(a.kind, obj))
    return templates.TemplateResponse("approval_detail.html", {
        "request": request, "a": a, "spec": spec, "obj": obj, "st": st, "changed": changed,
        "docs": _docs_of(db, a), "history": ap.history(db, a.kind, a.ref_id),
        "is_director": _is_director(request), "sig_ok": _director_sig_ok(db, request),
        "link": spec["link"](a.ref_id), "msg": msg, "err": err,
    })


@router.get("/approvals/doc/{aid}/file")
def approval_file(aid: int, request: Request, db: Session = Depends(get_db), doc: str = ""):
    from app.routers.pages import serve_generated
    from app.models import School
    a = db.get(Approval, aid)
    if not a or a.kind not in ap.KINDS or doc not in dict(_docs_of(db, a)):
        return RedirectResponse(f"/approvals/doc/{aid}", 303)
    obj = ap.KINDS[a.kind]["get"](db, a.ref_id)
    school = db.query(School).first()
    if a.kind in ap.PROC_STAGES:
        from app.services.render import render_document
        path = render_document(doc, obj, school)
    elif a.kind == "disburse":
        from app.services.finance_doc import render_disburse
        path = render_disburse(obj, school)
    else:
        from app.services.finance_forms_doc import render_loan_contract
        path = render_loan_contract(school, obj)
    return serve_generated(path, _DOCX, count=False)


@router.post("/approvals/doc/{aid}/decide")
def approval_decide(aid: int, request: Request, db: Session = Depends(get_db),
                    action: str = Form(""), comment: str = Form("")):
    if not _is_director(request):
        return RedirectResponse(f"/approvals/doc/{aid}?err=" + quote("เฉพาะ ผอ./รองผอ. เท่านั้น"), 303)
    try:
        a = ap.decide(db, aid, action, request.session.get("person_id"),
                      request.session.get("name") or "", comment)
        if a.sent_pid:
            from app.services.nav import create_notice
            spec = ap.KINDS[a.kind]
            word = {"returned": "ส่งกลับให้แก้", "approved": "อนุมัติแล้ว"}.get(a.status, a.status)
            create_notice(db, a.sent_pid, f"ผอ. {word}: {spec['label']}",
                          reason=(a.comment or a.title)[:200], link=spec["link"](a.ref_id),
                          level="warn" if a.status == "returned" else "info")
        db.commit()
    except ValueError as e:
        db.rollback()
        return RedirectResponse(f"/approvals/doc/{aid}?err=" + quote(str(e)), 303)
    done = {"sign": "อนุมัติและแปะลายเซ็นแล้ว", "approve": "อนุมัติแล้ว (ไม่แปะลายเซ็น)",
            "return": "ส่งกลับให้แก้แล้ว"}[action]
    return RedirectResponse("/approvals?msg=" + quote(done) + "#docs", 303)
