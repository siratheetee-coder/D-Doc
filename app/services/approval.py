# -*- coding: utf-8 -*-
"""ส่งเรื่องให้ ผอ. อนุมัติ (แกนกลาง ใช้ได้ทุกงาน) ระยะ 1 = พัสดุ + การเงิน

หลักการ (เจ้าของตกลง 2026-11-04)
  - ผู้ส่งกด "ส่ง ผอ. อนุมัติ" ผอ. เลือกได้ 3 ทาง
      อนุมัติและแปะลายเซ็น / อนุมัติแต่ไม่แปะลายเซ็น (เซ็นมือเอง) / ส่งกลับแก้
  - ลายเซ็น ผอ. ขึ้นเฉพาะเอกสารของขั้นที่อนุมัติแล้วเท่านั้น
  - แก้เรื่องหลังอนุมัติ (ยอดเงิน ผู้ขาย รายการ ฯลฯ) ลายเซ็นหลุดเอง ต้องส่งใหม่ (เทียบลายนิ้วมือ fingerprint)
  - ไม่กันขั้นต่อไป แค่ไม่ขึ้นลายเซ็น (ผอ. ไม่อยู่ งานไม่ค้าง)
  - เปิดเป็นรายโรงเรียน School.approval_on
  - เก็บประวัติทุกครั้ง (แถวใหม่ทุกการส่ง แถวล่าสุด = สถานะปัจจุบัน)
  - ลายเซ็นที่ใช้ = สำเนาลายเซ็นของ ผอ. ที่กดจริง ณ ตอนอนุมัติ (Approval.sig_file) เปลี่ยนรูปทีหลังไม่กระทบเรื่องเก่า

เพิ่มงานใหม่ = เพิ่มใน KINDS (ชื่อ, ชนิดตารางอ้างอิง, เอกสารที่ ผอ. ลงนาม, ลายนิ้วมือ, หัวเรื่อง/ยอด/ลิงก์)
"""
import hashlib
import shutil
import uuid
from datetime import datetime


# ---------------------------------------------------------------- ชนิดเรื่อง
def _proc(db, rid):
    from app.models import Procurement
    return db.get(Procurement, rid)


def _memo(db, rid):
    from app.models import DisburseMemo
    return db.get(DisburseMemo, rid)


def _loan(db, rid):
    from app.models import MoneyLoan
    return db.get(MoneyLoan, rid)


def _fp_proc(p) -> str:
    items = ";".join(f"{i.name}|{float(i.quantity or 0):g}|{float(i.unit_price or 0):.2f}"
                     for i in sorted(p.items or [], key=lambda x: x.id or 0))
    return "|".join([p.subject or "", p.proc_type or "", p.method or "", f"{float(p.total_amount or 0):.2f}",
                     str(p.vendor_id or ""), p.vat_mode or "", items])


def _fp_memo(m) -> str:
    return "|".join([m.subject or "", m.payee or "", f"{float(m.amount or 0):.2f}", f"{float(m.vat or 0):.2f}",
                     f"{float(m.wht or 0):.2f}", f"{float(m.fine or 0):.2f}", str(m.account_id or "")])


def _fp_loan(ln) -> str:
    return "|".join([ln.borrower or "", f"{float(ln.amount or 0):.2f}", ln.purpose or "", ln.items or "",
                     ln.fund_from or ""])


_PROC_TITLE = lambda p: f"{p.proc_type or 'ซื้อ'}{p.subject or ''}"  # noqa: E731

