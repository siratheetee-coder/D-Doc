# -*- coding: utf-8 -*-
"""
subsidy.py - เงินอุดหนุนโครงการเรียนฟรี 15 ปี: คำนวณยอดที่ควรได้รับแต่ละงวด

กติกาการจัดสรร (ใช้เป็นแกนของทั้งไฟล์นี้)
  เงินอุดหนุนได้รับ "ภาคเรียนละ 2 ครั้ง" คือ 70% แล้วตามด้วย 30%
  ฐานจำนวนนักเรียนที่ใช้คิดแต่ละครั้ง ไม่ใช่รอบเดียวกัน

      ภาคเรียนที่ 1   70%  ใช้ DMC 10 พ.ย. ของปีการศึกษาก่อนหน้า
                      30%  ใช้ DMC 10 มิ.ย. ของปีการศึกษานี้
      ภาคเรียนที่ 2   70%  ใช้ DMC 10 มิ.ย. ของปีการศึกษานี้
                      30%  ใช้ DMC 10 พ.ย. ของปีการศึกษานี้

  ภาคเรียนที่ 1 ได้ครบ 5 รายการ · ภาคเรียนที่ 2 ได้ 3 รายการ
  (ค่าหนังสือเรียนกับค่าเครื่องแบบนักเรียนจ่ายปีละครั้งในภาคเรียนที่ 1)

เรื่องอัตราต่อหัว
  อัตราที่ใส่ไว้เป็น "อัตราฐาน" ของโครงการเรียนฟรี 15 ปี ไว้ให้เริ่มใช้งานได้เร็ว
  แต่ละปีงบมีการปรับเพิ่ม และหนังสือแจ้งจัดสรรของเขตพื้นที่คือตัวจริง
  ระบบจึงเก็บอัตราแยกรายปีการศึกษาให้โรงเรียนแก้เองได้ และต้องเตือนให้ตรวจทุกปี
"""

from app.thai_utils import SCHOOL_LEVELS

