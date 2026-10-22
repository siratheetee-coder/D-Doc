# -*- coding: utf-8 -*-
""""จ่ายแล้วก่อนเริ่มใช้ระบบ": ทำเครื่องหมายให้เรื่องพัสดุที่จ่ายเงินไปก่อนเริ่มลงเงินในระบบ

ไม่สร้างรายการเงิน (ยอดยกมาหักเงินก้อนนั้นไปแล้ว) แค่ย้ายจาก "รอจ่าย" ไปนับเป็น "ก่อนเริ่มระบบ"
งบโครงการที่ใช้ไปเท่าเดิม (ดู budget.project_money_summary)
เรื่องที่มีรายการจ่ายในระบบแล้ว ทำเครื่องหมายไม่ได้ (จ่ายในระบบแล้ว ไม่ใช่จ่ายก่อนเริ่มใช้ระบบ)
"""
from datetime import datetime


def proc_date(p):
    from app.services.project_realign import proc_date as _d
    return _d(p)


def default_cutoff(db):
    """วันเริ่มใช้ระบบ (เดา) = 1 ต.ค. ของปีงบที่เริ่มกรอกยอดยกมา ถ้าเดาไม่ได้ใช้ 1 ต.ค. ของปีงบปัจจุบัน"""
    from app.services.finance_health import _joined
    from app.thai_utils import current_fiscal_year
    cur = current_fiscal_year()
    for fy in (cur, cur - 1, cur - 2):
        if _joined(db, fy):
            return datetime(fy - 544, 10, 1)
    return datetime(cur - 544, 10, 1)


def paid_in_system(db) -> set:
    """id เรื่องพัสดุที่มีรายการจ่ายในทะเบียนคุมเงินแล้ว (ผ่านบันทึกขอเบิกจ่าย หรือผ่านงานอาหารกลางวัน)"""
    from app.models import DisburseMemo, FinanceTxn, LunchLedger
    ids = {pid for (pid,) in db.query(DisburseMemo.procurement_id)
           .join(FinanceTxn, FinanceTxn.disburse_id == DisburseMemo.id)
           .filter(DisburseMemo.procurement_id.isnot(None))}
    ids |= {pid for (pid,) in db.query(LunchLedger.procurement_id)
            .filter(LunchLedger.procurement_id.isnot(None), LunchLedger.finance_txn_id.isnot(None))}
    return ids


def candidates(db, cutoff) -> list:
    """เรื่องที่ลงวันที่ก่อนวันเริ่มใช้ระบบ ยังไม่มีรายการจ่าย และยังไม่ได้ทำเครื่องหมาย (ใหม่ไปเก่า)"""
    from app.models import Procurement
    paid = paid_in_system(db)
    rows = []
    for p in db.query(Procurement).filter(Procurement.paid_before_system.isnot(True)):
        d = proc_date(p)
        if d and d < cutoff and p.id not in paid:
            rows.append(p)
    return sorted(rows, key=lambda p: (proc_date(p), p.id), reverse=True)


def marked(db) -> list:
    from app.models import Procurement
    rows = db.query(Procurement).filter(Procurement.paid_before_system.is_(True)).all()
    return sorted(rows, key=lambda p: (proc_date(p) or datetime.min, p.id), reverse=True)


def set_mark(db, ids, on=True) -> int:
    """ทำเครื่องหมาย/ยกเลิก · คืนจำนวนเรื่องที่เปลี่ยน · เรื่องที่มีรายการจ่ายในระบบแล้วข้าม (ถ้าจะทำเครื่องหมาย)"""
    from app.models import Procurement
    paid = paid_in_system(db) if on else set()
    n = 0
    for pid in {int(i) for i in ids}:
        p = db.get(Procurement, pid)
        if not p or bool(p.paid_before_system) == on:
            continue
        if on and p.id in paid:
            raise ValueError(f"เรื่องเลขที่ {p.memo_no or '-'} มีรายการจ่ายในทะเบียนคุมเงินแล้ว ทำเครื่องหมายไม่ได้")
        p.paid_before_system = on
        p.paid_before_marked_at = datetime.now() if on else None
        n += 1
    db.commit()
    return n
