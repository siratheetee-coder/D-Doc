"""นำเข้าเมนู + วัตถุดิบ จากรายงาน "วัตถุดิบและปริมาณการจัดซื้อ" ของ Thai School Lunch

ครูคัดลอกตารางรายงานมาวาง หน้าเว็บแปลงเป็นแถวของเซลล์ (list[list[str]])
แต่ละแถวท้าย 5 เซลล์คือ ส่วนประกอบ จำนวน หน่วย ราคาต่อหน่วย จำนวนเงิน
เซลล์ที่เกินมาด้านหน้าคือ ชื่ออาหาร และวันที่ (rowspan ทำให้บางแถวไม่มี)
"""
import math
import re
from datetime import datetime

SKIP_ING = ("นมวัว", "น้ำประปา")          # นมโรงเรียนเป็นงบอื่น น้ำประปาไม่ต้องซื้อ
FRUIT_HINT = ("ผลส่วนที่กินได้", "ชิ้นพอคำ")
WHOLE_UNITS = ("ฟอง", "ผล", "ชิ้น", "โครง", "กล่อง", "ลูก", "หัว", "ถุง", "ซอง", "แพ็ค")
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date(s):
    m = DATE_RE.match((s or "").strip())
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2500
    if y > 2400:
        y -= 543
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def report_students(text):
    m = re.search(r"จำนวน\s*\(คน\)\s*([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else 0


def dish_name(food):
    """ตัดขนาดสำรับออก เช่น 'ฝรั่ง 1/4 ผลส่วนที่กินได้ 62 กรัม' -> 'ฝรั่ง'"""
    s = re.split(r"\s\d", (food or "").strip(), maxsplit=1)[0].strip()
    return s or (food or "").strip()


def parse_rows(rows):
    """คืน list วัน: {date, dishes:[{food, fruit, milk, rice}], ings:[{name,qty,unit,price}]}"""
    days, cur_day, cur_food = [], None, ""
    for cells in rows:
        cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in cells]
        while cells and not cells[-1]:
            cells.pop()
        if len(cells) < 5:
            continue
        qty, price = _num(cells[-4]), _num(cells[-2])
        if qty is None or price is None or _num(cells[-1]) is None:
            continue
        head = cells[:-5]
        if head and _date(head[0]):
            cur_day = {"date": _date(head[0]), "dishes": [], "ings": []}
            days.append(cur_day)
            head = head[1:]
        if cur_day is None:
            continue
        if head and head[0]:
            cur_food = head[0]
            cur_day["dishes"].append({
                "food": cur_food,
                "fruit": any(h in cur_food for h in FRUIT_HINT),
                "milk": cur_food.startswith("นม"),
                "rice": cur_food.startswith("ข้าวสวย") or cur_food.startswith("ข้าวเหนียวนึ่ง"),
            })
        name = cells[-5]
        if not name or any(name.startswith(s) for s in SKIP_ING):
            continue
        cur_day["ings"].append({"name": name, "qty": qty, "unit": cells[-3], "price": price})
    return [d for d in days if d["dishes"] or d["ings"]]


def menu_text(day):
    mains = [dish_name(x["food"]) for x in day["dishes"] if not (x["fruit"] or x["milk"] or x["rice"])]
    fruits = [dish_name(x["food"]) for x in day["dishes"] if x["fruit"]]
    if not mains:   # วันที่มีแต่ข้าว ให้ใส่ข้าวไว้
        mains = [dish_name(x["food"]) for x in day["dishes"] if x["rice"]]
    return ", ".join(mains), ", ".join(fruits)


def scale_qty(qty, unit, factor):
    q = (qty or 0) * factor
    if any((unit or "").startswith(u) for u in WHOLE_UNITS):
        return float(math.ceil(q - 1e-9))
    return round(q, 2)


def merge_ings(ings):
    """วัตถุดิบเดียวกันหลายเมนูในวันเดียว รวมเป็นแถวเดียว"""
    out, idx = [], {}
    for g in ings:
        k = (g["name"], g["unit"])
        if k in idx:
            out[idx[k]]["qty"] += g["qty"]
        else:
            idx[k] = len(out)
            out.append(dict(g))
    return out


def price_memory(db):
    """ราคาที่โรงเรียนเคยใช้ล่าสุด ต่อ (ชื่อ, หน่วย)"""
    from app.models import LunchIngredient
    mem = {}
    q = (db.query(LunchIngredient).filter(LunchIngredient.unit_price > 0)
         .order_by(LunchIngredient.date, LunchIngredient.id))
    for r in q:
        mem[((r.name or "").strip(), (r.unit or "").strip())] = r.unit_price
    return mem


def build_preview(db, prog, rows, report_n, with_ings):
    actual = int(prog.total_students or 0)
    factor = (actual / report_n) if (report_n and actual) else 1.0
    mem = price_memory(db) if with_ings else {}
    have_menu = {m.date.date() for m in prog.menus if m.date}
    have_ing = {i.date.date() for i in prog.ingredients if i.date}
    out = []
    for d in parse_rows(rows):
        main, dessert = menu_text(d)
        ings = []
        if with_ings:
            for g in merge_ings(d["ings"]):
                k = (g["name"], g["unit"])
                ings.append({"name": g["name"], "unit": g["unit"],
                             "qty": scale_qty(g["qty"], g["unit"], factor),
                             "price": mem.get(k, g["price"]), "remembered": k in mem})
        dd = d["date"].date()
        out.append({"date": d["date"], "main": main, "dessert": dessert, "ings": ings,
                    "exists": dd in have_menu or (with_ings and dd in have_ing)})
    return {"days": out, "factor": factor, "actual": actual, "report_n": report_n}


def save(db, prog, days, replace, with_ings):
    """days: [{date, main, dessert, ings:[{name,qty,unit,price}]}] คืนจำนวนวันที่บันทึก"""
    from app.models import LunchMenu, LunchIngredient
    n = 0
    for d in days:
        dd = d["date"].date()
        menus = [m for m in prog.menus if m.date and m.date.date() == dd]
        olds = [i for i in prog.ingredients if i.date and i.date.date() == dd]
        if (menus or (with_ings and olds)) and not replace:
            continue
        for m in menus:
            db.delete(m)
        if d["main"] or d["dessert"]:
            db.add(LunchMenu(program_id=prog.id, date=d["date"], main=d["main"][:500],
                             dessert=d["dessert"][:500], note="จาก Thai School Lunch"))
        if with_ings:
            for i in olds:
                db.delete(i)
            for seq, g in enumerate([g for g in d["ings"] if g["name"]], 1):
                db.add(LunchIngredient(program_id=prog.id, date=d["date"], seq=seq, name=g["name"],
                                       quantity=g["qty"], unit=g["unit"], unit_price=g["price"]))
        n += 1
    db.commit()
    return n
