# -*- coding: utf-8 -*-
"""
lunch_meals.py - ยอดนักเรียนที่รับประทานรายวัน รายชั้น ของงานจ้างเหมาประกอบอาหาร (ปรุงสำเร็จ)

คู่มือการดำเนินงานโครงการอาหารกลางวัน พ.ศ. 2569 (สพฐ.) ตัวอย่าง TOR ข้อ 5:
  ผู้รับจ้างสรุปรายการประกอบอาหารรายวันในงวด โรงเรียนชำระเงิน "ตามที่ได้ประกอบอาหารจริงในแต่ละงวด"
  ค่าปรับรายวันร้อยละ 0.2 ของมูลค่าอาหารในวันที่ไม่ได้ส่งมอบ (กค (กวจ) 0405.2/ว 116)

ค่าจ้างงวด = ยอดนักเรียนรวมในงวด x ราคาต่อหัว (ของโครงการ)
ระบบตั้งยอดงวดให้เองเมื่อบันทึกยอดครบทุกวันในงวด และงวดนั้นยังไม่จ่าย (แก้ยอดเองได้เหมือนเดิม)
"""
from datetime import datetime, timedelta

PENALTY_RATE = 0.002      # ร้อยละ 0.2 ต่อวัน
WHT_RATE = 0.01           # หักภาษี ณ ที่จ่าย ร้อยละ 1 (เท่ากับเอกสารขอเบิกจ่ายรายงวด)


def workdays(inst):
    """วันทำการในงวด (หักวันหยุดราชการ/เสาร์-อาทิตย์) เป็น date เรียงตามวัน"""
    from app.services.thai_holidays import is_workday, holiday_map
    if not inst.start_date or not inst.end_date:
        return []
    base = (inst.round.program.year or 2568) - 543
    hs = set(holiday_map([base - 1, base, base + 1]).keys())
    out, d, e = [], inst.start_date.date(), inst.end_date.date()
    while d <= e:
        if is_workday(d, hs):
            out.append(d)
        d += timedelta(days=1)
    return out


def counts(db, prog, days) -> dict:
    """{date: {class_id: count}} ของวันที่บันทึกไว้แล้ว"""
    from app.models import LunchMealCount
    if not days:
        return {}
    lo = datetime(days[0].year, days[0].month, days[0].day)
    hi = datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, 59)
    out = {}
    for r in (db.query(LunchMealCount)
              .filter(LunchMealCount.program_id == prog.id,
                      LunchMealCount.date >= lo, LunchMealCount.date <= hi)):
        out.setdefault(r.date.date(), {})[r.class_id] = int(r.count or 0)
    return out


def save_day(db, prog, day, per_class: dict) -> None:
    """บันทึกจำนวนรายชั้นของวันหนึ่ง (แทนที่ของเดิม)"""
    from app.models import LunchMealCount
    dt = datetime(day.year, day.month, day.day)
    have = {r.class_id: r for r in db.query(LunchMealCount).filter_by(program_id=prog.id, date=dt)}
    for cid, n in per_class.items():
        n = max(0, int(n))
        if cid in have:
            have[cid].count = n
        else:
            db.add(LunchMealCount(program_id=prog.id, date=dt, class_id=cid, count=n))


def summary(db, inst) -> dict:
    """สรุปงวด: วันทำการ / บันทึกแล้ว / ยอดนักเรียนรวม / ค่าจ้างตามยอด / ค่าปรับ / ภาษี / จ่ายสุทธิ"""
    prog = inst.round.program
    days = workdays(inst)
    got = counts(db, prog, days)
    meals = sum(sum(v.values()) for v in got.values())
    rate = float(prog.rate_per_head or 0)
    value = round(meals * rate, 2)
    recorded = sum(1 for d in days if d in got)
    complete = bool(days) and recorded == len(days)
    amount = float(inst.amount or 0)
    # มูลค่าอาหารต่อวันของงวด ใช้คิดค่าปรับรายวัน
    per_day = (amount / len(days)) if days else 0.0
    penalty = round((inst.penalty_days or 0) * PENALTY_RATE * per_day, 2)
    wht = round(amount * WHT_RATE, 2)
    return {
        "days": days, "counts": got, "recorded": recorded, "complete": complete,
        "meals": meals, "rate": rate, "value": value, "amount": amount,
        "penalty": penalty, "wht": wht, "net": round(amount - wht - penalty, 2),
        "eligible": int(prog.total_students or 0),
        "matches": abs(value - amount) < 0.005,
    }


def apply_amount(db, inst) -> bool:
    """ตั้งค่าจ้างงวด = ยอดนักเรียนรวม x ราคาต่อหัว เมื่อบันทึกครบทุกวัน และงวดยังไม่จ่าย คืน True ถ้าเปลี่ยน"""
    if (inst.status or "") == "จ่ายแล้ว":
        return False
    s = summary(db, inst)
    if not s["complete"] or s["matches"]:
        return False
    inst.amount = s["value"]
    return True


# ---------------- จ่ายครั้งเดียวทั้งรอบ (ส่งมอบ/ตรวจรับรายงวด) ----------------
DONE_INSPECT = ("ตรวจรับแล้ว", "จ่ายแล้ว")


def pays_by_round(rnd) -> bool:
    """รอบจ้างเหมาที่ตั้งให้จ่ายเงินครั้งเดียวทั้งรอบ (งวดใช้ส่งมอบ/ตรวจรับเท่านั้น)"""
    return (getattr(rnd.program, "operate_mode", "hire") == "hire"
            and (getattr(rnd, "pay_mode", "") or "installment") == "round")


def round_pay(db, rnd) -> dict:
    """ยอดจ่ายทั้งรอบ = รวมค่าจ้างทุกงวด (แต่ละงวดคิดจากยอดนักเรียนรายวัน) หักค่าปรับรวม และภาษีร้อยละ 1"""
    insts = list(rnd.installments)
    rows = [(i, summary(db, i)) for i in insts]
    amount = round(sum(float(i.amount or 0) for i in insts), 2)
    penalty = round(sum(s["penalty"] for _, s in rows), 2)
    wht = round(amount * WHT_RATE, 2)
    return {
        "rows": rows, "amount": amount, "penalty": penalty, "wht": wht,
        "net": round(amount - wht - penalty, 2),
        "meals": sum(s["meals"] for _, s in rows),
        "inspected": sum(1 for i in insts if (i.status or "") in DONE_INSPECT),
        "total": len(insts),
        "ready": bool(insts) and all((i.status or "") in DONE_INSPECT for i in insts),
        "paid": (rnd.status or "") == "จ่ายแล้ว",
    }
