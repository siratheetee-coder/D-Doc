# -*- coding: utf-8 -*-
"""
asset_utils.py
--------------
คำนวณค่าเสื่อมราคาครุภัณฑ์แบบ "เส้นตรง" (straight-line) ตามแนวทางกรมบัญชีกลาง
- ค่าเสื่อมต่อปี = (ราคาทุน - มูลค่าซาก) / อายุการใช้งาน
- คิดค่าเสื่อมเป็นรายวัน เริ่มนับจากวันที่ได้มา
- มูลค่าสุทธิทางบัญชี (NBV) = ราคาทุน - ค่าเสื่อมสะสม (ไม่ต่ำกว่ามูลค่าซาก)

หมายเหตุ: ปีงบประมาณไทยเริ่ม 1 ต.ค. สิ้นสุด 30 ก.ย.
"""
from datetime import date, datetime

# อายุการใช้งานมาตรฐาน (ปี) ตามประเภทครุภัณฑ์ (อิงแนวกรมบัญชีกลาง)
# ผู้ใช้แก้ค่าได้เองในแต่ละรายการ
CATEGORY_LIFE = {
    "ครุภัณฑ์สำนักงาน": 12,
    "ครุภัณฑ์คอมพิวเตอร์": 5,
    "ครุภัณฑ์การศึกษา": 8,
    "ครุภัณฑ์ไฟฟ้าและวิทยุ": 8,
    "ครุภัณฑ์โฆษณาและเผยแพร่": 5,
    "ครุภัณฑ์งานบ้านงานครัว": 5,
    "ครุภัณฑ์กีฬา": 5,
    "ครุภัณฑ์ดนตรีและนาฏศิลป์": 8,
    "ครุภัณฑ์วิทยาศาสตร์การแพทย์": 8,
    "ครุภัณฑ์การเกษตร": 8,
    "ครุภัณฑ์ก่อสร้าง": 8,
    "ครุภัณฑ์โรงงาน": 8,
    "ครุภัณฑ์ยานพาหนะและขนส่ง": 8,
    "ครุภัณฑ์อื่น": 10,
}
CATEGORIES = list(CATEGORY_LIFE.keys())


def _as_date(d):
    if isinstance(d, datetime):
        return d.date()
    return d


def _fiscal_year_end(d: date) -> date:
    """สิ้นปีงบประมาณที่ครอบคลุมวันที่ d (30 ก.ย.)"""
    if d.month >= 10:          # ต.ค.-ธ.ค. -> ปีงบสิ้นสุด ก.ย. ปีถัดไป
        return date(d.year + 1, 9, 30)
    return date(d.year, 9, 30)


def annual_depreciation(cost, salvage, life_years) -> float:
    """ค่าเสื่อมราคาต่อปี (เต็มปี)"""
    depreciable = max(float(cost or 0) - float(salvage or 0), 0)
    if not life_years or life_years <= 0:
        return 0.0
    return round(depreciable / life_years, 2)


def accumulated_depreciation(cost, salvage, life_years, acquired, as_of=None) -> float:
    """ค่าเสื่อมสะสม ณ วันที่ as_of (คิดรายวันเส้นตรง ไม่เกินมูลค่าที่เสื่อมได้)"""
    acquired = _as_date(acquired)
    if acquired is None:
        return 0.0
    as_of = _as_date(as_of) or date.today()
    depreciable = max(float(cost or 0) - float(salvage or 0), 0)
    if not life_years or life_years <= 0 or depreciable <= 0 or as_of <= acquired:
        return 0.0
    annual = depreciable / life_years
    days = (as_of - acquired).days
    dep = annual * days / 365.0
    return round(min(dep, depreciable), 2)


def net_book_value(cost, salvage, life_years, acquired, as_of=None) -> float:
    """มูลค่าสุทธิทางบัญชี = ราคาทุน - ค่าเสื่อมสะสม (ไม่ต่ำกว่ามูลค่าซาก)"""
    acc = accumulated_depreciation(cost, salvage, life_years, acquired, as_of)
    nbv = float(cost or 0) - acc
    return round(max(nbv, float(salvage or 0)), 2)


