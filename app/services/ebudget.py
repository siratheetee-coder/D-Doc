# -*- coding: utf-8 -*-
"""
ebudget.py - ช่วยกรอก "ระบบบัญชีการศึกษาขั้นพื้นฐาน" (e-Budget ของ สนผ. สพฐ.)

เว็บ e-Budget ให้กรอกปีละ 2 ครั้ง
  ครั้งที่ 1 = 1 ต.ค. - 31 มี.ค.   ครั้งที่ 2 = 1 เม.ย. - 30 ก.ย.
แบ่งเป็น 5 ส่วนที่ผูกกัน: ส่วนที่ 2 คงเหลือยกมา · 3 รายรับ · 4 รายจ่าย · 5 คงเหลือปลายงวด
และเว็บจะตรวจว่า  รายรับ (ส่วน 3) − รายจ่าย (ส่วน 4) = คงเหลือ (ส่วน 5)

ไฟล์นี้ "คำนวณตัวเลขให้" จากทะเบียนคุมเงินที่ครูลงไว้แล้ว ไม่ได้ส่งข้อมูลไปที่ e-Budget
ครูยังต้องเปิดเว็บ e-Budget แล้วคัดลอกตัวเลขไปวางเอง (เหมือนหน้าช่วยกรอก e-GP)

การจับคู่ประเภทเงิน ใช้ "ชื่อบัญชี/ชื่อรายการย่อย" ที่ครูตั้งไว้ จับคำสำคัญ
ถ้าจับไม่ได้จะไปลงช่อง "อื่น ๆ" และหน้าเว็บจะบอกให้ครูตรวจทานก่อนกรอก
"""
from datetime import datetime

# ---------------------------------------------------------------- ช่วงเวลา
ROUNDS = {1: ("1 ต.ค. - 31 มี.ค.", 10, 1, 3, 31),
          2: ("1 เม.ย. - 30 ก.ย.", 4, 1, 9, 30)}


def period(fiscal_year: int, rnd: int) -> tuple:
    """ช่วงวันที่ของการรายงานรอบนั้น (ปีงบ 2569 = 1 ต.ค. 2568 - 30 ก.ย. 2569)"""
    label, m1, d1, m2, d2 = ROUNDS[2 if rnd == 2 else 1]
    y_start = fiscal_year - 1 if m1 >= 10 else fiscal_year
    start = datetime(y_start - 543, m1, d1)
    end = datetime(fiscal_year - 543, m2, d2, 23, 59, 59)
    return start, end, label


# ------------------------------------------------- จับคู่ประเภทเงิน -> ช่อง e-Budget
# เรียงจาก "เจาะจงที่สุด" ไป "กว้างที่สุด" เพราะจับคำแรกที่ตรง
_FREE = "free"          # 3.1 เงินอุดหนุนทั่วไป โครงการเรียนฟรี
_SUBSIDY = "subsidy"    # 3.2 เงินอุดหนุนทั่วไป (นอกเหนือ 3.1)
_OTHER = "other"        # 3.3 - 3.13