KINDS = {
    "proc_request": dict(
        label="ขออนุมัติจัดซื้อจัดจ้าง", step="ขั้นที่ 1 รายงานขอซื้อขอจ้าง",
        docs=["แต่งตั้งกรรมการคุณลักษณะ", "คำสั่งแต่งตั้งกรรมการคุณลักษณะ", "รายงานขอซื้อ",
              "คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง", "คำสั่งแต่งตั้งผู้ตรวจรับ"],
        get=_proc, fp=_fp_proc, title=_PROC_TITLE, amount=lambda p: p.total_amount,
        link=lambda rid: f"/procurement/{rid}", group="พัสดุ"),
    "proc_order": dict(
        label="อนุมัติสั่งซื้อสั่งจ้าง", step="ขั้นที่ 2 ผลพิจารณาและใบสั่ง",
        docs=["รายงานผลการพิจารณา", "ประกาศผู้ชนะ", "ใบสั่งซื้อ/สั่งจ้าง"],
        get=_proc, fp=_fp_proc, title=_PROC_TITLE, amount=lambda p: p.total_amount,
        link=lambda rid: f"/procurement/{rid}", group="พัสดุ"),
    "proc_pay": dict(
        label="ผลตรวจรับและอนุมัติเบิกจ่าย", step="ขั้นที่ 3 ตรวจรับและเบิกจ่าย",
        docs=["ใบตรวจรับพัสดุ", "รายงานผลตรวจรับและเบิกจ่าย"],
        get=_proc, fp=_fp_proc, title=_PROC_TITLE, amount=lambda p: p.total_amount,
        link=lambda rid: f"/procurement/{rid}", group="พัสดุ"),
    "disburse": dict(
        label="บันทึกขอเบิกจ่าย", step="บันทึกขออนุมัติเบิกจ่าย", docs=["บันทึกขอเบิกจ่าย"],
        get=_memo, fp=_fp_memo, title=lambda m: m.subject or f"บันทึกขอเบิก {m.memo_no or m.id}",
        amount=lambda m: m.amount, link=lambda rid: f"/finance/disburse/{rid}", group="การเงิน"),
    "loan": dict(
        label="สัญญายืมเงิน", step="อนุมัติให้ยืมเงิน", docs=["สัญญายืมเงิน"],
        get=_loan, fp=_fp_loan, title=lambda ln: f"{ln.borrower or ''} {ln.purpose or ''}".strip(),
        amount=lambda ln: ln.amount, link=lambda rid: "/finance/loans", group="การเงิน"),
}
# ---- ระยะ 2: ธุรการ + โครงการ ----
def _get(model):
    def get(db, rid):
        import app.models as M
        return db.get(getattr(M, model), rid)
    return get


def _fp_fields(*names):
    def fp(o):
        return "|".join(str(getattr(o, n, "") or "") for n in names)
    return fp


KINDS.update({
    "memo": dict(
        label="บันทึกข้อความ", step="บันทึกข้อความเสนอ ผอ.", docs=["บันทึกข้อความ"],
        get=_get("OfficeMemo"), fp=_fp_fields("subject", "to_person", "body", "signer_name"),
        title=lambda o: o.subject or f"บันทึกข้อความ {o.memo_no or o.id}", amount=lambda o: 0,
        link=lambda rid: f"/admin/memos/{rid}", group="ธุรการ"),
    "order": dict(
        label="คำสั่งโรงเรียน", step="ผอ. ลงนามคำสั่ง", docs=["คำสั่ง"],
        get=_get("SchoolOrder"), fp=_fp_fields("subject", "body"),
        title=lambda o: o.subject or f"คำสั่ง {o.order_no or o.id}", amount=lambda o: 0,
        link=lambda rid: f"/admin/orders/{rid}", group="ธุรการ"),
    "letter": dict(
        label="หนังสือราชการ (ส่งออก)", step="ผอ. ลงนามหนังสือ", docs=["หนังสือราชการ"],
        get=_get("OfficialLetter"), fp=_fp_fields("subject", "to", "body", "signer_name"),
        title=lambda o: o.subject or f"หนังสือ {o.doc_no or o.id}", amount=lambda o: 0,
        link=lambda rid: f"/admin/letters/{rid}", group="ธุรการ"),
    "project": dict(
        label="อนุมัติโครงการ", step="ขออนุมัติโครงการ", docs=[],
        get=_get("Project"), fp=lambda p: f"{p.name or ''}|{float(p.budget or 0):.2f}|{p.responsible or ''}",
        title=lambda p: p.name or "", amount=lambda p: p.budget,
        link=lambda rid: f"/projects/{rid}", group="โครงการ"),
    "project_report": dict(
        label="รายงานผลโครงการ", step="เสนอรายงานผลการดำเนินงาน", docs=["รายงานผลโครงการ"],
        get=_get("ProjectReport"),
        fp=_fp_fields("title", "responsible", "date_start", "date_end", "memo_body", "summary_note", "suggestions"),
        title=lambda r: r.title or (r.project.name if r.project else "") or "รายงานผลโครงการ", amount=lambda r: 0,
        link=lambda rid: f"/project-reports/{rid}", group="โครงการ"),
})
# เส้นทางส่ง (อยู่ใต้ path ของงาน สิทธิ์งานเดิมคุม) -> ชนิดที่ส่งได้
SEND_PATHS = {"/finance/approval": ("disburse", "loan"),
              "/admin/approval": ("memo", "order", "letter"),
              "/projects/approval": ("project", "project_report")}


