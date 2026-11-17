# -*- coding: utf-8 -*-
"""คำขอใช้งบประมาณ: ข้อความในบันทึก + ยอดงบโครงการ + ข้อมูลการ์ดหน้าหลักครู

กติกาเดียวกับบันทึกขอใช้งบในเรื่องจัดซื้อ (services/budget_memo.py)
- ประเภทค่าใช้จ่ายและวิธีเบิก คนเลือกเองทุกแถว ระบบไม่เดาจากราคา
- ไม่พิมพ์เลขบัตรประชาชน (PDPA)
"""
from app.services.budget_memo import COST_TYPES, _ORDER, _num

METHODS = ["จัดซื้อ", "จัดจ้าง", "ยืมเงิน", "เบิกจ่ายตรง"]


def clean_lines(form):
    """แถวจากฟอร์ม -> list[dict] (ทิ้งแถวที่ไม่มีชื่อรายการ)"""
    g = form.getlist
    names, types, qtys, units, prices, methods = (g("ln_name"), g("ln_type"), g("ln_qty"), g("ln_unit"),
                                                  g("ln_price"), g("ln_method"))
    out = []
    for i, nm in enumerate(names):
        nm = (nm or "").strip()
        if not nm:
            continue
        pick = lambda lst, d="": (lst[i] if i < len(lst) else d) or d
        try:
            qty = float(str(pick(qtys, "0")).replace(",", ""))
            price = float(str(pick(prices, "0")).replace(",", ""))
        except ValueError:
            qty = price = 0.0
        t, m = pick(types), pick(methods)
        out.append(dict(name=nm[:300], cost_type=t if t in COST_TYPES else "ค่าวัสดุ", qty=max(qty, 0.0),
                        unit=str(pick(units)).strip()[:40], price=max(price, 0.0),
                        method=m if m in METHODS else "จัดซื้อ"))
    return out


def total(req) -> float:
    return round(sum(ln.amount for ln in req.lines), 2)


def by_method(req) -> list:
    """กลุ่มตามวิธีเบิก [{method, lines, total}] เรียงตาม METHODS"""
    out = []
    for m in METHODS:
        rows = [ln for ln in req.lines if ln.method == m]
        if rows:
            out.append(dict(method=m, lines=rows, total=round(sum(r.amount for r in rows), 2)))
    return out


def memo_lines(req) -> list:
    """ข้อความรายการในบันทึก จัดกลุ่มตามประเภทค่าใช้จ่าย แต่ละแถวบอกวิธีเบิก"""
    lines, n = [], 0
    for t in _ORDER:
        rows = [ln for ln in req.lines if ln.cost_type == t]
        if not rows:
            continue
        n += 1
        lines.append({"text": f"{n}. {t} เป็นเงิน {_num(sum(r.amount for r in rows))} บาท ดังนี้", "sub": False})
        for k, r in enumerate(rows, 1):
            unit = f" {r.unit}" if r.unit else ""
            lines.append({"text": f"{n}.{k} {r.name} จำนวน {_num(r.qty)}{unit} ๆ ละ {_num(r.price)} บาท "
                                  f"เป็นเงิน {_num(r.amount)} บาท ({r.method})", "sub": True})
    return lines


def budget_numbers(db, req) -> dict:
    """ข้อ 1-5 ของบันทึก จากทะเบียนโครงการ (คำขอยังไม่ได้ตัดงบ จึงไม่ต้องบวกคืน)"""
    from app.models import Project
    from app.services.budget import project_budget, project_remaining
    req_total = total(req)
    proj = db.get(Project, req.project_id) if req.project_id else None
    if not proj:
        return {"approved": None, "used": None, "left": None, "request": req_total, "carry": None}
    approved = float(project_budget(proj) or 0)
    left = float(project_remaining(proj) or 0)
    return {"approved": approved, "used": approved - left, "left": left, "request": req_total,
            "carry": left - req_total}


STEPS = ["ขอใช้งบ", "ผอ. อนุมัติ", "จัดซื้อ/ยืม/เบิก", "จ่ายครบ"]


# ---------------- ช่วงที่ 2: เอกสารปลายทางรายวิธีเบิก ----------------
# วิธีเบิก -> (คอลัมน์ในแถว, ชนิดเอกสาร)
TARGET = {"จัดซื้อ": ("procurement_id", "proc"), "จัดจ้าง": ("procurement_id", "proc"),
          "ยืมเงิน": ("loan_id", "loan"), "เบิกจ่ายตรง": ("disburse_id", "disburse")}
