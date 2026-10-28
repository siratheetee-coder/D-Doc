# -*- coding: utf-8 -*-
"""
budget.py - คำนวณงบโครงการ / ใช้จริง / คงเหลือ (โมดูลแผนปฏิบัติการ)

- งบปัจจุบัน = ยอดของการปรับงบครั้งล่าสุด (ProjectBudgetRevision) ถ้าไม่มี = Project.budget
- ใช้จริง = Σ เรื่องจัดซื้อที่ผูกโครงการ + Σ ขอเบิกจ่ายที่ผูกโครงการ (เฉพาะที่ไม่ได้อ้างเรื่องจัดซื้อ กันนับซ้ำ)
- เงินยืมที่ผูกโครงการ: ใบสำคัญที่ส่งใช้ = ใช้จริง, ยอดที่ยังไม่ส่งใช้ = กันงบไว้ (รอจ่าย),
  เงินสดที่ส่งคืน = ไม่นับ (กลับเป็นงบเหลือ) · รายการจ่ายเงินยืมในทะเบียนคุมเงินไม่นับซ้ำ
"""
from app.thai_utils import current_fiscal_year, current_academic_year


def current_plan_year(school) -> int:
    """ปีของแผนปัจจุบัน ตามโหมดที่ตั้งไว้ของโรงเรียน"""
    mode = getattr(school, "project_year_mode", "budget") or "budget"
    return current_academic_year() if mode == "academic" else current_fiscal_year()


def plan_year_label(school, year=None) -> str:
    mode = getattr(school, "project_year_mode", "budget") or "budget"
    if year is not None:
        from sqlalchemy.orm import object_session
        from app.models import PlanBudget
        db=object_session(school)
        saved=db.query(PlanBudget).filter_by(year=year).first() if db else None
        if saved: mode=saved.mode
    return "ปีการศึกษา" if mode == "academic" else "ปีงบประมาณ"


def project_budget(project) -> float:
    """งบปัจจุบันของโครงการ = ยอดของการปรับงบครั้งล่าสุด มิฉะนั้นใช้ budget ตั้งต้น"""
    revs = getattr(project, "revisions", None) or []
    if revs:
        last = max(revs, key=lambda r: (r.seq or 0))
        return float(last.amount or 0)
    return float(project.budget or 0)


def project_procurements(project) -> list:
    """เรื่องจัดซื้อที่ผูกกับโครงการนี้ = ผูกด้วย project_id หรือ (เรื่องเก่า) ชื่อโครงการ+ปีตรงกัน
    (เผื่อเรื่องที่สร้างก่อนมีโมดูลนี้ ยังไม่มี project_id แต่เลือกชื่อโครงการไว้)"""
    from app.models import Procurement
    from sqlalchemy import or_, and_
    from sqlalchemy.orm import object_session
    db = object_session(project)
    if db is None:
        return []
    cond = Procurement.project_id == project.id
    if project.name:
        cond = or_(cond, and_(Procurement.project_id.is_(None),
                              Procurement.project_name == project.name,
                              Procurement.fiscal_year == project.plan_year))
    return db.query(Procurement).filter(cond).order_by(Procurement.id.desc()).all()


def project_spent(project) -> float:
    """ยอดใช้ไปของโครงการ = ที่บันทึกในระบบ + ใช้ไปก่อนเริ่มใช้ระบบ (ยอดตั้งต้นของโรงเรียนที่เริ่มกลางปี)

    ทุกหน้าที่โชว์ "ใช้ไป" (หน้าโครงการ รายการโครงการ รายงานสรุป) เรียกตัวนี้ตัวเดียว
    จึงตรงกันเสมอ
    """
    return round(project_spent_in_system(project) + float(getattr(project, "spent_before", 0) or 0), 2)


def project_spent_in_system(project) -> float:
    """Budget consumed in-system: ledger payments plus unpaid source documents
    (รวมเรื่องที่ทำเครื่องหมาย "จ่ายแล้วก่อนเริ่มใช้ระบบ" ด้วย ยอดใช้ไปจึงเท่าเดิม)"""
    info = project_money_summary(project)
    return round(info['paid'] + info['waiting'] + info['paid_pre'], 2)


def project_txn_spent(project, db=None) -> float:
    """เงินที่จ่ายจากโครงการนี้โดยลงในทะเบียนคุมเงินตรง ๆ (ไม่ได้ผ่านบันทึกขอเบิกจ่าย)

    ข้ามรายการที่ผูกกับบันทึกเบิกจ่ายอยู่แล้ว (disburse_id) เพราะนับไปแล้วข้างบน
    """
    from sqlalchemy.orm import object_session

    from app.models import FinanceTxn
    db = db or object_session(project)
    if db is None:
        return 0.0
    rows = (db.query(FinanceTxn)
            .filter(FinanceTxn.project_id == project.id,
                    FinanceTxn.kind == "out",
                    FinanceTxn.disburse_id.is_(None),
                    FinanceTxn.loan_id.is_(None)).all())
    return round(sum(t.amount or 0 for t in rows), 2)


