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


OTHER_SLOTS = ("3.13", "2.5")      # ช่อง "อื่น ๆ" = เดาไม่ได้ ถ้ายังไม่ได้เลือกเอง


def slot_choices() -> list:
    """ช่องที่เลือกได้ (เฉพาะข้อย่อย หัวข้อรวมคิดจากลูกเอง) -> [(code, label)]"""
    return [(code, label if label.startswith(code + " ") else f"{code} {label}")
            for code, label, bold in ORDER if not bold and code not in PARENTS]


def slot_of(obj, fund_type: str = "") -> tuple:
    """(ช่อง, เลือกเองไหม) ของบัญชีหรือหมวดย่อย · เลือกเองไว้ = ใช้ค่านั้น ไม่งั้นเดาจากชื่อ"""
    own = (getattr(obj, "eb_slot", "") or "").strip()
    if own and own in {code for code, _l in slot_choices()}:
        return own, True
    return _target(getattr(obj, "name", "") or "", fund_type), False


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
    year_start = period(fiscal_year, 1)[0]
    start_day, end_day = start.date(), end.date()

    accounts = db.query(FinanceAccount).all()
    items = {it.id: it for it in db.query(AccountItem).filter_by(fiscal_year=fiscal_year).all()}
    txns = [t for t in db.query(FinanceTxn).filter_by(fiscal_year=fiscal_year).all()]

    acc_by_id = {a.id: a for a in accounts}

    def place(acct, it) -> tuple:
        """(ช่อง, ต้นทางที่ทำให้ลงช่องนี้) ของเงินในหมวดย่อย it ของบัญชี acct
        หมวดย่อยที่เลือกเองหรือชื่อตรง -> ใช้หมวด · ไม่งั้นใช้ของบัญชี"""
        ft = acct.fund_type if acct else ""
        if it is not None:
            code, own = slot_of(it, ft)
            if own or code not in OTHER_SLOTS:
                return code, ("item", it.id, own)
        if acct is None:
            return "3.13", ("none", 0, False)
        code, own = slot_of(acct, ft)
        if it is not None and code in OTHER_SLOTS and not own:
            return code, ("item", it.id, False)     # ทั้งหมวดและบัญชีเดาไม่ได้: ให้แก้ที่หมวด (เจาะจงกว่า)
        return code, ("account", acct.id, own)

    opening, income, closing = _bucket(), _bucket(), _bucket()
    expense = {s: 0.0 for s, _ in SOURCES}
    rows = []
    matrix, missing = {}, []          # ตารางไขว้ส่วนที่ 4 · รายการที่ยังไม่ได้ระบุหมวด
    other = {}                        # ต้นทางที่ยอดไปตกช่อง "อื่น ๆ" เพราะเดาไม่ได้ -> ยอดคงเหลือ/ความเคลื่อนไหว
    # ส่วนที่ 3 จริงของเว็บ = "ใครให้เงินมา" (ข้อ 2-6) ใช้ค่าที่ครูเลือกตอนบันทึกรับ (eb_code i2-i6)
    # แยกย่อยตามประเภทเงินไว้ช่วยเลือกข้อย่อยในเว็บ เช่น ข้อ 2 -> 3.1.1 รายหัว 100,000
    income_src, income_missing = {}, []

    def note_other(src, code, bal=0.0, moved=0.0):
        kind, oid, own = src
        if code in OTHER_SLOTS and not own and kind != "none":
            r = other.setdefault((kind, oid), {"balance": 0.0, "moved": 0.0})
            r["balance"] += bal
            r["moved"] += moved

    # ยอดยกมาต้นปีงบ: หมวดย่อยลงช่องของหมวด (ยอดยกมาแยกหมวดไว้แล้ว) ส่วนที่เหลือลงช่องของบัญชี
    # (เดิมลงทั้งก้อนตามชื่อบัญชี แต่รายการจ่ายลงตามหมวด -> ช่องหมวดติดลบ ช่องบัญชีเกิน)
    from app.services.asset_utils import opening_for
    for a in accounts:
        total = opening_for(a, fiscal_year)
        used = 0.0
        for it in (i for i in items.values() if i.account_id == a.id):
            amt = float(it.opening_balance or 0)
            if not amt:
                continue
            code, src = place(a, it)
            opening[code] += amt
            closing[code] += amt
            note_other(src, code, bal=amt)
            used += amt
        rest = round(total - used, 2)
        code, src = place(a, None)
        opening[code] += rest
        closing[code] += rest
        note_other(src, code, bal=rest)

    for t in txns:
        acct = acc_by_id.get(t.account_id)
        it = items.get(t.item_id) if t.item_id else None
        code, src = place(acct, it)
        amt = float(t.amount or 0)
        # Compare calendar days, including transactions late on the closing day.
        # Undated legacy entries belong to the same provisional period in both rounds.
        d = t.date or year_start
        day = d.date()
        if day <= end_day:
            note_other(src, code, bal=amt if t.kind == "in" else -amt, moved=amt)
        inside = start_day <= day <= end_day
        before = day < start_day
        if t.kind == "in":
            if before or inside:
                closing[code] += amt
            if before:
                opening[code] += amt
            if inside:
                income[code] += amt
                src_in = (getattr(t, "eb_code", "") or "").strip()
                if src_in.startswith("i"):
                    by = income_src.setdefault(src_in, {})
                    by[code] = by.get(code, 0.0) + amt
                else:
                    income_missing.append(t.id)
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
        "unmapped": _unmapped_rows(other, acc_by_id, items),
        "income_src": income_src, "income_missing": income_missing,
        "n_in_period": sum(1 for t in txns if t.date and start_day <= t.date.date() <= end_day),
        "undated": [t.id for t in txns if not t.date],
    }


