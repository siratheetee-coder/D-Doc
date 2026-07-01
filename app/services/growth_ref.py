# -*- coding: utf-8 -*-
"""
growth_ref.py — เกณฑ์การเจริญเติบโตเด็ก 6-19 ปี (กรมอนามัย)
จัดกลุ่มภาวะโภชนาการอัตโนมัติจาก น้ำหนัก/ส่วนสูง/อายุ/เพศ ด้วยค่าจุดตัดตาม SD

ที่มาค่าเกณฑ์: มาตรฐานการเจริญเติบโตกรมอนามัย (ชุดตัวเลขสาธารณะ)
ฝังเป็น app/data/growth_ref.json — ค่า SD เรียง [-3,-2,-1.5,-1,MEDIAN,+1,+1.5,+2,+3]
"""
import json
from datetime import date, datetime
from pathlib import Path

_REF = json.loads((Path(__file__).resolve().parent.parent / "data" / "growth_ref.json")
                  .read_text(encoding="utf-8"))

# ตำแหน่งใน 9 ค่า SD
_I_2N, _I_15N, _I_15P, _I_2P, _I_3P = 1, 2, 6, 7, 8

# ป้ายกลุ่ม (เรียงจากน้อย->มาก)
WH_LABELS = ["ผอม", "ค่อนข้างผอม", "สมส่วน", "ท้วม", "เริ่มอ้วน", "อ้วน"]
HA_LABELS = ["เตี้ย", "ค่อนข้างเตี้ย", "สูงตามเกณฑ์", "ค่อนข้างสูง", "สูง"]
WA_LABELS = ["น้ำหนักน้อยกว่าเกณฑ์", "ค่อนข้างน้อย", "ตามเกณฑ์", "ค่อนข้างมาก", "มากกว่าเกณฑ์"]


def _sex(s):
    s = (s or "").strip().upper()
    if s in ("M", "ช", "ชาย", "MALE", "1"):
        return "M"
    if s in ("F", "ญ", "หญิง", "FEMALE", "2"):
        return "F"
    return None


def _interp(table, x):
    """หา 9 ค่า SD ที่ index = x (linear interpolation) ; คืน None ถ้านอกช่วง"""
    if not table:
        return None
    if x < table[0][0] or x > table[-1][0]:
        return None
    lo = table[0]
    for cur in table:
        if cur[0] == x:
            return cur[1]
        if cur[0] > x:
            hi = cur
            f = (x - lo[0]) / (hi[0] - lo[0])
            return [a + (b - a) * f for a, b in zip(lo[1], hi[1])]
        lo = cur
    return lo[1]


def age_months(birth, at=None):
    """อายุเป็นเดือนจากวันเกิดถึงวันที่วัด (รับ date/datetime)"""
    if not birth:
        return None
    at = at or datetime.now()
    if isinstance(birth, datetime):
        birth = birth.date()
    if isinstance(at, datetime):
        at = at.date()
    m = (at.year - birth.year) * 12 + (at.month - birth.month)
    if at.day < birth.day:
        m -= 1
    return max(0, m)


def _band5(value, sd9, labels):
    """แบ่ง 5 กลุ่ม (เตี้ย/สูง, น้ำหนักน้อย/มาก) ด้วยจุดตัด -2,-1.5,+1.5,+2 SD"""
    if sd9 is None or value is None:
        return None
    if value < sd9[_I_2N]:
        return labels[0]
    if value < sd9[_I_15N]:
        return labels[1]
    if value <= sd9[_I_15P]:
        return labels[2]
    if value <= sd9[_I_2P]:
        return labels[3]
    return labels[4]


def classify_wh(sex, height_cm, weight_kg):
    """น้ำหนักตามเกณฑ์ส่วนสูง -> ผอม/ค่อนข้างผอม/สมส่วน/ท้วม/เริ่มอ้วน/อ้วน"""
    s = _sex(sex)
    if not s or not height_cm or not weight_kg:
        return None
    sd = _interp(_REF["wh"][s], round(float(height_cm), 1))
    if sd is None:
        return None
    w = float(weight_kg)
    if w < sd[_I_2N]:
        return WH_LABELS[0]
    if w < sd[_I_15N]:
        return WH_LABELS[1]
    if w <= sd[_I_15P]:
        return WH_LABELS[2]
    if w <= sd[_I_2P]:
        return WH_LABELS[3]
    if w <= sd[_I_3P]:
        return WH_LABELS[4]
    return WH_LABELS[5]


def classify_ha(sex, age_mo, height_cm):
    """ส่วนสูงตามเกณฑ์อายุ -> เตี้ย/ค่อนข้างเตี้ย/สูงตามเกณฑ์/ค่อนข้างสูง/สูง"""
    s = _sex(sex)
    if not s or age_mo is None or not height_cm:
        return None
    return _band5(float(height_cm), _interp(_REF["ha"][s], age_mo), HA_LABELS)


def classify_wa(sex, age_mo, weight_kg):
    """น้ำหนักตามเกณฑ์อายุ -> น้ำหนักน้อยกว่าเกณฑ์/ค่อนข้างน้อย/ตามเกณฑ์/ค่อนข้างมาก/มากกว่าเกณฑ์"""
    s = _sex(sex)
    if not s or age_mo is None or not weight_kg:
        return None
    return _band5(float(weight_kg), _interp(_REF["wa"][s], age_mo), WA_LABELS)


def classify_all(sex, birth, weight_kg, height_cm, at=None):
    """คืน dict ผลทั้ง 3 เกณฑ์ + อายุ(เดือน) ; ภาวะโภชนาการหลัก = น้ำหนักตามส่วนสูง"""
    mo = age_months(birth, at)
    return {
        "age_months": mo,
        "wh": classify_wh(sex, height_cm, weight_kg),      # ผอม/อ้วน (หลัก)
        "ha": classify_ha(sex, mo, height_cm),             # เตี้ย
        "wa": classify_wa(sex, mo, weight_kg),             # น้ำหนักต่ออายุ
    }