def loan_parts(loan) -> dict:
    """แยกยอดเงินยืม 1 สัญญา: receipts = ใบสำคัญที่ส่งใช้, cash = เงินสดที่คืน, open = ยังไม่ส่งใช้"""
    rets = getattr(loan, "returns", None) or []
    receipts = round(sum(float(r.amount or 0) for r in rets if (r.kind or "") == "ใบสำคัญ"), 2)
    cash = round(sum(float(r.amount or 0) for r in rets if (r.kind or "") != "ใบสำคัญ"), 2)
    open_ = round(max(float(loan.amount or 0) - receipts - cash, 0), 2)
    return {"receipts": receipts, "cash": cash, "open": open_, "used": round(receipts + open_, 2)}


def project_loans(project, db=None) -> list:
    from sqlalchemy.orm import object_session
    from app.models import MoneyLoan
    db = db or object_session(project)
    if db is None:
        return []
    return db.query(MoneyLoan).filter(MoneyLoan.project_id == project.id).order_by(MoneyLoan.date, MoneyLoan.id).all()


def project_remaining(project) -> float:
    return round(project_budget(project) - project_spent(project), 2)


def project_money_summary(project):
    """Separate recorded cash, unpaid document amounts, and legacy opening spend.

    Pending includes drafts for compatibility with existing budget reservation;
    it is not an assertion that a legal obligation or payment has occurred.
    Each transaction is attributed once: direct project, memo, then procurement.
    """
    from sqlalchemy.orm import object_session
    from app.models import FinanceTxn, DisburseMemo, LunchLedger
    db = object_session(project)
    before = float(getattr(project, 'spent_before', 0) or 0)
    sources, paid_by = {}, {}
    paid = 0.0
    if db is not None:
        procs = project_procurements(project)
        proc_ids = {p.id for p in procs}
        sources = {('proc', p.id): float(p.total_amount or 0) for p in procs}
        memos = {m.id: m for m in db.query(DisburseMemo)}
        for m in memos.values():
            if m.project_id == project.id and not m.procurement_id:
                sources[('memo', m.id)] = float(m.amount or 0)
        lunch = {l.finance_txn_id: l.procurement_id for l in db.query(LunchLedger)
                 if l.finance_txn_id and l.procurement_id}
        for t in db.query(FinanceTxn).filter_by(kind='out'):
            if t.loan_id:                 # จ่ายเงินยืม: นับจากสัญญายืมด้านล่างแทน
                continue
            m = memos.get(t.disburse_id)
            proc_id = (m.procurement_id if m else None) or lunch.get(t.id)
            if t.project_id:
                belongs = t.project_id == project.id
            elif m and m.project_id:
                belongs = m.project_id == project.id
            else:
                belongs = proc_id in proc_ids
            if not belongs:
                continue
            value = float(t.amount or 0)
            paid += value
            key = ('proc', proc_id) if proc_id in proc_ids else ('memo', m.id) if m else None
            if key in sources:
                paid_by[key] = paid_by.get(key, 0) + value
    # เรื่องพัสดุที่ "จ่ายแล้วก่อนเริ่มใช้ระบบ": ส่วนที่ยังไม่มีรายการจ่ายในระบบ ไม่นับเป็นรอจ่าย
    # ไปรวมในยอด "ก่อนเริ่มระบบ" แทน (หน้าโครงการและรายงานแสดงในช่องนั้นอยู่แล้ว)
    pre_keys = {('proc', p.id) for p in (procs if db is not None else []) if getattr(p, 'paid_before_system', False)}
    paid_pre = sum(max(value - paid_by.get(key, 0), 0) for key, value in sources.items() if key in pre_keys)
    waiting = sum(max(value - paid_by.get(key, 0), 0) for key, value in sources.items() if key not in pre_keys)
    for ln in (project_loans(project, db) if db is not None else []):
        parts = loan_parts(ln)
        paid += parts["receipts"]
        waiting += parts["open"]
    used = round(before + paid + waiting + paid_pre, 2)
    return dict(paid=round(paid,2), waiting=round(waiting,2), before=round(before + paid_pre, 2),
                paid_pre=round(paid_pre, 2), spent_before=round(before, 2),
                used=used, remaining=round(project_budget(project)-used,2))