def checklist(d: dict, fiscal_year: int, rnd: int) -> dict:
    """ขั้นตอนก่อนกรอก e-Budget (กล่องรายการเริ่มต้นแบบเดียวกับงานอื่น) ติ๊กเองจากตัวเลขจริง"""
    from app.services.module_setup import _pack
    fill = f"/finance/ebudget/fill?year={fiscal_year}&round={rnd}"
    n_un = len(d["unmapped"])
    steps = [
        dict(title="ตรวจวันที่รายการรับ–จ่าย", done=not d.get("undated"),
             detail="ระบุวันที่ครบแล้ว" if not d.get("undated") else "มีรายการไม่ระบุวันที่ กรุณาแก้วันที่ก่อนนำตัวเลขไปใช้",
             href=f"/finance/cashbook?year={fiscal_year}", cta="ตรวจรายการ"),
        dict(title="ลงรายการรับ-จ่ายของงวดนี้ในทะเบียนคุมเงิน", done=d["n_in_period"] > 0,
             detail=(f"มี {d['n_in_period']} รายการในงวดนี้" if d["n_in_period"]
                     else "ยังไม่มีรายการในงวดนี้ ตัวเลข e-Budget คำนวณจากทะเบียนคุมเงินทั้งหมด"),
             href=f"/finance/accounts?year={fiscal_year}", cta="ไปทะเบียนคุมเงิน"),
        dict(title="บอกระบบว่าเงินแต่ละบัญชีลงช่องไหน", done=not n_un,
             detail=("ระบบรู้ช่องของเงินทุกบัญชีแล้ว (ส่วนที่ 2 และ 5)" if not n_un
                     else f"มี {n_un} บัญชี/หมวดที่ระบบเดาช่องไม่ได้ ยอดไปรวมอยู่ช่อง \"อื่น ๆ\""),
             href="#eb-slots", cta="เลือกช่องให้บัญชี"),
        dict(title="ระบุที่มาของเงินรับทุกรายการ (ส่วนที่ 3)", done=not d["income_missing"],
             detail=("ครบทุกรายการแล้ว" if not d["income_missing"]
                     else f"ยังไม่ระบุ {len(d['income_missing'])} รายการ ว่าใครให้เงินมา (ต้นสังกัด / อปท. / เงินนอกงบ ฯลฯ) "
                          "ระบบเดาไว้ให้แล้ว แค่ตรวจแล้วกดบันทึก"),
             href=fill, cta="เติมที่มาของเงิน"),
        dict(title="ระบุหมวดรายจ่ายทุกรายการ (ส่วนที่ 4)", done=not d["missing"],
             detail=("ครบทุกรายการแล้ว" if not d["missing"]
                     else f"ยังไม่ระบุ {len(d['missing'])} รายการ ว่าจ่ายด้านไหน ระบบเดาไว้ให้แล้ว แค่ตรวจแล้วกดบันทึก"),
             href=fill, cta="เติมหมวดรายจ่าย"),
        dict(title="ยอดตรวจตรงกัน (ยกมา + รับ − จ่าย = คงเหลือ)", done=d["check"] == 0,
             detail=("ตรงกันพอดี" if d["check"] == 0
                     else f"ต่างกัน {d['check']:,.2f} บาท มักเกิดจากลงรายการผิดงวดหรือยังลงไม่ครบ"),
             href=f"/finance/cashbook?year={fiscal_year}", cta="ตรวจสมุดเงินสด"),
    ]
    return _pack(steps)


def _unmapped_rows(other: dict, acc_by_id: dict, items: dict) -> list:
    """ต้นทางที่ยอดไปตกช่อง "อื่น ๆ" เพราะระบบเดาไม่ได้ (ยังไม่ได้เลือกเอง) · ยอดมากก่อน"""
    out = []
    for (kind, oid), v in other.items():
        if not round(v["balance"], 2) and not round(v["moved"], 2):
            continue
        if kind == "item":
            it = items.get(oid)
            if not it:
                continue
            acc = acc_by_id.get(it.account_id)
            out.append({"kind": "item", "id": oid, "name": it.name, "account": acc.name if acc else "",
                        "account_id": it.account_id, "balance": round(v["balance"], 2)})
        else:
            acc = acc_by_id.get(oid)
            if not acc:
                continue
            n_items = sum(1 for i in items.values() if i.account_id == oid)
            out.append({"kind": "account", "id": oid, "name": acc.name, "account": acc.name,
                        "account_id": oid, "balance": round(v["balance"], 2), "has_items": bool(n_items)})
    return sorted(out, key=lambda r: -abs(r["balance"]))