NEXT_LABEL = {"proc": "สร้างเรื่องจัดซื้อ/จัดจ้าง", "loan": "ทำสัญญายืมเงิน", "disburse": "ออกบันทึกขอเบิก"}


def _target_obj(db, kind, tid):
    from app.models import DisburseMemo, MoneyLoan, Procurement
    model = {"proc": Procurement, "loan": MoneyLoan, "disburse": DisburseMemo}[kind]
    return db.get(model, tid) if tid else None


def target_info(db, kind, obj) -> dict:
    """สถานะเอกสารปลายทาง: id, label, href, done (จ่าย/ส่งใช้ครบแล้ว)"""
    d = _target_info(kind, obj)
    d["id"] = obj.id
    return d


def _target_info(kind, obj) -> dict:
    if kind == "proc":
        no = obj.memo_no or f"#{obj.id}"
        return dict(label=f"เรื่องจัดซื้อ/จ้าง {no}", status=obj.status or "ร่าง", href=f"/procurement/{obj.id}",
                    done=obj.status == "เบิกจ่ายแล้ว" or bool(obj.paid_before_system))
    if kind == "loan":
        back = sum(float(r.amount or 0) for r in (obj.returns or []))
        done = float(obj.amount or 0) > 0 and back >= float(obj.amount or 0) - 0.005
        return dict(label=f"สัญญายืม {obj.contract_no or '#' + str(obj.id)}", href=f"/finance/loans?year={obj.fiscal_year}#loan-{obj.id}",
                    status="ส่งใช้ครบแล้ว" if done else ("ส่งใช้บางส่วน" if back else "ยังไม่ส่งใช้"), done=done)
    return dict(label=f"บันทึกขอเบิก {obj.memo_no or '#' + str(obj.id)}", status=obj.status or "ร่าง",
                href=f"/finance/disburse/{obj.id}", done=obj.status == "จ่ายแล้ว")


def groups(db, req) -> list:
    """by_method + เอกสารปลายทางของแต่ละกลุ่ม (แถวที่ยังไม่ผูก = pending)"""
    out = []
    for g in by_method(req):
        col, kind = TARGET[g["method"]]
        docs, pending = {}, []
        for ln in g["lines"]:
            obj = _target_obj(db, kind, getattr(ln, col))
            ln.target = target_info(db, kind, obj) if obj else None
            if obj:
                docs[obj.id] = ln.target
            else:
                pending.append(ln)
        g.update(kind=kind, docs=list(docs.values()), pending=pending,
                 pending_total=round(sum(ln.amount for ln in pending), 2),
                 next_label=f"สร้างเรื่อง{g['method']}" if kind == "proc" else NEXT_LABEL[kind])
        out.append(g)
    return out


def pending_lines(req, method, db=None):
    """แถวที่ยังไม่มีเอกสาร (เอกสารที่ผูกไว้ถูกลบไปแล้ว นับเป็นยังไม่มี)"""
    col, kind = TARGET[method]
    return [ln for ln in req.lines if ln.method == method
            and not (getattr(ln, col) and (db is None or _target_obj(db, kind, getattr(ln, col))))]


def link(db, req, method, target_id) -> int:
    """ผูกแถวที่ยังไม่มีเอกสารของวิธีเบิกนี้เข้ากับเอกสาร target_id คืนจำนวนแถว"""
    col, kind = TARGET[method]
    if not _target_obj(db, kind, target_id):
        raise ValueError("ไม่พบเอกสารที่เลือก")
    rows = pending_lines(req, method, db)
    for ln in rows:
        setattr(ln, col, target_id)
    return len(rows)


def unlink(db, req, method, target_id):
    col, _ = TARGET[method]
    for ln in req.lines:
        if ln.method == method and getattr(ln, col) == target_id:
            setattr(ln, col, None)


def candidates(db, req, kind) -> list:
    """เอกสารที่มีอยู่แล้ว (โครงการเดียวกัน ปีงบเดียวกัน) ให้เลือกผูก"""
    from app.models import DisburseMemo, MoneyLoan, Procurement
    model = {"proc": Procurement, "loan": MoneyLoan, "disburse": DisburseMemo}[kind]
    q = db.query(model).filter(model.fiscal_year == req.fiscal_year)
    if req.project_id:
        q = q.filter(model.project_id == req.project_id)
    out = []
    for o in q.order_by(model.id.desc()).limit(30):
        name = getattr(o, "subject", None) or getattr(o, "purpose", None) or getattr(o, "borrower", "")
        amt = getattr(o, "total_amount", None) if kind == "proc" else o.amount
        out.append(dict(id=o.id, text=f"{target_info(db, kind, o)['label']} {name or ''} {float(amt or 0):,.2f} บาท".strip()))
    return out