def depreciation_schedule(cost, salvage, life_years, acquired) -> list:
    """ตารางค่าเสื่อมรายปีงบประมาณ จนกว่าจะถึงมูลค่าซาก
    คืน [{'fy': 2569, 'dep': .., 'acc': .., 'nbv': ..}, ...] (fy = พ.ศ.)"""
    acquired = _as_date(acquired)
    cost = float(cost or 0)
    salvage = float(salvage or 0)
    depreciable = max(cost - salvage, 0)
    if acquired is None or not life_years or life_years <= 0 or depreciable <= 0:
        return []
    annual = depreciable / life_years
    rows = []
    acc = 0.0
    seg_start = acquired
    fy_end = _fiscal_year_end(acquired)
    guard = 0
    while acc < depreciable - 0.005 and guard < life_years + 4:
        guard += 1
        days = (fy_end - seg_start).days + 1
        dep = annual * days / 365.0
        if acc + dep > depreciable:
            dep = depreciable - acc
        acc += dep
        rows.append({
            "fy": fy_end.year + 543,          # ปีงบประมาณ = พ.ศ. ของปีที่สิ้นสุด (ก.ย.)
            "dep": round(dep, 2),
            "acc": round(acc, 2),
            "nbv": round(cost - acc, 2),
        })
        seg_start = date(fy_end.year, 10, 1)
        fy_end = date(fy_end.year + 1, 9, 30)
    return rows


def material_balance(item) -> float:
    """ยอดคงเหลือวัสดุ = ผลรวมรับเข้า - ผลรวมจ่ายออก"""
    bal = 0.0
    for t in item.txns:
        if t.kind == "in":
            bal += (t.qty or 0)
        else:
            bal -= (t.qty or 0)
    return bal


def account_balance(account) -> float:
    """ยอดคงเหลือสะสมทั้งหมด = ยอดยกมาตั้งต้น + ผลรวมรับ - ผลรวมจ่าย (ทุกปี)
    ใช้กรณีต้องการยอดรวมทั้งบัญชี (ไม่แยกปี)"""
    bal = float(account.opening_balance or 0)
    for t in account.txns:
        if t.kind == "in":
            bal += (t.amount or 0)
        else:
            bal -= (t.amount or 0)
    return round(bal, 2)


def opening_for(account, fy) -> float:
    """ยอดยกมาของบัญชีในปีงบ fy:
    ถ้ามีระเบียนยกยอดของปีนั้น ใช้ค่านั้น มิฉะนั้นใช้ยอดตั้งต้นของบัญชี"""
    for o in getattr(account, "openings", []) or []:
        if o.fiscal_year == fy:
            return float(o.amount or 0)
    return float(account.opening_balance or 0)


def account_balance_year(account, fy) -> float:
    """ยอดคงเหลือของบัญชี ณ สิ้นปีงบ fy = ยอดยกมาปีนั้น + (รับ - จ่าย) เฉพาะรายการปีนั้น"""
    bal = opening_for(account, fy)
    for t in account.txns:
        if t.fiscal_year != fy:
            continue
        bal += (t.amount or 0) if t.kind == "in" else -(t.amount or 0)
    return round(bal, 2)


def _before(t, as_of):
    """รายการนี้เกิดก่อนหรือเท่ากับวันที่ as_of หรือไม่ (ถ้าไม่กำหนด as_of = นับทั้งหมด)"""
    if not as_of or not t.date:
        return True
    d = as_of.date() if hasattr(as_of, "date") else as_of
    return t.date.date() <= d


def account_balance_asof(account, fy, as_of=None) -> float:
    """ยอดคงเหลือบัญชี ณ วันที่ as_of (ในปีงบ fy) — สำหรับรายงานเงินคงเหลือประจำวัน"""
    bal = opening_for(account, fy)
    for t in account.txns:
        if t.fiscal_year != fy or not _before(t, as_of):
            continue
        bal += (t.amount or 0) if t.kind == "in" else -(t.amount or 0)
    return round(bal, 2)


def item_remaining_asof(item, as_of=None) -> float:
    """คงเหลือของหมวด ณ วันที่ as_of = งบที่ตั้งไว้ + (รับ - จ่าย) ที่ผูกกับหมวดถึงวันนั้น"""
    bal = float(item.budget or 0)
    for t in item.account.txns:
        if t.item_id != item.id or t.fiscal_year != item.fiscal_year or not _before(t, as_of):
            continue
        bal += (t.amount or 0) if t.kind == "in" else -(t.amount or 0)
    return round(bal, 2)
