# -*- coding: utf-8 -*-
"""
money_place.py - เงินของบัญชีหนึ่งอยู่ที่ไหนบ้าง (เงินสด / เงินฝากธนาคาร / เงินฝากส่วนราชการผู้เบิก)

ที่เก็บของแต่ละรายการรับ-จ่าย:
  FinanceTxn.place ถ้ากรอกไว้ มิฉะนั้นใช้ที่เก็บของหมวด แล้วจึงที่เก็บของบัญชี (ข้อมูลเดิมจึงคิดเหมือนเดิม)
ยอดยกมา: ยอดยกมาเฉพาะหมวดอยู่ที่ที่เก็บของหมวด ส่วนที่เหลือของบัญชีอยู่ที่ที่เก็บของบัญชี
ถอน/ฝากระหว่างที่เก็บ = รายการจ่ายจากที่หนึ่ง + รับเข้าอีกที่ ในบัญชีเดียวกัน (ไม่นับเป็นรายรับ-รายจ่าย)
"""
PLACES = {"cash": "เงินสด", "bank": "เงินฝากธนาคาร", "agency": "เงินฝากส่วนราชการผู้เบิก"}


def _valid(p):
    return p if p in PLACES else None


def account_place(account) -> str:
    return _valid(getattr(account, "deposit_type", None)) or "bank"


def item_place(item) -> str:
    return _valid(getattr(item, "deposit_type", None)) or account_place(item.account)


def txn_place(t) -> str:
    p = _valid(getattr(t, "place", None))
    if p:
        return p
    item = getattr(t, "item", None)
    return item_place(item) if item is not None else account_place(t.account)


def blank() -> dict:
    return {k: 0.0 for k in PLACES}


def _before(t, as_of):
    from app.services.asset_utils import _before as same_day_or_before   # นับทั้งวันของวันที่รายงาน
    return same_day_or_before(t, as_of)


def _sign(t):
    return (t.amount or 0) if t.kind == "in" else -(t.amount or 0)


def opening_by_place(account, fy) -> dict:
    """ยอดยกมาของบัญชีในปีงบ fy แยกที่เก็บ"""
    from app.services.asset_utils import opening_for
    out = blank()
    total = float(opening_for(account, fy) or 0)
    for it in getattr(account, "items", None) or []:
        if it.fiscal_year == fy and it.opening_balance:
            out[item_place(it)] += float(it.opening_balance)
            total -= float(it.opening_balance)
    out[account_place(account)] += total
    return out


def account_by_place(account, fy, as_of=None) -> dict:
    """ยอดคงเหลือของบัญชี ณ as_of (ในปีงบ fy) แยกที่เก็บ"""
    out = opening_by_place(account, fy)
    for t in account.txns:
        if t.fiscal_year == fy and _before(t, as_of):
            out[txn_place(t)] += _sign(t)
    return {k: round(v, 2) for k, v in out.items()}


def item_by_place(item, as_of=None) -> dict:
    """ยอดคงเหลือของหมวด ณ as_of แยกที่เก็บ"""
    out = blank()
    out[item_place(item)] += float(item.opening_balance or 0)
    for t in item.account.txns:
        if t.item_id == item.id and t.fiscal_year == item.fiscal_year and _before(t, as_of):
            out[txn_place(t)] += _sign(t)
    return {k: round(v, 2) for k, v in out.items()}


def used_places(account, fy) -> list:
    """ที่เก็บที่บัญชีนี้ใช้จริงในปีงบนี้ (ที่ตั้งไว้ + ที่มีรายการ) เรียงตามลำดับในแบบฟอร์ม"""
    seen = {account_place(account)}
    for it in getattr(account, "items", None) or []:
        if it.fiscal_year == fy:
            seen.add(item_place(it))
    for t in account.txns:
        if t.fiscal_year == fy:
            seen.add(txn_place(t))
    return [k for k in PLACES if k in seen]