def lookup_current(kind: str, ref_id: int) -> dict:
    """ใช้ตอนสร้างเอกสารที่ประกอบเองในโค้ด (บันทึก/คำสั่ง/หนังสือ)
    on = โรงเรียนเปิดใช้ · a = Approval ที่อนุมัติแล้วและเรื่องไม่ถูกแก้ · sig = path รูปลายเซ็น (แปะได้)"""
    out = {"on": False, "a": None, "sig": None}
    try:
        from app.tenancy import current_school_id, session_for
        from app.services.signature import signature_full_path
        sid = current_school_id.get()
        if not sid:
            return out
        db = session_for(sid)
        try:
            out["on"] = enabled(db)
            if out["on"]:
                a = approved_for(db, kind, ref_id)
                if a:
                    db.expunge(a)
                    out["a"] = a
                    if a.with_sign and a.sig_file:
                        p = signature_full_path(a.sig_file)
                        out["sig"] = str(p) if p else None
        finally:
            db.close()
    except Exception:
        pass
    return out


KINDS["proc_alt"] = dict(
    label="อนุมัติจัดซื้อแบบพิเศษ", step="เอกสารของเรื่องนี้ทั้งชุด (ว.804 / ว.119)",
    docs=["w804", "w119t1", "w119t2", "w119_borrow"],      # กรองตามรูปแบบของเรื่องใน alt_docs()
    get=_proc, fp=_fp_proc, title=_PROC_TITLE, amount=lambda p: p.total_amount,
    link=lambda rid: f"/procurement/{rid}", group="พัสดุ")
PROC_STAGES = ["proc_request", "proc_order", "proc_pay"]
# รูปแบบพิเศษที่ ผอ. ลงนาม (ข้อ 79 วรรคสอง หัวหน้าเจ้าหน้าที่อนุมัติ ไม่ผ่าน ผอ.)
ALT_CASES = ("w804", "w119t1", "w119t2")


def alt_docs(proc) -> list:
    """เอกสารรูปแบบพิเศษของเรื่องนี้ที่มีช่องลงนาม ผอ."""
    case = proc.proc_case or ""
    return [case] + (["w119_borrow"] if case == "w119t2" else []) if case in ALT_CASES else []
# ชนิดเอกสารพัสดุ -> ขั้นอนุมัติ
DOC_STAGE = {d: k for k in PROC_STAGES for d in KINDS[k]["docs"]}