# ---------------------------------------------------------------- 5 รายการ
# key, ชื่อที่ใช้ทั้งในทะเบียนคุมและเอกสาร, จ่ายทั้งสองภาคเรียนไหม
ITEMS = [
    ("teach", "ค่าจัดการเรียนการสอน", True),
    ("book", "ค่าหนังสือเรียน", False),
    ("equip", "ค่าอุปกรณ์การเรียน", True),
    ("uniform", "ค่าเครื่องแบบนักเรียน", False),
    ("activity", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", True),
]
ITEM_NAME = {k: name for k, name, _ in ITEMS}
ITEM_KEYS = [k for k, _n, _b in ITEMS]
BOTH_TERMS = {k for k, _n, both in ITEMS if both}        # แบ่งครึ่งลงสองภาคเรียน
TERM1_ONLY = {k for k, _n, both in ITEMS if not both}    # จ่ายเต็มจำนวนในภาคเรียนที่ 1

# ---------------------------------------------------------------- งวดการจัดสรร
# (ภาคเรียน, สัดส่วน, รอบ DMC ที่ใช้, ปีการศึกษาของรอบนั้นเทียบกับปีที่คำนวณ)
ROUNDS = [
    (1, 0.70, "nov", -1),
    (1, 0.30, "jun", 0),
    (2, 0.70, "jun", 0),
    (2, 0.30, "nov", 0),
]
ROUND_LABEL = {"jun": "10 มิถุนายน", "nov": "10 พฤศจิกายน"}


def census_rounds(academic_year: int) -> list:
    """รอบ DMC ที่ต้องกรอก สำหรับคำนวณปีการศึกษานี้ (เรียงตามเวลาจริง)"""
    return [
        {"key": f"nov{academic_year - 1}", "round": "nov", "year": academic_year - 1,
         "label": f"10 พ.ย. {academic_year - 1}", "why": "ฐานของ 70% ภาคเรียนที่ 1"},
        {"key": f"jun{academic_year}", "round": "jun", "year": academic_year,
         "label": f"10 มิ.ย. {academic_year}", "why": "ฐานของ 30% ภาคเรียนที่ 1 และ 70% ภาคเรียนที่ 2"},
        {"key": f"nov{academic_year}", "round": "nov", "year": academic_year,
         "label": f"10 พ.ย. {academic_year}", "why": "ฐานของ 30% ภาคเรียนที่ 2"},
    ]


# ---------------------------------------------------------------- อัตราฐาน
# บาท/คน/ปี · ค่าหนังสือเรียนต่างกันรายชั้น ที่เหลือเท่ากันทั้งช่วงชั้น
# ตัวเลขชุดนี้เป็นค่าตั้งต้นให้แก้ ไม่ใช่ตัวเลขที่ระบบยืนยันแทนหนังสือแจ้งจัดสรร
_GROUP_RATES = {
    "อ": {"teach": 1700, "equip": 290, "uniform": 300, "activity": 430},
    "ป": {"teach": 1900, "equip": 440, "uniform": 360, "activity": 480},
    "ม": {"teach": 3500, "equip": 520, "uniform": 450, "activity": 880},
}
_BOOK_RATES = {
    "อ.1": 200, "อ.2": 200, "อ.3": 200,
    "ป.1": 656, "ป.2": 650, "ป.3": 653, "ป.4": 707, "ป.5": 846, "ป.6": 859,
    "ม.1": 808, "ม.2": 921, "ม.3": 996,
}


def default_rates() -> dict:
    """อัตราฐานต่อคนต่อปี -> {ชั้น: {รายการ: อัตรา}}"""
    out = {}
    for level in SCHOOL_LEVELS:
        group = level[0]
        base = dict(_GROUP_RATES.get(group, {}))
        base["book"] = _BOOK_RATES.get(level, 0)
        out[level] = base
    return out


# ---------------------------------------------------------------- คำนวณ
def _term_share(item_key: str, term: int) -> float:
    """สัดส่วนของอัตราต่อปี ที่ตกอยู่ในภาคเรียนนี้"""
    if item_key in TERM1_ONLY:
        return 1.0 if term == 1 else 0.0
    return 0.5


def compute(counts: dict, rates: dict, academic_year: int) -> dict:
    """คำนวณยอดที่ควรได้รับทุกงวด

    counts = {"nov2568": {"ป.1": 20, ...}, "jun2569": {...}, "nov2569": {...}}
    rates  = {"ป.1": {"teach": 1900, ...}, ...}  (บาท/คน/ปี)
    คืน rows รายงวด + สรุปรายรายการ + ยอดรวมทั้งปี
    """
    rounds = []
    for term, pct, rnd, offset in ROUNDS:
        key = f"{rnd}{academic_year + offset}"
        by_level = counts.get(key, {})
        heads = sum(int(v or 0) for v in by_level.values())
        amounts = {}
        for item_key in ITEM_KEYS:
            share = _term_share(item_key, term)
            if not share:
                continue
            total = 0.0
            for level, n in by_level.items():
                rate = float((rates.get(level) or {}).get(item_key) or 0)
                total += rate * int(n or 0) * share * pct
            amounts[item_key] = round(total, 2)
        rounds.append({
            "term": term, "pct": pct, "pct_text": f"{int(pct * 100)}%",
            "census_key": key, "census_label": ROUND_LABEL[rnd],
            "census_year": academic_year + offset,
            "heads": heads, "amounts": amounts,
            "total": round(sum(amounts.values()), 2),
            "item_count": len(amounts),
        })
    by_item = {k: round(sum(r["amounts"].get(k, 0.0) for r in rounds), 2) for k in ITEM_KEYS}
    return {
        "rounds": rounds,
        "by_item": by_item,
        "by_term": {t: round(sum(r["total"] for r in rounds if r["term"] == t), 2) for t in (1, 2)},
        "total": round(sum(by_item.values()), 2),
    }


def match_received(db, academic_year: int, by_item: dict) -> dict:
    """จับคู่ยอดที่คำนวณได้ กับเงินที่รับจริงในทะเบียนคุม (รายการย่อยของเงินอุดหนุน)

    ดูจากชื่อรายการย่อย ไม่ผูก id เพราะโรงเรียนตั้งชื่อเองได้และอาจสร้างใหม่ทุกปี
    ปีงบประมาณของเงินอุดหนุนปีการศึกษา Y คร่อม 2 ปีงบ จึงนับทั้ง Y และ Y+1
    """
    from app.models import AccountItem, FinanceTxn
    got = {k: 0.0 for k in ITEM_KEYS}
    rows = (db.query(FinanceTxn, AccountItem)
            .join(AccountItem, FinanceTxn.item_id == AccountItem.id)
            .filter(FinanceTxn.kind == "in",
                    FinanceTxn.fiscal_year.in_([academic_year, academic_year + 1]))
            .all())
    for txn, item in rows:
        name = (item.name or "").strip()
        for key in ITEM_KEYS:
            if ITEM_NAME[key] in name or name in ITEM_NAME[key]:
                got[key] += float(txn.amount or 0)
                break
    return {k: {"should": by_item.get(k, 0.0), "got": round(got[k], 2),
                "diff": round(got[k] - by_item.get(k, 0.0), 2)} for k in ITEM_KEYS}