RULES = [
    # (คำสำคัญในชื่อบัญชี/รายการย่อย, รหัสช่อง, ชื่อช่องใน e-Budget)
    (("เสมอภาค", "กสศ"), "3.12", "เงินอุดหนุนนักเรียนยากจนพิเศษแบบมีเงื่อนไข (ทุนเสมอภาค) กสศ."),
    (("ยากลำบาก",), "3.2.4", "ค่าอาหารนักเรียนพักนอนสำหรับโรงเรียนในพื้นที่ยากลำบาก"),
    (("ยากจน",), "3.1.6", "ปัจจัยพื้นฐานสำหรับนักเรียนยากจน"),
    (("หนังสือเรียน",), "3.1.2", "ค่าหนังสือเรียน"),
    (("อุปกรณ์การเรียน",), "3.1.3", "ค่าอุปกรณ์การเรียน"),
    (("เครื่องแบบ",), "3.1.4", "ค่าเครื่องแบบนักเรียน"),
    (("กิจกรรมพัฒนา",), "3.1.5", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน"),
    (("พักนอน",), "3.1.7", "ค่าอาหารนักเรียนประจำพักนอน"),
    (("รายหัว", "จัดการเรียนการสอน"), "3.1.1", "รายหัว"),
    (("อาหารกลางวัน",), "3.2.2", "ค่าอาหารกลางวัน (ได้รับจากท้องถิ่น)"),
    (("ทุนหมุนเวียน",), "3.2.3", "โครงการเงินทุนหมุนเวียนฯ อาหารกลางวัน"),
    (("จ้างครู", "ค่าจ้างครู"), "3.2.1", "ค่าจ้างครูและบุคลากร (ได้รับจากท้องถิ่น)"),
    (("บำรุงการศึกษา",), "3.3", "เงินบำรุงการศึกษา"),
    (("บริจาค",), "3.4", "เงินบริจาค"),
    (("รายได้สถานศึกษา",), "3.5", "เงินรายได้สถานศึกษา"),
    (("กยศ",), "3.6", "เงินค่าใช้จ่ายในการดำเนินงาน กยศ."),
    (("ประกันสัญญา",), "3.7", "เงินประกันสัญญา"),
    (("ภาษี", "หัก ณ ที่จ่าย"), "3.8", "เงินภาษีหัก ณ ที่จ่ายจากสัญญาซื้อ/จ้าง"),
    (("ลูกเสือ",), "3.9", "เงินลูกเสือ"),
    (("เนตรนารี", "บำเพ็ญประโยชน์"), "3.10", "เงินเนตรนารี/ผู้บำเพ็ญประโยชน์"),
    (("ยุวกาชาด",), "3.11", "เงินยุวกาชาด"),
    (("กันไว้เบิกจ่าย", "เหลื่อมปี"), "1.3", "เงินกันไว้เบิกจ่ายเหลื่อมปี อื่น ๆ"),
    (("ขายของเบ็ตเตล็ด",), "2.1", "ค่าขายของเบ็ตเตล็ด"),
    (("ธรรมเนียม",), "2.2", "ค่าธรรมเนียมเบ็ตเตล็ด"),
    (("ดอกเบี้ย",), "2.4", "ดอกเบี้ยเงินฝากฯ"),
]

# ลำดับช่องที่จะแสดง (ตามหน้า e-Budget ส่วนที่ 2 / 5)
ORDER = [
    ("1", "เงินกันไว้เบิกจ่ายเหลื่อมปี", True),
    ("1.1", "1.1 ค่าครุภัณฑ์", False),
    ("1.2", "1.2 ค่าที่ดินและสิ่งก่อสร้าง", False),
    ("1.3", "1.3 อื่น ๆ (ไม่ใช่เงินอุดหนุน)", False),
    ("2", "เงินรายได้แผ่นดินคงเหลือ", True),
    ("2.1", "2.1 ค่าขายของเบ็ตเตล็ด", False),
    ("2.2", "2.2 ค่าธรรมเนียมเบ็ตเตล็ด", False),
    ("2.3", "2.3 เงินอุดหนุนทั่วไปที่เหลือจ่ายเกิน 2 ปีงบประมาณ", False),
    ("2.4", "2.4 ดอกเบี้ยเงินฝากฯ", False),
    ("2.5", "2.5 อื่น ๆ", False),
    ("3", "เงินนอกงบประมาณคงเหลือ", True),
    ("3.1", "3.1 เงินอุดหนุนทั่วไป โครงการเรียนฟรี", False),
    ("3.1.1", "(1) รายหัว", False),
    ("3.1.2", "(2) ค่าหนังสือเรียน", False),
    ("3.1.3", "(3) ค่าอุปกรณ์การเรียน", False),
    ("3.1.4", "(4) ค่าเครื่องแบบนักเรียน", False),
    ("3.1.5", "(5) ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", False),
    ("3.1.6", "(6) ปัจจัยพื้นฐานสำหรับนักเรียนยากจน", False),
    ("3.1.7", "(7) ค่าอาหารนักเรียนประจำพักนอน", False),
    ("3.2", "3.2 เงินอุดหนุนทั่วไป (นอกเหนือจากข้อ 3.1)", False),
    ("3.2.1", "(1) ค่าจ้างครูและบุคลากร (ได้รับจากท้องถิ่น)", False),
    ("3.2.2", "(2) ค่าอาหารกลางวัน (ได้รับจากท้องถิ่น)", False),
    ("3.2.3", "(3) โครงการเงินทุนหมุนเวียนส่งเสริมผลผลิตเพื่อโครงการอาหารกลางวัน", False),
    ("3.2.4", "(4) ค่าอาหารนักเรียนพักนอนสำหรับโรงเรียนในพื้นที่ยากลำบาก", False),
    ("3.2.5", "(5) อื่น ๆ", False),
    ("3.3", "3.3 เงินบำรุงการศึกษา", False),
    ("3.4", "3.4 เงินบริจาค", False),
    ("3.5", "3.5 เงินรายได้สถานศึกษา", False),
    ("3.6", "3.6 เงินค่าใช้จ่ายในการดำเนินงาน กยศ.", False),
    ("3.7", "3.7 เงินประกันสัญญา", False),
    ("3.8", "3.8 เงินภาษีหัก ณ ที่จ่าย จากสัญญาซื้อ/จ้างของโรงเรียน", False),
    ("3.9", "3.9 เงินลูกเสือ", False),
    ("3.10", "3.10 เงินเนตรนารี/ผู้บำเพ็ญประโยชน์", False),
    ("3.11", "3.11 เงินยุวกาชาด", False),
    ("3.12", "3.12 เงินอุดหนุนนักเรียนยากจนพิเศษแบบมีเงื่อนไข (ทุนเสมอภาค) กสศ.", False),
    ("3.13", "3.13 อื่น ๆ", False),
    ("4", "เงินอื่น ๆ คงเหลือ", True),
]

# คอลัมน์ "แหล่งเงิน" ของส่วนที่ 4 (รายจ่าย)
SOURCES = [
    ("budget", "เงินงบประมาณ"),
    ("free", "โครงการเรียนฟรี"),
    ("edu", "เงินบำรุงการศึกษา"),
    ("donate", "เงินบริจาค"),
    ("income", "เงินรายได้สถานศึกษา"),
    ("etc", "อื่น ๆ"),
    ("land", "เงินรายได้แผ่นดิน"),
]


def classify(name: str, fund_type: str = "") -> tuple:
    """ชื่อบัญชี/รายการย่อย -> (รหัสช่อง, ชื่อช่อง) · จับไม่ได้ = 3.13 อื่น ๆ

    บัญชีที่ตั้งหมวดเงินเป็น "เงินรายได้แผ่นดิน" ต้องลงหมวด 2 เสมอ
    ไม่ใช่ไปรวมกับเงินนอกงบประมาณ เพราะ e-Budget แยกคนละหมวด
    """
    text = (name or "").strip()
    hit = next(((code, label) for words, code, label in RULES
                if any(w in text for w in words)), None)
    if (fund_type or "") == "เงินรายได้แผ่นดิน":
        return hit if hit and hit[0].startswith("2.") else ("2.5", "อื่น ๆ")
    return hit or ("3.13", "อื่น ๆ")


def source_of(code: str, fund_type: str) -> str:
    """ช่อง e-Budget -> คอลัมน์แหล่งเงินในส่วนที่ 4"""
    if (fund_type or "") == "เงินรายได้แผ่นดิน":
        return "land"
    if (fund_type or "") == "เงินงบประมาณ":
        return "budget"
    if code.startswith("2"):
        return "land"
    if code.startswith("3.1."):
        return "free"
    return {"3.3": "edu", "3.4": "donate", "3.5": "income"}.get(code, "etc")


# ---------------------------------------------------------------- คำนวณ
def _bucket():
    return {code: 0.0 for code, _lbl, _bold in ORDER}


def _target(name: str, fund_type: str = "") -> str:
    """ช่องที่ยอดของบัญชี/รายการย่อยนี้ต้องลง (หัวข้อรวมคิดจากลูกให้เอง)"""
    return classify(name, fund_type)[0]


# หัวข้อรวมในแบบ e-Budget = ผลรวมของข้อย่อย (ไล่จากชั้นในออกชั้นนอก)
PARENTS = {
    "3.1": ["3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.1.7"],
    "3.2": ["3.2.1", "3.2.2", "3.2.3", "3.2.4", "3.2.5"],
    "1": ["1.1", "1.2", "1.3"],
    "2": ["2.1", "2.2", "2.3", "2.4", "2.5"],
    "3": ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8",
          "3.9", "3.10", "3.11", "3.12", "3.13"],
}