def prefill(req, method, db=None) -> dict:
    """ค่าตั้งต้นของฟอร์มปลายทางจากแถวที่ยังไม่ผูก"""
    rows = pending_lines(req, method, db)
    title = (req.project.name if req.project else "") or req.purpose or ""
    return dict(rows=rows, total=round(sum(ln.amount for ln in rows), 2), title=title,
                subject=" ".join(ln.name for ln in rows)[:200] or title,
                purpose=f"เพื่อใช้ในโครงการ {title}".strip() if title else "")


def step_of(req, db=None) -> int:
    """ขั้นปัจจุบัน (0-based) 0 ขอใช้งบ 1 ผอ. อนุมัติ 2 จัดซื้อ/ยืม/เบิก 3 จ่ายครบ 4 = เสร็จทุกขั้น"""
    if db is not None and req.lines:
        gs = groups(db, req)
        if all(not g["pending"] for g in gs):
            return 4 if all(ln.target and ln.target["done"] for g in gs for ln in g["lines"]) else 3
        if any(g["docs"] for g in gs):
            return 2
    return 1 if req.status == "ส่งแล้ว" else 0


def teacher_cards(db, pid, limit=3) -> list:
    from app.models import BudgetRequest
    if not pid:
        return []
    rows = (db.query(BudgetRequest).filter(BudgetRequest.owner_person_id == pid)
            .order_by(BudgetRequest.id.desc()).limit(limit).all())
    out = []
    for r in rows:
        nums = budget_numbers(db, r)
        out.append(dict(id=r.id, title=(r.purpose or (r.project.name if r.project else "") or "คำขอใช้งบประมาณ"),
                        no=r.request_no, total=nums["request"], left=nums["left"], step=step_of(r, db),
                        href=f"/me/budget-requests/{r.id}"))
    return out


def render_docx(db, req, school) -> str:
    """บันทึกขอใช้งบประมาณจากคำขอ ใช้แม่แบบเดียวกับเรื่องจัดซื้อ (หน้า 2 = รายการจัดซื้อ/จัดจ้าง)"""
    from docxtpl import DocxTemplate
    from app.database import get_data_dir
    from app.services import render as R
    from app.thai_utils import bahttext, thai_date
    path = R.TEMPLATES_DIR / R.TEMPLATE_FILES["บันทึกขอใช้งบประมาณ"]
    tpl = DocxTemplate(str(path))
    nums = budget_numbers(db, req)
    m = lambda v: R._money(v) if v is not None else "................"
    proc_rows = [ln for ln in req.lines if ln.method in ("จัดซื้อ", "จัดจ้าง")]
    names = [x.strip() for x in (req.inspectors or "").splitlines() if x.strip()]
    pj = req.project.name if req.project else ""
    tot = total(req)
    ctx = {
        "budget_memo_no": req.request_no or R._BLANK,
        "request_date": thai_date(req.date) if req.date else R._BLANK,
        "school_office": R._school_office(school), "director_office": R._director_office(school),
        "director_name": school.director_name or "",
        "finance_officer_text": (getattr(school, "finance_officer_name", "") or "").strip() or R._BLANK,
        "bm_owner": (req.owner or "").strip() or R._BLANK,
        "department_text": (req.department or "").strip() or R._BLANK,
        "bm_project": ("โครงการ" + R._clean_project(pj)) if pj else ((req.purpose or "").strip() or R._BLANK),
        "bm_activity_date": thai_date(req.activity_date) if req.activity_date else "",
        "bm_lines": memo_lines(req), "bm_total": R._money(tot), "bm_total_baht": bahttext(tot),
        "bm_approved": m(nums["approved"]), "bm_used": m(nums["used"]), "bm_left": m(nums["left"]),
        "bm_carry": m(nums["carry"]), "bm_inspectors": names or [R._BLANK],
        "items": [{"name": ln.name, "quantity": f"{ln.qty:g}", "unit": ln.unit, "unit_price": R._money(ln.price),
                   "amount": R._money(ln.amount), "cost_type": ln.cost_type} for ln in proc_rows],
        "total_amount": R._money(sum(ln.amount for ln in proc_rows)),
    }
    tpl.render(ctx)
    try:
        from app.services.page_fit import fit_one_page
        fit_one_page(tpl.docx)
    except Exception:
        pass
    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    fname = R._safe_filename(f"บันทึกขอใช้งบประมาณ_{req.request_no or req.id}_{pj or req.purpose or ''}.docx")
    p = out / fname
    tpl.save(str(p))
    return str(p)
