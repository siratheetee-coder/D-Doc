# -*- coding: utf-8 -*-
"""คุมเงินภาษีหัก ณ ที่จ่ายที่โรงเรียนหักไว้ จนนำส่งสรรพากร

แนวเดียวกับหมวด e-Budget: รับเข้าบัญชี "เงินภาษีหัก ณ ที่จ่าย" (3.8) ตอนลงจ่ายบันทึกขอเบิก
แล้วจ่ายออก (4.7) ตอนนำส่ง เริ่มคุมตั้งแต่วันที่โรงเรียนเลือก (School.wht_track_from)
กันซ้ำกับโรงเรียนที่ลงรายการภาษีเองไว้ก่อน
sync() เรียกซ้ำได้ ไม่สร้างรายการซ้ำ
"""
from collections import OrderedDict
from datetime import datetime

from app.models import DisburseMemo, FinanceAccount, FinanceTxn, School
from app.thai_utils import current_fiscal_year

ACCOUNT_NAME = "เงินภาษีหัก ณ ที่จ่าย"
IN_CAT = "รับภาษีหัก ณ ที่จ่าย"
OUT_CAT = "นำส่งภาษีหัก ณ ที่จ่าย"


def start_date(school):
    s = (getattr(school, "wht_track_from", "") or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError:
        return None


def account(db, create=True):
    for a in db.query(FinanceAccount).all():
        n = a.name or ""
        if "ภาษีหัก" in n or "หัก ณ ที่จ่าย" in n:
            return a
    if not create:
        return None
    a = FinanceAccount(name=ACCOUNT_NAME, deposit_type="cash", fund_type="เงินนอกงบประมาณ",
                       note="ระบบสร้างให้ ใช้คุมภาษีหัก ณ ที่จ่ายที่รอนำส่งสรรพากร")
    db.add(a)
    db.flush()
    return a


def _paid_date(db, memo):
    d = [t.date for t in db.query(FinanceTxn).filter(FinanceTxn.disburse_id == memo.id,
                                                     FinanceTxn.kind == "out") if t.date]
    return min(d) if d else None


def sync(db) -> int:
    """ให้รายการรับภาษีตรงกับบันทึกขอเบิกที่ลงจ่ายแล้ว คืนจำนวนที่เปลี่ยน (ไม่ commit)"""
    school = db.query(School).first()
    start = start_date(school) if school else None
    have = {t.wht_memo_id: t for t in db.query(FinanceTxn).filter(FinanceTxn.wht_memo_id.isnot(None))}
    if start is None and not have:
        return 0
    changed = 0
    for t in db.query(FinanceTxn).filter(FinanceTxn.wht_remit_id.isnot(None)):
        if db.get(FinanceTxn, t.wht_remit_id) is None:   # รายการนำส่งถูกลบจากทะเบียน กลับเป็นรอนำส่ง
            t.wht_remit_id = None; changed += 1
    want = {}
    if start is not None:
        for m in db.query(DisburseMemo).filter(DisburseMemo.wht > 0):
            paid = _paid_date(db, m)
            if paid and paid >= start:
                want[m.id] = (m, paid)
    for mid, t in have.items():
        if t.wht_remit_id:          # นำส่งแล้ว ไม่แตะ
            continue
        if mid not in want:
            db.delete(t); changed += 1
            continue
        m, paid = want[mid]
        amt = round(float(m.wht or 0), 2)
        if round(t.amount or 0, 2) != amt or t.date != paid or t.ref != (m.memo_no or ""):
            t.amount, t.date, t.ref = amt, paid, m.memo_no or ""
            t.fiscal_year = m.fiscal_year
            changed += 1
    acc = None
    for mid, (m, paid) in want.items():
        if mid in have:
            continue
        acc = acc or account(db)
        db.add(FinanceTxn(account_id=acc.id, fiscal_year=m.fiscal_year, kind="in",
                          amount=round(float(m.wht or 0), 2), date=paid, category=IN_CAT,
                          ref=m.memo_no or "", note=f"ภาษีหัก ณ ที่จ่าย {m.payee or ''} ({m.subject or ''})".strip(),
                          place="cash", eb_code="3.8", wht_memo_id=m.id))
        changed += 1
    if changed:
        db.flush()
    return changed


def pending(db):
    """ภาษีที่รับไว้ยังไม่นำส่ง แยกเดือน {YYYY-MM: [txn]}"""
    out = OrderedDict()
    q = (db.query(FinanceTxn).filter(FinanceTxn.wht_memo_id.isnot(None), FinanceTxn.wht_remit_id.is_(None))
         .order_by(FinanceTxn.date, FinanceTxn.id))
    for t in q:
        out.setdefault(t.date.strftime("%Y-%m") if t.date else "", []).append(t)
    return out


def remitted(db, limit=24):
    return (db.query(FinanceTxn).filter(FinanceTxn.category == OUT_CAT, FinanceTxn.kind == "out")
            .order_by(FinanceTxn.date.desc(), FinanceTxn.id.desc()).limit(limit).all())


def remit(db, month: str, when: datetime, ref: str = ""):
    items = pending(db).get(month) or []
    if not items:
        raise ValueError("ไม่มีภาษีรอนำส่งของเดือนนี้")
    total = round(sum(t.amount or 0 for t in items), 2)
    acc = db.get(FinanceAccount, items[0].account_id)
    y, mo = month.split("-")
    out = FinanceTxn(account_id=acc.id, fiscal_year=current_fiscal_year(when), kind="out", amount=total, date=when,
                     category=OUT_CAT, ref=ref, place="cash", eb_code="4.7",
                     note=f"นำส่งภาษีหัก ณ ที่จ่าย เดือน {int(mo)}/{int(y) + 543} ({len(items)} รายการ)")
    db.add(out); db.flush()
    for t in items:
        t.wht_remit_id = out.id
    db.flush()
    return out


def undo(db, txn_id: int):
    out = db.get(FinanceTxn, txn_id)
    if not out or out.category != OUT_CAT:
        raise ValueError("ไม่พบรายการนำส่ง")
    for t in db.query(FinanceTxn).filter(FinanceTxn.wht_remit_id == out.id):
        t.wht_remit_id = None
    db.delete(out); db.flush()