def leaf_sum(bucket: dict) -> float:
    """ยอดรวมจริง = รวมเฉพาะข้อย่อย ไม่นับหัวข้อรวม (ไม่งั้นนับซ้ำ)"""
    return round(sum(v for k, v in bucket.items() if k not in PARENTS), 2)


def _rollup(bucket: dict) -> dict:
    """หัวข้อรวม = ผลรวมของข้อย่อย (ถ้ามีเงินลงที่หัวข้อรวมตรง ๆ ให้บวกเพิ่ม)"""
    for parent, kids in PARENTS.items():
        bucket[parent] = round(bucket.get(parent, 0.0)
                               + sum(bucket.get(k, 0.0) for k in kids), 2)
    return bucket


def build(db, fiscal_year: int, rnd: int) -> dict:
    """สรุปตัวเลขทุกส่วนของ e-Budget จากทะเบียนคุมเงิน

    คืน dict: period · opening (ส่วน 2) · income (ส่วน 3) · expense (ส่วน 4)
              · closing (ส่วน 5) · check (ยอดตรวจ) · unmapped (รายการที่จับคู่ไม่ได้)
    """
    from app.models import AccountItem, FinanceAccount, FinanceTxn
    start, end, label = period(fiscal_year, rnd)

    accounts = db.query(FinanceAccount).all()
    items = {it.id: it for it in db.query(AccountItem).filter_by(fiscal_year=fiscal_year).all()}
    txns = [t for t in db.query(FinanceTxn).filter_by(fiscal_year=fiscal_year).all()]

    def code_for(t) -> str:
        """ช่องของรายการนี้ - ดูชื่อรายการย่อยก่อน ถ้าไม่มีจึงใช้ชื่อบัญชี"""
        acct = next((a for a in accounts if a.id == t.account_id), None)
        ft = acct.fund_type if acct else ""
        it = items.get(t.item_id) if t.item_id else None
        if it is not None:
            code = _target(it.name, ft)
            if code not in ("3.13", "2.5"):
                return code
        return _target(acct.name if acct else "", ft)

    opening, income, closing = _bucket(), _bucket(), _bucket()
    expense = {s: 0.0 for s, _ in SOURCES}
    rows, unmapped = [], set()
    matrix, missing = {}, []          # ตารางไขว้ส่วนที่ 4 · รายการที่ยังไม่ได้ระบุหมวด

    # ยอดยกมาต้นปีงบ ลงช่องตามชื่อบัญชี
    for a in accounts:
        from app.services.asset_utils import opening_for
        code = _target(a.name, a.fund_type)
        opening[code] += opening_for(a, fiscal_year)
        closing[code] += opening_for(a, fiscal_year)

    for t in txns:
        code = code_for(t)
        amt = float(t.amount or 0)
        acct = next((a for a in accounts if a.id == t.account_id), None)
        if code in ("3.13", "2.5"):
            it = items.get(t.item_id) if t.item_id else None
            unmapped.add((it.name if it else (acct.name if acct else "-")))
        d = t.date or start
        inside = start <= d <= end
        before = d < start
        if t.kind == "in":
            if before or inside:
                closing[code] += amt
            if before:
                opening[code] += amt
            if inside:
                income[code] += amt
        else:
            if before or inside:
                closing[code] -= amt
            if before:
                opening[code] -= amt
            if inside:
                src = source_of(code, acct.fund_type if acct else "")
                expense[src] += amt
                eb = (getattr(t, "eb_code", "") or "").strip()
                if eb:
                    matrix.setdefault(eb, {k: 0.0 for k, _ in SOURCES})[src] += amt
                else:
                    missing.append(t.id)
                rows.append({"date": d, "ref": t.ref or "", "note": t.note or "",
                             "amount": amt, "source": src, "code": code, "eb": eb,
                             "account": acct.name if acct else "", "id": t.id})

    # หัวข้อรวม (3.1 / 3.2) ในแบบ e-Budget = ผลรวมของข้อย่อย ไม่ใช่ช่องกรอกแยก
    for bucket in (opening, income, closing):
        _rollup(bucket)

    rows.sort(key=lambda r: r["date"])
    tot_in = leaf_sum(income)
    tot_out = round(sum(expense.values()), 2)      # expense ไม่มีหัวข้อรวม
    tot_open = leaf_sum(opening)
    tot_close = leaf_sum(closing)
    return {
        "fiscal_year": fiscal_year, "round": rnd, "label": label,
        "start": start, "end": end,
        "opening": opening, "income": income, "closing": closing,
        "expense": expense, "rows": rows,
        "matrix": matrix, "missing": missing,
        "totals": {"opening": tot_open, "income": tot_in, "expense": tot_out,
                   "closing": tot_close},
        # เว็บ e-Budget ตรวจว่า (ยกมา + รายรับ) − รายจ่าย = คงเหลือ
        "check": round(tot_open + tot_in - tot_out - tot_close, 2),
        "unmapped": sorted(x for x in unmapped if x),
    }
