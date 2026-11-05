# -*- coding: utf-8 -*-
"""ส่งเรื่องพัสดุ/การเงินให้ ผอ. อนุมัติ (services/approval.py)

ผู้ส่ง   POST /procurement/{pid}/approval  และ  POST /finance/approval   (อยู่ใต้ path ของงาน สิทธิ์งานเดิมคุมให้)
ผอ.     GET  /approvals/doc/{aid}           ดูเรื่อง + เปิดเอกสารฉบับที่จะลงนาม
        GET  /approvals/doc/{aid}/file      สร้างเอกสารให้ดู (GET ผอ. เปิดได้ ไม่ต้องเข้า allowlist)
        POST /approvals/doc/{aid}/decide    sign / approve / return  (อยู่ใน _DIRECTOR_WRITE_ALLOW)
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
        money = f" {a.amount:,.2f} บาท" if a.amount else ""
        notify(db, f"รออนุมัติ: {spec['label']}", f"{a.title}{money} จาก {a.sent_by}",
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
    if kind not in ap.PROC_STAGES and kind != "proc_alt":
        return RedirectResponse(f"/procurement/{pid}", 303)
    return _send_or_cancel(request, db, kind, pid, action, note,
                           _back(back, f"/procurement/{pid}") + "#approval")


def _generic_send(path):
    def handler(request: Request, db: Session = Depends(get_db), kind: str = Form(""),
                ref_id: int = Form(0), action: str = Form("send"), note: str = Form(""),
                back: str = Form("")):
        if kind not in ap.SEND_PATHS[path]:
            return RedirectResponse("/", 303)
        return _send_or_cancel(request, db, kind, ref_id, action, note,
                               _back(back, ap.KINDS[kind]["link"](ref_id)))
    return handler


# การเงิน (เบิกจ่าย/ยืมเงิน) ธุรการ (บันทึก/คำสั่ง/หนังสือ) โครงการ (อนุมัติโครงการ/รายงานผล)
for _path in ap.SEND_PATHS:
    router.add_api_route(_path, _generic_send(_path), methods=["POST"])


# ---------------------------------------------------------------- ฝั่ง ผอ.
def _is_director(request) -> bool:
    from app.routers.pages import _is_director as isd
    return isd(request)


def _docs_for(db, kind, ref_id) -> list:
    """เอกสารของขั้นนี้ที่เรื่องนี้ออกได้จริง [(คีย์, ชื่อ)]"""
    spec = ap.KINDS[kind]
    obj = spec["get"](db, ref_id)
    if obj is None:
        return []
    if spec.get("docs_fn"):
        return list(spec["docs_fn"](obj))
    if kind == "proc_alt":
        from app.routers.pages import _alt_label
        return [(d, _alt_label(obj, d)) for d in ap.alt_docs(obj)]
    if kind in ap.PROC_STAGES:
        from app.services.render import doc_label, kinds_for
        have = set(kinds_for(obj))
        return [(d, doc_label(d, obj.proc_type)) for d in spec["docs"] if d in have]
    return [(d, d) for d in spec["docs"]]


def _docs_of(db, a) -> list:
    return _docs_for(db, a.kind, a.ref_id)


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


def _director_name(db) -> str:
    from app.models import School
    s = db.query(School).first()
    return (s.director_name or "") if s else ""


@router.get("/approvals/doc/{aid}", response_class=HTMLResponse)
def approval_detail(aid: int, request: Request, db: Session = Depends(get_db), msg: str = "", err: str = ""):
    a = db.get(Approval, aid)
    if not a or a.kind not in ap.KINDS:
        return RedirectResponse("/approvals", 303)
    spec = ap.KINDS[a.kind]
    obj = spec["get"](db, a.ref_id)
    st = ap.state(db, a.kind, a.ref_id, obj) if obj is not None else None
    changed = bool(obj is not None and a.status == "pending" and a.fingerprint != ap.fingerprint(a.kind, obj))
    acting = _is_director(request) and a.status == "pending" and ap.is_acting(
        db, request.session.get("person_id"), _decider_name(request, db))
    return templates.TemplateResponse("approval_detail.html", {
        "acting": acting, "school_director": _director_name(db) if acting else "",
        "request": request, "a": a, "spec": spec, "obj": obj, "st": st, "changed": changed,
        "docs": _docs_of(db, a), "history": ap.history(db, a.kind, a.ref_id),
        "is_director": _is_director(request), "sig_ok": _director_sig_ok(db, request),
        "link": spec["link"](a.ref_id), "msg": msg, "err": err,
    })


def _render(db, kind, ref_id, doc) -> str:
    """สร้างไฟล์ Word ของเอกสารนี้ (แปะลายเซ็นถ้าอนุมัติแล้ว) คืน path"""
    from app.models import School
    obj = ap.KINDS[kind]["get"](db, ref_id)
    school = db.query(School).first()
    if kind == "proc_alt":
        from app.services import staff
        from app.services.proc_alt_doc import RENDERERS
        from app.services.w119_doc import RENDERERS as W119
        school = staff.school_for(obj, school)
        path = (RENDERERS.get(doc) or W119[doc])(obj, school)
        ap.stamp_current("proc_alt", obj.id, path, school.director_name or "", tick=("เห็นชอบ", "อนุมัติ"))
    elif kind in ap.PROC_STAGES:
        from app.services.render import render_document
        path = render_document(doc, obj, school)
    elif kind == "disburse":
        from app.services.finance_doc import render_disburse
        path = render_disburse(obj, school)
    elif kind == "loan":
        from app.services.finance_forms_doc import render_loan_contract
        path = render_loan_contract(school, obj)
    elif kind == "memo":
        from app.services.office_doc import render_memo
        path = render_memo(obj, school)
    elif kind == "order":
        from app.services.office_doc import render_order
        path = render_order(obj, school)
    elif kind == "letter":
        from app.services.office_doc import render_official_letter
        path = render_official_letter(obj, school)
    elif kind == "revenue":
        from app.routers.finance import revenue_stamped
        path = revenue_stamped(db, obj, doc)
    elif kind.startswith("lunch_"):
        from app.services.lunch_approval import render_stamped
        path = render_stamped(db, doc, obj, school)
    else:                                   # project_report
        from app.services.project_report_doc import render_project_report
        path = render_project_report(obj, school)
        ap.stamp_current("project_report", obj.id, path, school.director_name or "", tick=())
    return path


@router.get("/approvals/doc/{aid}/file")
def approval_file(aid: int, request: Request, db: Session = Depends(get_db), doc: str = ""):
    from app.routers.pages import serve_generated
    a = db.get(Approval, aid)
    if not a or a.kind not in ap.KINDS or doc not in dict(_docs_of(db, a)):
        return RedirectResponse(f"/approvals/doc/{aid}", 303)
    return serve_generated(_render(db, a.kind, a.ref_id, doc), _DOCX, count=False)


# ---------------------------------------------------------------- ดูตัวอย่างเอกสาร (services/doc_preview.py)
def _preview_json(db, kind, ref_id, doc, file_url=None):
    """doc ว่าง = รายชื่อเอกสาร  มี doc = สร้างภาพแต่ละหน้า"""
    from app.services import doc_preview as dp
    from app.tenancy import current_school_id
    docs = _docs_for(db, kind, ref_id) if kind in ap.KINDS else []
    if not doc:
        return JSONResponse({"docs": [{"key": d, "label": lb, "file": file_url(d) if file_url else None}
                                      for d, lb in docs]})
    if doc not in dict(docs):
        return JSONResponse({"ok": False, "msg": "ไม่พบเอกสารนี้"})
    if not dp.available():
        return JSONResponse({"ok": False, "msg": "เซิร์ฟเวอร์ยังไม่พร้อมแสดงตัวอย่าง ดาวน์โหลดไปเปิดแทน"})
    try:
        m = dp.build(_render(db, kind, ref_id, doc), current_school_id.get())
    except (dp.PreviewBusy, dp.PreviewFailed) as e:
        return JSONResponse({"ok": False, "msg": str(e)})
    except Exception:
        return JSONResponse({"ok": False, "msg": "สร้างตัวอย่างไม่สำเร็จ ดาวน์โหลดไปเปิดแทน"})
    return JSONResponse({"ok": True, "total": m["total"], "cut": m["cut"],
                         "pages": [f"/approvals/preview/{m['key']}/{i}.png" for i in range(1, m["pages"] + 1)]})


@router.get("/approvals/doc/{aid}/preview")
def approval_preview(aid: int, db: Session = Depends(get_db), doc: str = ""):
    a = db.get(Approval, aid)
    if not a or a.kind not in ap.KINDS:
        return JSONResponse({"ok": False, "msg": "ไม่พบเรื่องนี้", "docs": []})
    return _preview_json(db, a.kind, a.ref_id, doc,
                         file_url=lambda d: f"/approvals/doc/{aid}/file?doc={quote(d)}")


@router.get("/approvals/preview/{key}/{n}.png")
def approval_preview_page(key: str, n: int):
    from app.services import doc_preview as dp
    from app.tenancy import current_school_id
    p = dp.page_file(current_school_id.get(), key, n)
    if not p:
        return Response(status_code=404)
    return Response(p.read_bytes(), media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


# ผู้ส่งดูตัวอย่างก่อนกดส่ง ผอ. (อยู่ใต้ path ของงาน สิทธิ์งานเดิมคุมให้)
@router.get("/procurement/{pid}/approval/preview")
def proc_preview(pid: int, db: Session = Depends(get_db), kind: str = "", doc: str = ""):
    if kind not in ap.PROC_STAGES and kind != "proc_alt":
        return JSONResponse({"ok": False, "msg": "ไม่พบเอกสารนี้", "docs": []})
    return _preview_json(db, kind, pid, doc)


def _generic_preview(path):
    def handler(db: Session = Depends(get_db), kind: str = "", ref_id: int = 0, doc: str = ""):
        if kind not in ap.SEND_PATHS[path]:
            return JSONResponse({"ok": False, "msg": "ไม่พบเอกสารนี้", "docs": []})
        return _preview_json(db, kind, ref_id, doc)
    return handler


for _path in ap.SEND_PATHS:
    router.add_api_route(_path + "/preview", _generic_preview(_path), methods=["GET"])


def _decider_name(request, db) -> str:
    """ชื่อจริงจากทะเบียนบุคลากรที่ผูกกับไอดี (ขึ้นในเอกสารกรณีรักษาราชการแทน) ไม่มีใช้ชื่อไอดี"""
    pid = request.session.get("person_id")
    p = db.get(Person, pid) if pid else None
    return ((p.name if p else "") or request.session.get("name") or "").strip()


def _decide_one(request, db, aid, action, comment=""):
    a = ap.decide(db, aid, action, request.session.get("person_id"), _decider_name(request, db), comment)
    # แจ้งเตือน "รออนุมัติ" ของเรื่องนี้ (ถึง ผอ./รองผอ. ทุกคน) หมดหน้าที่แล้ว ไม่ให้ค้างในกระดิ่ง
    from datetime import datetime as _dt
    from app.models import Notification
    (db.query(Notification).filter(Notification.link == f"/approvals/doc/{aid}",
                                   Notification.read_at.is_(None))
     .update({Notification.read_at: _dt.now()}, synchronize_session=False))
    if a.sent_pid:
        from app.services.nav import create_notice
        spec = ap.KINDS[a.kind]
        word = {"returned": "ส่งกลับให้แก้", "approved": "อนุมัติแล้ว"}.get(a.status, a.status)
        create_notice(db, a.sent_pid, f"ผอ. {word}: {spec['label']}",
                      reason=(a.comment or a.title)[:200], link=spec["link"](a.ref_id),
                      level="warn" if a.status == "returned" else "info")
    return a


@router.post("/approvals/docs/decide-many")
async def approval_decide_many(request: Request, db: Session = Depends(get_db)):
    """อนุมัติหลายเรื่องพร้อมกัน (แปะลายเซ็น / ไม่แปะ) ส่งกลับต้องทำทีละเรื่องเพราะต้องเขียนเหตุผล"""
    if not _is_director(request):
        return RedirectResponse("/approvals?err=" + quote("เฉพาะ ผอ./รองผอ. เท่านั้น") + "#docs", 303)
    form = await request.form()
    action = form.get("action", "")
    if action not in ("sign", "approve"):
        return RedirectResponse("/approvals#docs", 303)
    ids = []
    for v in form.getlist("aid"):
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            pass
    if not ids:
        return RedirectResponse("/approvals?err=" + quote("ยังไม่ได้เลือกเรื่อง") + "#docs", 303)
    ok, bad = 0, []
    for aid in dict.fromkeys(ids):
        try:
            with db.begin_nested():
                _decide_one(request, db, aid, action)
            ok += 1
        except ValueError as e:
            a = db.get(Approval, aid)
            bad.append(f"{(a.title if a else aid)}: {e}")
    db.commit()
    word = "อนุมัติและแปะลายเซ็น" if action == "sign" else "อนุมัติ (ไม่แปะลายเซ็น)"
    q = "msg=" + quote(f"{word}แล้ว {ok} เรื่อง")
    if bad:
        q += "&err=" + quote("ทำไม่ได้ " + str(len(bad)) + " เรื่อง: " + " / ".join(bad)[:400])
    return RedirectResponse("/approvals?" + q + "#docs", 303)


@router.get("/lunch/installment/{iid}/approval-go")
def lunch_inst_go(iid: int, db: Session = Depends(get_db)):
    """ลิงก์จากกล่องรออนุมัติ/แจ้งเตือน: งวดอยู่ในหน้ารอบ"""
    from app.models import LunchInstallment
    i = db.get(LunchInstallment, iid)
    return RedirectResponse(f"/lunch/round/{i.round_id}/plan#approval" if i else "/lunch", 303)


@router.post("/approvals/doc/{aid}/decide")
def approval_decide(aid: int, request: Request, db: Session = Depends(get_db),
                    action: str = Form(""), comment: str = Form("")):
    if not _is_director(request):
        return RedirectResponse(f"/approvals/doc/{aid}?err=" + quote("เฉพาะ ผอ./รองผอ. เท่านั้น"), 303)
    try:
        _decide_one(request, db, aid, action, comment)
        db.commit()
    except ValueError as e:
        db.rollback()
        return RedirectResponse(f"/approvals/doc/{aid}?err=" + quote(str(e)), 303)
    done = {"sign": "อนุมัติและแปะลายเซ็นแล้ว", "approve": "อนุมัติแล้ว (ไม่แปะลายเซ็น)",
            "return": "ส่งกลับให้แก้แล้ว"}[action]
    return RedirectResponse("/approvals?msg=" + quote(done) + "#docs", 303)
