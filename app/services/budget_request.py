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


def step_of(req) -> int:
    """ขั้นปัจจุบัน (0-based) สำหรับแถบขั้นตอนในการ์ดครู ช่วงที่ 1 มีแค่ร่าง/ส่งแล้ว"""
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
                        no=r.request_no, total=nums["request"], left=nums["left"], step=step_of(r),
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
