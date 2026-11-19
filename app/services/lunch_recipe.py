"""สูตรอาหาร: คำนวณวัตถุดิบตามจำนวนนักเรียน 3 ระดับ เทียบงบรายวัน และรวมใบซื้อของรายสัปดาห์"""
import math
from datetime import datetime, timedelta

from app.models import LunchRecipe, LunchHireRound

STEP = {"กก.": 0.5, "กิโลกรัม": 0.5, "ฟอง": 10, "ลิตร": 0.5}


def tiers(prog):
    """จำนวนนักเรียน (อนุบาล, ประถม, มัธยม) จากชั้นที่ตั้งไว้ในโครงการ"""
    k = p = m = 0
    for c in prog.classes:
        lv, n = (c.level or "").strip(), int(c.num_students or 0)
        if lv.startswith("อ"): k += n
        elif lv.startswith("ม"): m += n
        else: p += n
    return k, p, m


def step_of(unit):
    return STEP.get((unit or "").strip(), 1)


def round_up(q, unit):
    s = step_of(unit)
    return round(math.ceil(q / s - 1e-9) * s, 2) if q > 0 else 0.0


def last_prices(prog):
    """ราคาต่อหน่วยล่าสุดของวัตถุดิบแต่ละชื่อ (จากที่เคยกรอก)"""
    out = {}
    for ig in sorted(prog.ingredients, key=lambda x: (x.date or datetime.min, x.id)):
        if (ig.unit_price or 0) > 0:
            out[(ig.name or "").strip()] = float(ig.unit_price)
    return out


def calc(recipe, t, prices):
    k, p, m = t
    rows = []
    for it in recipe.items:
        q = ((it.q_k or 0) * k + (it.q_p or 0) * p + (it.q_m or 0) * m) / 10
        rows.append({"name": it.name, "unit": it.unit or "", "raw": round(q, 2),
                     "qty": round_up(q, it.unit), "price": prices.get(it.name.strip(), 0.0),
                     "locked": bool(it.locked)})
    return rows


def match(db, menu_text):
    """หาสูตรจากชื่อเมนูของวัน ชื่อสูตรต้องอยู่ในข้อความเมนู (ยาวสุดชนะ)"""
    text = (menu_text or "").replace(" ", "")
    best = None
    for r in db.query(LunchRecipe).all():
        n = (r.name or "").replace(" ", "")
        if n and n in text and (best is None or len(n) > len(best.name.replace(" ", ""))):
            best = r
    return best


def current_round(prog, back=""):
    import re
    m = re.search(r"/lunch/round/(\d+)/", back or "")
    if m:
        for r in prog.rounds:
            if r.id == int(m.group(1)):
                return r
    rws = [r for r in prog.rounds if r.start_date]
    return max(rws, key=lambda r: r.start_date) if rws else None


def daily_budget(prog, rnd):
    """งบวัตถุดิบต่อวัน = นักเรียน x อัตรารายหัว - (ค่าจ้างแม่ครัว + ค่าเชื้อเพลิง) / จำนวนวันของรอบ"""
    per = float(prog.total_students or 0) * float(prog.rate_per_head or 0)
    if rnd and (rnd.days or 0) > 0:
        wage = float(getattr(rnd, "cook_wage", 0) or 0) if prog.operate_mode == "person" else 0.0
        fuel = float(getattr(rnd, "fuel_cost", 0) or 0)
        per -= (wage + fuel) / rnd.days
    return round(per, 2)


def week_list(db, prog, monday):
    """ใบซื้อของ: รวมวัตถุดิบจากสูตรของเมนูวันจันทร์ถึงศุกร์"""
    t, prices = tiers(prog), last_prices(prog)
    end = monday + timedelta(days=4)
    agg, days, missing = {}, [], []
    for mn in sorted((x for x in prog.menus if x.date and monday.date() <= x.date.date() <= end.date()),
                     key=lambda x: x.date):
        r = match(db, mn.main)
        if not r:
            missing.append(mn); continue
        days.append(mn)
        wd = "จ. อ. พ. พฤ. ศ.".split()[mn.date.weekday()] if mn.date.weekday() < 5 else ""
        for row in calc(r, t, prices):
            key = (row["name"], row["unit"])
            a = agg.setdefault(key, {"name": row["name"], "unit": row["unit"], "raw": 0.0,
                                     "price": row["price"], "days": []})
            a["raw"] += row["raw"]
            if wd and wd not in a["days"]: a["days"].append(wd)
    items = []
    for a in agg.values():
        a["qty"] = round_up(a["raw"], a["unit"]); a["amount"] = round(a["qty"] * a["price"], 2)
        items.append(a)
    items.sort(key=lambda a: a["name"])
    return {"rows": items, "days": days, "missing": missing,
            "total": round(sum(a["amount"] for a in items), 2)}
