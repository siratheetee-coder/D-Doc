# -*- coding: utf-8 -*-
"""ธนาคารโรงเรียน (เงินออมนักเรียน) แบบโรงเรียนเก็บเงินเอง

กติกา:
- ฝาก/ถอนรายคน ยอดคงเหลือคิดจากรายการที่ไม่ถูกยกเลิก
- ถอนเกินยอดคงเหลือไม่ได้
- แก้ไขไม่ได้ ผิดให้ยกเลิก (เก็บเหตุผล ผู้ยกเลิก เวลา) แล้วบันทึกใหม่
- เดือนที่ปิดยอดแล้ว บันทึกหรือยกเลิกรายการในเดือนนั้นไม่ได้
- เป็นเงินของนักเรียน ไม่ปนกับทะเบียนคุมเงินของโรงเรียน
"""
from datetime import datetime

from sqlalchemy import func

from app.models import SavingsTxn, SavingsLock

KIND_LABEL = {"dep": "ฝาก", "wd": "ถอน"}


def _signed(kind, amount):
    return amount if kind == "dep" else -amount


def balances(db, ids, *, upto=None) -> dict:
    """ยอดคงเหลือรายคน upto=ISO นับถึงวันนั้น (รวมวันนั้น)"""
    ids = [i for i in ids if i]
    out = {i: 0.0 for i in ids}
    if not ids:
        return out
    q = db.query(SavingsTxn.student_id, SavingsTxn.kind, func.sum(SavingsTxn.amount)).filter(
        SavingsTxn.student_id.in_(ids), SavingsTxn.void == False)  # noqa: E712
    if upto:
        q = q.filter(SavingsTxn.date <= upto)
    for sid, kind, tot in q.group_by(SavingsTxn.student_id, SavingsTxn.kind):
        out[sid] = round(out.get(sid, 0.0) + _signed(kind, tot or 0.0), 2)
    return out


def is_locked(db, iso: str) -> bool:
    return bool(iso) and db.query(SavingsLock).filter_by(month=iso[:7]).first() is not None


def parse_amount(text) -> float | None:
    """'1,250.50' -> 1250.5  ว่าง -> 0  ผิดรูป/ติดลบ -> None"""
    t = str(text or "").replace(",", "").strip()
    if not t:
        return 0.0
    try:
        v = round(float(t), 2)
    except ValueError:
        return None
    return v if v >= 0 and v == v and v != float("inf") else None


def add(db, *, student_id, kind, amount, day, note="", by_name="", by_pid=None, balance=None):
    """เพิ่มรายการ คืน (txn, error) balance=ยอดคงเหลือก่อนหน้า (ส่งมาเพื่อลด query)"""
    if kind not in KIND_LABEL:
        return None, "ประเภทรายการไม่ถูกต้อง"
    if not amount or amount <= 0:
        return None, "จำนวนเงินต้องมากกว่า 0"
    if is_locked(db, day):
        return None, "เดือนนี้ปิดยอดแล้ว บันทึกเพิ่มไม่ได้"
    if kind == "wd":
        bal = balances(db, [student_id])[student_id] if balance is None else balance
        if amount > bal + 0.001:
            return None, f"ถอนเกินยอดคงเหลือ ({bal:,.2f} บาท)"
    t = SavingsTxn(student_id=student_id, kind=kind, amount=amount, date=day,
                   note=(note or "").strip()[:200], by_name=by_name, by_pid=by_pid)
    db.add(t)
    db.flush()
    return t, ""


def void(db, t: SavingsTxn, *, reason, by_name):
    """ยกเลิกรายการ คืนข้อความผิดพลาด หรือ '' ถ้าสำเร็จ"""
    if t.void:
        return "รายการนี้ยกเลิกไปแล้ว"
    if is_locked(db, t.date):
        return "เดือนนี้ปิดยอดแล้ว ยกเลิกรายการไม่ได้"
    reason = (reason or "").strip()
    if not reason:
        return "กรอกเหตุผลที่ยกเลิก"
    if t.kind == "dep":
        # ยกเลิกเงินฝากต้องไม่ทำให้ยอดติดลบ (เงินถูกถอนไปแล้ว)
        bal = balances(db, [t.student_id])[t.student_id]
        if bal - t.amount < -0.001:
            return "ยกเลิกไม่ได้ เพราะยอดคงเหลือจะติดลบ (มีการถอนไปแล้ว) ให้ยกเลิกรายการถอนก่อน"
    t.void, t.void_reason, t.void_by, t.void_at = True, reason[:200], by_name, datetime.now()
    return ""


def history(db, sid):
    """รายการทั้งหมดของนักเรียน เรียงตามวัน พร้อมยอดคงเหลือหลังแต่ละรายการ (ไม่นับที่ยกเลิก)"""
    rows = (db.query(SavingsTxn).filter(SavingsTxn.student_id == sid)
            .order_by(SavingsTxn.date, SavingsTxn.id).all())
    bal, out = 0.0, []
    for t in rows:
        if not t.void:
            bal = round(bal + _signed(t.kind, t.amount), 2)
        out.append({"t": t, "bal": bal})
    return out


def day_totals(db, day, ids=None) -> dict:
    """ยอดฝาก/ถอนของวัน {student_id: {"dep": x, "wd": y}}"""
    q = db.query(SavingsTxn).filter(SavingsTxn.date == day, SavingsTxn.void == False)  # noqa: E712
    if ids is not None:
        q = q.filter(SavingsTxn.student_id.in_(list(ids) or [0]))
    out = {}
    for t in q:
        d = out.setdefault(t.student_id, {"dep": 0.0, "wd": 0.0})
        d[t.kind] = round(d[t.kind] + t.amount, 2)
    return out


def month_summary(db, month: str) -> dict:
    """ยอดรวมทั้งโรงเรียนของเดือน YYYY-MM"""
    q = db.query(SavingsTxn.kind, func.sum(SavingsTxn.amount), func.count(SavingsTxn.id)).filter(
        SavingsTxn.date.like(month + "-%"), SavingsTxn.void == False).group_by(SavingsTxn.kind)  # noqa: E712
    out = {"dep": 0.0, "wd": 0.0, "n": 0}
    for kind, tot, n in q:
        out[kind] = round(tot or 0.0, 2)
        out["n"] += n
    return out


def total_balance(db, *, upto=None) -> float:
    q = db.query(SavingsTxn.kind, func.sum(SavingsTxn.amount)).filter(SavingsTxn.void == False)  # noqa: E712
    if upto:
        q = q.filter(SavingsTxn.date <= upto)
    return round(sum(_signed(k, v or 0.0) for k, v in q.group_by(SavingsTxn.kind)), 2)