def fingerprint(kind: str, obj) -> str:
    return hashlib.sha1(KINDS[kind]["fp"](obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- อ่านสถานะ
def enabled(db) -> bool:
    from app.models import School
    s = db.query(School).first()
    return bool(s and getattr(s, "approval_on", False))


def latest(db, kind: str, ref_id: int):
    from app.models import Approval
    return (db.query(Approval).filter_by(kind=kind, ref_id=ref_id)
            .order_by(Approval.id.desc()).first())


def history(db, kind: str, ref_id: int) -> list:
    from app.models import Approval
    return (db.query(Approval).filter_by(kind=kind, ref_id=ref_id)
            .order_by(Approval.id.desc()).all())


def state(db, kind: str, ref_id: int, obj=None) -> dict:
    """สถานะสำหรับกล่องในหน้าเรื่อง
    code: none / pending / approved / signed / returned / stale (แก้หลังอนุมัติ ต้องส่งใหม่)"""
    a = latest(db, kind, ref_id)
    spec = KINDS[kind]
    out = dict(kind=kind, ref_id=ref_id, label=spec["label"], step=spec["step"], docs=spec["docs"], a=a, code="none")
    if not a or a.status == "cancelled":
        return out
    if a.status == "approved":
        obj = obj if obj is not None else spec["get"](db, ref_id)
        if obj is not None and a.fingerprint and a.fingerprint != fingerprint(kind, obj):
            out["code"] = "stale"
        else:
            out["code"] = "signed" if a.with_sign else "approved"
    else:
        out["code"] = a.status          # pending / returned
    return out


def proc_states(db, proc) -> list:
    """กล่องส่ง ผอ. ของเรื่องจัดซื้อ แบบปกติ 3 ขั้น แบบพิเศษ 1 ครั้งทั้งชุด ข้อ 79 ไม่มี"""
    case = proc.proc_case or "normal"
    if case == "normal":
        return [state(db, k, proc.id, proc) for k in PROC_STAGES]
    if case in ALT_CASES:
        st = state(db, "proc_alt", proc.id, proc)
        st["docs"] = alt_docs(proc)
        return [st]
    return []


def pending(db) -> list:
    """เรื่องที่รอ ผอ. ทั้งหมด (ล่าสุดของแต่ละเรื่องเป็น pending) พร้อมหัวเรื่อง/ยอด"""
    from app.models import Approval
    rows = db.query(Approval).filter_by(status="pending").order_by(Approval.sent_at).all()
    out = []
    for a in rows:
        if latest(db, a.kind, a.ref_id).id != a.id or a.kind not in KINDS:
            continue
        out.append(a)
    return out


def pending_count(db) -> int:
    try:
        return len(pending(db))
    except Exception:
        return 0


def approved_for(db, kind: str, ref_id: int, obj=None):
    """Approval ที่อนุมัติแล้วและเรื่องยังไม่ถูกแก้ (ใช้ติ๊ก ☑ อนุมัติ / แปะลายเซ็น) หรือ None"""
    st = state(db, kind, ref_id, obj)
    return st["a"] if st["code"] in ("approved", "signed") else None


# ---------------------------------------------------------------- เปลี่ยนสถานะ
def send(db, kind: str, ref_id: int, by_name: str, note: str = "", by_pid=None):
    from app.models import Approval
    if kind not in KINDS:
        raise ValueError("ไม่รู้จักชนิดเรื่อง")
    obj = KINDS[kind]["get"](db, ref_id)
    if obj is None:
        raise ValueError("ไม่พบเรื่องนี้")
    cur = latest(db, kind, ref_id)
    if cur and cur.status == "pending":
        raise ValueError("เรื่องนี้ส่ง ผอ. ไว้แล้ว รอ ผอ. พิจารณา")
    a = Approval(kind=kind, ref_id=ref_id, status="pending",
                 title=(KINDS[kind]["title"](obj) or "")[:300], amount=float(KINDS[kind]["amount"](obj) or 0),
                 fingerprint=fingerprint(kind, obj), sent_by=(by_name or "")[:120], sent_pid=by_pid, sent_at=datetime.now(),
                 sent_note=(note or "").strip()[:500])
    db.add(a)
    return a


def cancel(db, kind: str, ref_id: int):
    cur = latest(db, kind, ref_id)
    if cur and cur.status == "pending":
        cur.status = "cancelled"
    return cur


def decide(db, aid: int, action: str, person_id, name: str, comment: str = ""):
    """action: sign = อนุมัติและแปะลายเซ็น / approve = อนุมัติไม่แปะ / return = ส่งกลับแก้"""
    from app.models import Approval
    a = db.get(Approval, aid)
    if not a or a.status != "pending":
        raise ValueError("เรื่องนี้พิจารณาไปแล้ว")
    if action not in ("sign", "approve", "return"):
        raise ValueError("เลือกผลการพิจารณา")
    comment = (comment or "").strip()[:500]
    if action == "return" and not comment:
        raise ValueError("ส่งกลับแก้ ต้องเขียนเหตุผลให้ผู้ส่ง")
    obj = KINDS[a.kind]["get"](db, a.ref_id) if a.kind in KINDS else None
    if obj is None:
        raise ValueError("ไม่พบเรื่องนี้แล้ว อาจถูกลบไป")
    if action != "return" and a.fingerprint != fingerprint(a.kind, obj):
        # ผู้ส่งแก้เรื่องระหว่างรอ ให้ ผอ. อนุมัติฉบับที่เห็นอยู่ตอนนี้
        a.fingerprint = fingerprint(a.kind, obj)
    a.decided_by, a.decided_name, a.decided_at, a.comment = person_id, (name or "")[:120], datetime.now(), comment
    if action == "return":
        a.status = "returned"
        return a
    a.status, a.with_sign = "approved", action == "sign"
    if a.with_sign:
        a.sig_file = _copy_signature(db, person_id, name)
        if not a.sig_file:
            raise ValueError("ยังไม่มีรูปลายเซ็นของ ผอ. ในทะเบียนบุคลากร เลือก อนุมัติแต่ไม่แปะลายเซ็น "
                             "หรือให้ไอดีหลักใส่รูปลายเซ็นก่อน")
    return a


def _copy_signature(db, person_id, name) -> str:
    """สำเนาลายเซ็นของ ผอ. ที่กดจริง ณ ตอนนี้ (เปลี่ยนรูปทีหลังไม่กระทบเรื่องที่อนุมัติไปแล้ว)"""
    from app.models import Person, School
    from app.services.signature import signature_full_path, signature_path_for, signatures_dir
    src = None
    p = db.get(Person, person_id) if person_id else None
    if p and (p.signature or "").strip():
        src = signature_full_path(p.signature)
    if not src:
        s = db.query(School).first()
        path = signature_path_for(db, (name or "").strip()) or (signature_path_for(db, s.director_name or "") if s else None)
        src = path
    if not src:
        return ""
    fn = "ap_" + uuid.uuid4().hex + ".png"
    try:
        shutil.copyfile(str(src), str(signatures_dir() / fn))
    except OSError:
        return ""
    return fn


# ---------------------------------------------------------------- แปะลงเอกสาร
def stamp_current(kind: str, ref_id: int, path: str, director_name: str, tick=("อนุมัติ",)) -> bool:
    """เปิดฐานข้อมูลโรงเรียนที่ล็อกอินเอง (ฟังก์ชันสร้างเอกสารไม่มี db) แล้วแปะถ้าอนุมัติแล้ว"""
    try:
        from app.tenancy import current_school_id, session_for
        sid = current_school_id.get()
        if not sid:
            return False
        db = session_for(sid)
        try:
            if not enabled(db):
                return False
            a = approved_for(db, kind, ref_id)
            if not a:
                return False
            return stamp_file(path, director_name, a.sig_file if a.with_sign else "", tick=tick)
        finally:
            db.close()
    except Exception:
        return False


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _all_paragraphs(doc):
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def walk(container):
        for el in container._element.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                yield Paragraph(el, container)
            elif tag == "tbl":
                for row in Table(el, container).rows:
                    for cell in row.cells:
                        yield from walk(cell)
    body = doc._body if hasattr(doc, "_body") else doc
    yield from walk(body)


def stamp_file(path: str, director_name: str, sig_file: str, tick=("อนุมัติ",)) -> bool:
    """แปะลายเซ็น ผอ. บนบรรทัด 'ลงชื่อ....' ที่อยู่เหนือ ( ชื่อ ผอ. ) ทุกจุดในไฟล์
    + ติ๊กช่องคำสั่ง tick ('อนุมัติ' / 'ทราบ') ทั้งแบบ ☐ อนุมัติ และ (   ) อนุมัติ"""
    from docx import Document
    from app.services.signature import signature_full_path
    name = _norm(director_name)
    sig = signature_full_path(sig_file) if sig_file else None
    if not name or not (sig or tick):
        return False
    doc = Document(path)
    paras = list(_all_paragraphs(doc))
    done, seen = 0, set()
    for i, p in enumerate(paras):
        t = _norm(p.text)
        target = None
        if "ลงชื่อ" in t and f"( {name} )" in t or "ลงชื่อ" in t and f"({name})" in t:
            target = p
        elif t in (f"( {name} )", f"({name})"):
            for back in (1, 2):
                if i - back >= 0 and "ลงชื่อ" in paras[i - back].text:
                    target = paras[i - back]
                    break
        if target is None or id(target._p) in seen:
            continue
        seen.add(id(target._p))
        if sig and _float_on_dots(target, str(sig)):
            done += 1
    if tick:
        import re
        words = "|".join(re.escape(w) for w in ((tick,) if isinstance(tick, str) else tick))
        box = re.compile(r"☐(\s*(?:" + words + "))")
        paren = re.compile(r"\(\s{1,5}\)(\s*(?:" + words + "))")
        for p in paras:
            for r in p.runs:
                t = r.text or ""
                new = paren.sub(r"( ✓ )\1", box.sub(r"☑\1", t))
                if new != t:
                    r.text = new
                    done += 1
    if done:
        refit_signatures(doc)          # ล้างเครื่องหมายภายในก่อนบันทึก (ค่าไม่เปลี่ยน)
        doc.save(path)
    return bool(done)


def _float_on_dots(paragraph, sig_path: str, height_cm: float = 1.1) -> bool:
    """วางรูปลายเซ็นลอยทับจุดไข่ปลาหลังคำ 'ลงชื่อ' (แยก run ที่จุดเริ่ม แล้วแทรกรูปตรงนั้น)"""
    import copy
    import re
    from docx.shared import Cm
    from docx.text.run import Run
    from docx.oxml import OxmlElement
    from app.services.gov_forms import _float_at_run
    runs = paragraph.runs
    for r in runs:
        m = re.search(r"[.…]{3,}", r.text or "")      # ว.804 ใช้ … แทนจุด
        if not m:
            continue
        before, after = r.text[:m.start()], r.text[m.start():]
        r.text = before
        dots = copy.deepcopy(r._element)
        r._element.addnext(dots)
        Run(dots, r._parent).text = after
        pic = OxmlElement("w:r")
        r._element.addnext(pic)
        try:
            shape = Run(pic, r._parent).add_picture(sig_path, height=Cm(height_cm))
            # ลอยทับจุดไข่ปลา ยกขึ้นนิดเดียว ไม่ให้ทับบรรทัดคำสั่ง (   ) อนุมัติ ข้างบน
            # ตำแหน่งนับจากขอบบนของย่อหน้า ต้องบวกระยะเว้นก่อนย่อหน้า (แม่แบบพัสดุเว้นไว้ราว 1 ซม.)
            gap = paragraph.paragraph_format.space_before or 0
            _float_at_run(shape._inline, dx_emu=Cm(0.4).emu, dy_emu=int(gap) + Cm(-0.45).emu)
            _mark(paragraph)
            return True
        except Exception:
            pic.getparent().remove(pic)
            return False
    return False


def _mark(paragraph):
    """จำย่อหน้าที่วางลายเซ็นไว้ (ในหน่วยความจำของเอกสาร ไม่เขียนลงไฟล์)
    เผื่อตัวจัดหน้าเติมระยะเว้นทีหลัง (refit_signatures)"""
    try:
        part = paragraph.part
        if not hasattr(part, "_ee_sigs"):
            part._ee_sigs = []
        part._ee_sigs.append(paragraph._p)
    except Exception:
        pass


def refit_signatures(doc):
    """ตัวจัดหน้า (page_fit) เพิ่ม/ลดระยะเว้นเหนือบรรทัดลงชื่อหลังวางลายเซ็นแล้ว
    คำนวณตำแหน่งแนวตั้งใหม่ตามระยะเว้นล่าสุด ไม่งั้นลายเซ็นลอยสูงเกินบรรทัด แล้วล้างเครื่องหมาย"""
    from docx.oxml.ns import qn
    from docx.shared import Cm
    from docx.text.paragraph import Paragraph
    for p_el in getattr(doc.part, "_ee_sigs", []):
        gap = Paragraph(p_el, None).paragraph_format.space_before or 0
        for pv in p_el.iter(qn("wp:positionV")):
            off = pv.find(qn("wp:posOffset"))
            if off is not None:
                off.text = str(int(gap) + Cm(-0.45).emu)


def box(db, kind: str, ref_id: int, back: str):
    """ข้อมูลกล่องส่ง ผอ. ของหน้าเรื่อง (_approval_card.html) None = โรงเรียนยังไม่เปิดใช้"""
    if not enabled(db):
        return None
    action = next(p for p, ks in SEND_PATHS.items() if kind in ks)
    return dict(st=state(db, kind, ref_id), action=action, back=back, extra={"ref_id": ref_id})
