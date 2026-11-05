# -*- coding: utf-8 -*-
"""สถานะเรื่องจัดซื้อตามการจ่ายเงินจริง

เดิมสถานะเรื่องจัดซื้อเปลี่ยนเองจาก dropdown อย่างเดียว ลงจ่ายบันทึกขอเบิกแล้วเรื่องยังค้าง "ร่าง"
ที่นี่ฟังทุกการบันทึกของบันทึกขอเบิก (DisburseMemo) ที่ผูกเรื่องจัดซื้อ แล้วปรับสถานะเรื่องนั้น
- บันทึกขอเบิกของเรื่องจ่ายแล้วทุกฉบับ และยอดรวมครบวงเงินเรื่อง -> "เบิกจ่ายแล้ว"
- เคยเป็น "เบิกจ่ายแล้ว" แต่ยกเลิกการจ่าย/ลบจนไม่ครบ -> "ตรวจรับแล้ว" (มีวันตรวจรับ) หรือ "อนุมัติ"
  (ถ้าไม่มีบันทึกขอเบิกเหลือเลย ไม่แตะ เพราะอาจตั้งเองหรือจ่ายทางอื่น เช่น จ่ายก่อนเริ่มระบบ)
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

PAID = "เบิกจ่ายแล้ว"
_KEY = "proc_paid_sync"


def status_for(proc, memos):
    """สถานะที่ควรเป็น หรือ None = ไม่ต้องเปลี่ยน"""
    if not memos:
        return None
    total = round(float(proc.total_amount or 0), 2)
    amount = round(sum(float(m.amount or 0) for m in memos), 2)
    full = all((m.status or "") == "จ่ายแล้ว" for m in memos) and amount >= total - 1
    if full:
        return PAID if proc.status != PAID else None
    if proc.status == PAID:
        return "ตรวจรับแล้ว" if proc.inspect_date else "อนุมัติ"
    return None


def sync(db, proc_ids):
    from app.models import DisburseMemo, Procurement
    for pid in proc_ids:
        proc = db.get(Procurement, pid)
        if proc is None:
            continue
        memos = db.query(DisburseMemo).filter(DisburseMemo.procurement_id == pid).all()
        new = status_for(proc, memos)
        if new:
            proc.status = new


def _proc_ids(obj):
    from sqlalchemy import inspect
    ids = {obj.procurement_id} if obj.procurement_id else set()
    hist = inspect(obj).attrs.procurement_id.history
    ids.update(x for x in (hist.deleted or ()) if x)
    return ids


@event.listens_for(Session, "before_flush")
def _collect(db, _ctx, _inst):
    from app.models import DisburseMemo
    ids = set()
    for obj in list(db.new) + list(db.dirty) + list(db.deleted):
        if isinstance(obj, DisburseMemo):
            ids |= _proc_ids(obj)
    if ids:
        db.info.setdefault(_KEY, set()).update(ids)


@event.listens_for(Session, "after_flush_postexec")
def _apply(db, _ctx):
    ids = db.info.pop(_KEY, None)
    if ids:
        sync(db, ids)          # เปลี่ยนสถานะเรื่อง -> session วนบันทึกรอบถัดไปในการ flush เดียวกัน


def backfill(engine) -> None:
    """ข้อมูลเดิม: เรื่องที่บันทึกขอเบิกจ่ายครบแล้วแต่สถานะยังค้าง (รันซ้ำได้ ไม่เปลี่ยนซ้ำ)"""
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT p.id, p.total_amount, p.status, "
            "       SUM(COALESCE(m.amount, 0)), "
            "       SUM(CASE WHEN m.status = 'จ่ายแล้ว' THEN 0 ELSE 1 END) "
            "FROM procurement p JOIN disburse_memo m ON m.procurement_id = p.id "
            "GROUP BY p.id").fetchall()
        for pid, total, status, amount, unpaid in rows:
            if status != PAID and not unpaid and round(amount or 0, 2) >= round(total or 0, 2) - 1:
                conn.exec_driver_sql("UPDATE procurement SET status = ? WHERE id = ?", (PAID, pid))
