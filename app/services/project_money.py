# -*- coding: utf-8 -*-
"""
project_money.py - โครงการนี้ใช้เงินจากหมวดไหน (เชื่อมโครงการกับทะเบียนคุมเงิน)

เดิมฟอร์มเบิกจ่ายถามแยก 4 ช่อง (แหล่งเงิน / บัญชี / หมวด / โครงการ) ที่ไม่รู้จักกัน
ผู้ใช้เลือกโครงการแล้วต้องไปเลือกบัญชีกับหมวดเองอีก ทั้งที่ระบบรู้อยู่แล้ว

ระบบรู้ได้จากสองทาง เรียงตามความน่าเชื่อถือ
  1. จัดสรรไว้ในแผน   โครงการได้รับเงินจากหมวดไหน (ProjectFunding -> PlanFunding.account_item_id)
  2. เคยใช้ครั้งก่อน   บันทึกขอเบิกจ่าย/รายการจ่ายของโครงการนี้ที่เคยระบุหมวดไว้
ทางที่ 2 ทำให้โรงเรียนไม่ต้องตั้งค่าอะไรล่วงหน้า เลือกหมวดครั้งแรกครั้งเดียว ครั้งต่อไประบบจำให้

หมวด (AccountItem) แยกรายปีงบ หมวดที่จำไว้จากปีงบก่อนจึงต้องหา "หมวดชื่อเดียวกันในปีงบนี้"
ไม่งั้นจะหักเงินลงหมวดของปีที่ปิดไปแล้ว (แผนปีการศึกษาคร่อมสองปีงบ เจอกรณีนี้ทุกปี)
"""
from sqlalchemy import or_

from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Procurement

try:        # ระบบจัดสรรงบให้โครงการ (หน้างบประมาณที่ใช้จัดทำแผน) ยังไม่มีในทุกเครื่อง
    from app.models import PlanFunding, ProjectFunding
except ImportError:                                  # ไม่มีก็ใช้แค่ "เคยใช้ครั้งก่อน" ไปก่อน
    PlanFunding = ProjectFunding = None

ALLOCATED = "จัดสรรไว้ในแผน"
USED_BEFORE = "เคยใช้ครั้งก่อน"


def _same_item_in_year(db, item, fy):
    """หมวดเดียวกันในปีงบ fy (ชื่อเดียวกัน บัญชีเดียวกัน หมวดแม่ชื่อเดียวกัน) ไม่พบคืน None"""
    if item is None:
        return None
    if item.fiscal_year == fy:
        return item
    parent_name = item.parent.name if item.parent_id and item.parent else None
    for cand in db.query(AccountItem).filter_by(account_id=item.account_id, fiscal_year=fy,
                                                name=item.name).all():
        cp = cand.parent.name if cand.parent_id and cand.parent else None
        if cp == parent_name:
            return cand
    return None


def _entry(account, item, why):
    label = account.name + (f" / {item.name}" if item else "")
    return {"account_id": account.id, "account_name": account.name,
            "item_id": item.id if item else None, "item_name": item.name if item else "",
            "label": label, "why": why}


def project_sources(db, project_id, fy) -> list:
    """หมวดที่โครงการนี้ใช้ ในปีงบ fy · เรียงจากน่าเชื่อถือที่สุด ไม่ซ้ำกัน

    คืน [{account_id, account_name, item_id, item_name, label, why}]
    item_id เป็น None ได้ (บัญชีที่ไม่ได้แบ่งหมวด)
    """
    if not project_id:
        return []
    out, seen = [], set()

    def add(account, item, why):
        if account is None:
            return
        key = (account.id, item.id if item else None)
        if key in seen:
            return
        seen.add(key)
        out.append(_entry(account, item, why))

    # 1) จัดสรรไว้ในแผน
    rows = [] if PlanFunding is None else (db.query(PlanFunding)
            .join(ProjectFunding, ProjectFunding.funding_id == PlanFunding.id)
            .filter(ProjectFunding.project_id == project_id, ProjectFunding.amount > 0,
                    PlanFunding.account_item_id.isnot(None))
            .order_by(ProjectFunding.amount.desc()).all())
    for f in rows:
        it = _same_item_in_year(db, db.get(AccountItem, f.account_item_id), fy)
        if it is not None:
            add(it.account, it, ALLOCATED)

    # 2) เคยใช้ครั้งก่อน (ล่าสุดก่อน) · นับทั้งบันทึกที่ผูกโครงการตรง และที่ผูกผ่านเรื่องจัดซื้อ
    proc_ids = [p.id for p in db.query(Procurement.id).filter(Procurement.project_id == project_id)]
    memo_q = db.query(DisburseMemo).filter(DisburseMemo.account_id.isnot(None))
    cond = DisburseMemo.project_id == project_id
    if proc_ids:
        cond = or_(cond, DisburseMemo.procurement_id.in_(proc_ids))
    memo_q = memo_q.filter(cond)
    history = [(m.id, m.account_id, m.item_id) for m in memo_q.order_by(DisburseMemo.id.desc()).all()]
    history += [(t.id, t.account_id, t.item_id) for t in
                db.query(FinanceTxn).filter(FinanceTxn.project_id == project_id,
                                            FinanceTxn.kind == "out")
                .order_by(FinanceTxn.id.desc()).all()]
    for _, acc_id, item_id in history:
        acc = db.get(FinanceAccount, acc_id)
        if item_id:
            it = _same_item_in_year(db, db.get(AccountItem, item_id), fy)
            if it is None:
                continue          # หมวดของปีก่อนที่ปีนี้ไม่มีแล้ว ปล่อยให้ผู้ใช้เลือกเอง
            add(acc, it, USED_BEFORE)
        else:
            add(acc, None, USED_BEFORE)
    return out
