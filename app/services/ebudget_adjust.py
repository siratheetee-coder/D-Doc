# -*- coding: utf-8 -*-
"""ยอดที่ไม่มีในระบบ ของรอบ e-Budget ที่คร่อมวันเริ่มใช้ระบบ (โรงเรียนเริ่มใช้กลางรอบ)

ตัวอย่าง เริ่มใช้ 1 ม.ค. แต่ครั้งที่ 1 นับ 1 ต.ค. ระบบไม่รู้รับจ่าย ต.ค. ถึง ธ.ค. และยอดยกมาในระบบเป็นยอด ณ 1 ม.ค.
  ส่วนที่ 2  ครูกรอกยอดยกมาจริง ณ วันเริ่มรอบ แทนยอดของระบบ (เป็นตัวเลขในอดีต ไม่ขยับแล้ว)
  ส่วนที่ 3  รายรับก่อนเริ่มใช้ระบบ บวกเพิ่มจากยอดของระบบ
  ส่วนที่ 4  รายจ่ายก่อนเริ่มใช้ระบบ บวกเพิ่มจากยอดของระบบ (ข้อ x แหล่งเงิน)
  ส่วนที่ 5  ไม่กรอก ใช้ยอดจริงในทะเบียนเสมอ
บวกเพิ่ม ไม่แก้ทับ เพราะรายการใหม่ในระบบยังเดินต่อได้ (ลอง FinVouch แล้ว แบบแก้ทับ ยอดที่กรอกหายจากช่องแต่ยังถูกนับในยอดรวม)
กรอกครบแล้ว ยอดตรวจ ยกมา + รับ - จ่าย = คงเหลือ จะลงตัวเอง ไม่ลงตัว = ยังกรอกไม่ครบ
"""
SECTIONS = ("2", "3", "4")


def rows(db, fiscal_year: int, rnd: int) -> list:
    from app.models import EbudgetAdjust
    return (db.query(EbudgetAdjust).filter_by(fiscal_year=fiscal_year, round=rnd)
            .order_by(EbudgetAdjust.section, EbudgetAdjust.code, EbudgetAdjust.source).all())


def save(db, fiscal_year: int, rnd: int, section: str, code: str, source: str, amount: float, note: str = ""):
    """เพิ่มหรือแก้ยอด 1 ช่อง ยอด 0 (หรือว่าง) = ลบช่องนั้น"""
    from app.models import EbudgetAdjust
    from app.services.ebudget import SOURCES, slot_choices
    from app.services.ebudget_cat import EXPENSE, INCOME_LEAVES
    if section not in SECTIONS or rnd not in (1, 2):
        raise ValueError("ส่วนของ e-Budget ไม่ถูกต้อง")
    code, source = (code or "").strip(), (source or "").strip()
    ok = {"2": {c for c, _ in slot_choices()},
          "3": set(INCOME_LEAVES),
          "4": {c for _g, rs in EXPENSE for c, _l in rs}}[section]
    if code not in ok:
        raise ValueError("เลือกข้อใน e-Budget ก่อน")
    if section == "4":
        if source not in {k for k, _ in SOURCES}:
            raise ValueError("เลือกแหล่งเงินก่อน")
    else:
        source = ""
    if not -1e9 < amount < 1e9:
        raise ValueError("จำนวนเงินไม่ถูกต้อง")
    row = (db.query(EbudgetAdjust)
           .filter_by(fiscal_year=fiscal_year, round=rnd, section=section, code=code, source=source).first())
    if not round(amount, 2) and section != "2":
        if row:
            db.delete(row)
        return None
    if row is None:
        row = EbudgetAdjust(fiscal_year=fiscal_year, round=rnd, section=section, code=code, source=source)
        db.add(row)
    row.amount, row.note = round(amount, 2), (note or "").strip()[:200]
    return row


def remove(db, fiscal_year: int, rnd: int, adj_id: int):
    from app.models import EbudgetAdjust
    row = db.get(EbudgetAdjust, adj_id)
    if row and (row.fiscal_year, row.round) == (fiscal_year, rnd):
        db.delete(row)


def apply(adjs, opening, income_src, matrix, expense) -> dict:
    """ใส่ยอดที่กรอกเพิ่มลงตัวเลขของ build() (ก่อนรวมหัวข้อ) คืนสิ่งที่ใช้ทำเครื่องหมาย * ในตาราง"""
    mark = {"2": {}, "3": {}, "4": {}, "in": 0.0}
    for a in adjs:
        amt = float(a.amount or 0)
        if a.section == "2":
            mark["2"][a.code] = (round(opening.get(a.code, 0.0), 2), amt)     # (ยอดระบบ, ยอดจริงที่กรอก)
            opening[a.code] = amt
        elif a.section == "3":
            by = income_src.setdefault(a.code, {})
            by["_adj"] = by.get("_adj", 0.0) + amt
            mark["3"][a.code] = amt
            mark["in"] += amt
        elif a.section == "4":
            matrix.setdefault(a.code, {k: 0.0 for k in expense})[a.source] += amt
            expense[a.source] += amt
            mark["4"][f"{a.code}|{a.source}"] = amt
    return mark
