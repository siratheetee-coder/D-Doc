# -*- coding: utf-8 -*-
"""
project_money.py - โครงการนี้ใช้เงินจากหมวดไหน (เชื่อมโครงการกับทะเบียนคุมเงิน)

เดิมฟอร์มเบิกจ่ายถามแยก 4 ช่อง (แหล่งเงิน / บัญชี / หมวด / โครงการ) ที่ไม่รู้จักกัน
ผู้ใช้เลือกโครงการแล้วต้องไปเลือกบัญชีกับหมวดเองอีก ทั้งที่ระบบรู้อยู่แล้ว

ระบบรู้จากบันทึกขอเบิกจ่าย/รายการจ่ายของโครงการนี้ที่เคยระบุหมวดไว้ โรงเรียนไม่ต้องตั้งค่าอะไรล่วงหน้า
เลือกหมวดครั้งแรกครั้งเดียว ครั้งต่อไประบบจำให้
(เดิมมีการจัดสรรเงินให้โครงการล่วงหน้าด้วย เลิกใช้แล้วเพราะตัวเลขไม่ตรงกับเงินจริง ครูงง)

หมวด (AccountItem) แยกรายปีงบ หมวดที่จำไว้จากปีงบก่อนจึงต้องหา "หมวดชื่อเดียวกันในปีงบนี้"
ไม่งั้นจะหักเงินลงหมวดของปีที่ปิดไปแล้ว (แผนปีการศึกษาคร่อมสองปีงบ เจอกรณีนี้ทุกปี)
"""
from sqlalchemy import or_

from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Procurement

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

    # เคยใช้ครั้งก่อน (ล่าสุดก่อน) · นับทั้งบันทึกที่ผูกโครงการตรง และที่ผูกผ่านเรื่องจัดซื้อ
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


def project_cash(db, projects, fy) -> dict:
    """กล่องสรุปหน้าโครงการหลัก: โครงการยังต้องใช้เงินเท่าไร เทียบกับเงินในหมวดที่โครงการใช้จ่าย

    ไม่จัดสรรเงินให้โครงการล่วงหน้า (แบบที่ครูการเงินทำจริง ดูงบโครงการกับเงินในบัญชีแยกกัน)
    นับเฉพาะโครงการที่รู้แล้วว่าใช้เงินหมวดไหน (เคยทำบันทึกขอเบิก/จ่ายเงินที่ระบุหมวด) ทั้งสองฝั่งจึงมาจากชุดเดียวกัน
    เดิมนับงบทุกโครงการแต่นับเงินแค่หมวดที่เคยจ่าย บ้านหินลาดเลยขึ้นว่าขาดเงินเกินจริง
    เพราะโครงการอาหารกลางวันยังไม่เคยจ่ายในระบบ เงินอาหารกลางวันจึงไม่ถูกนับ แต่งบถูกนับ

    คืน {need, n, rows: [{item, remain}], cash, gap, skipped}
      gap > 0 = เงินในหมวดยังไม่พอ  skipped = โครงการที่ยังต้องใช้เงินแต่ยังไม่รู้หมวด (ไม่นับ)
    """
    from app.services.asset_utils import item_remaining_asof
    from app.services.budget import project_budget, project_spent
    need, n, skipped, items = 0.0, 0, 0, {}
    for p in projects:
        left = round(project_budget(p) - project_spent(p), 2)
        if left <= 0:
            continue
        srcs = [x for x in project_sources(db, p.id, fy) if x["item_id"]]
        if not srcs:
            skipped += 1
            continue
        need += left
        n += 1
        for x in srcs:
            items.setdefault(x["item_id"], None)
    rows = []
    for iid in items:
        it = db.get(AccountItem, iid)
        rows.append({"item": it, "remain": item_remaining_asof(it)})
    rows.sort(key=lambda x: -x["remain"])
    need = round(need, 2)
    cash = round(sum(x["remain"] for x in rows), 2)
    return {"need": need, "n": n, "rows": rows, "cash": cash, "gap": round(need - cash, 2), "skipped": skipped}
