# -*- coding: utf-8 -*-
"""บันทึกขอใช้งบประมาณ (เอกสารต้นเรื่องของเรื่องจัดซื้อ/จัดจ้าง)

เจ้าของสั่ง 2026-11-14: ออกหรือไม่ก็ได้ (สวิตช์ในฟอร์ม) ใช้แม่แบบเดียวกับที่โรงเรียนใช้จริง
- ประเภทค่าใช้จ่ายให้คนเลือกเองทุกรายการ ห้ามเดาจากราคา
  (ราคาต่อหน่วยเกิน 10,000 ไม่จำเป็นต้องเป็นครุภัณฑ์เสมอ)
- ค่าใช้จ่ายอื่น (ค่าอาหาร ค่าวิทยากร ฯลฯ) เป็นข้อมูลในบันทึกเท่านั้น ไม่สร้างรายการเงิน
- ไม่พิมพ์เลขบัตรประชาชนกรรมการ (PDPA)
"""
import json

COST_TYPES = ["ค่าวัสดุ", "ค่าใช้สอย", "ค่าตอบแทน", "ค่าสาธารณูปโภค", "ค่าครุภัณฑ์"]
# ลำดับหัวข้อในบันทึก
_ORDER = ["ค่าวัสดุ", "ค่าครุภัณฑ์", "ค่าใช้สอย", "ค่าตอบแทน", "ค่าสาธารณูปโภค"]


def default_type(proc_type: str) -> str:
    return "ค่าใช้สอย" if (proc_type or "ซื้อ") == "จ้าง" else "ค่าวัสดุ"


def item_type(item, proc_type: str) -> str:
    t = (getattr(item, "cost_type", "") or "").strip()
    return t if t in COST_TYPES else default_type(proc_type)


def parse_extra(raw) -> list:
    """JSON ในฐานข้อมูล -> list[dict] (ข้อมูลเสีย = รายการว่าง)"""
    try:
        rows = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not (r.get("name") or "").strip():
            continue
        t = r.get("type") if r.get("type") in COST_TYPES else "ค่าใช้สอย"
        try:
            qty = float(r.get("qty") or 0)
            price = float(r.get("price") or 0)
        except (TypeError, ValueError):
            qty, price = 0.0, 0.0
        out.append({"type": t, "name": r["name"].strip(), "qty": qty,
                    "unit": (r.get("unit") or "").strip(), "price": price})
    return out


def extra_from_form(form) -> str:
    """แถวค่าใช้จ่ายอื่นจากฟอร์ม -> JSON"""
    types, names = form.getlist("bx_type"), form.getlist("bx_name")
    qtys, units, prices = form.getlist("bx_qty"), form.getlist("bx_unit"), form.getlist("bx_price")
    rows = []
    for i, nm in enumerate(names):
        nm = (nm or "").strip()
        if not nm:
            continue
        def g(lst, d=""):
            return lst[i] if i < len(lst) else d
        rows.append({"type": g(types), "name": nm, "qty": g(qtys, "0"), "unit": g(units), "price": g(prices, "0")})
    return json.dumps(parse_extra(json.dumps(rows)), ensure_ascii=False)


def _num(x) -> str:
    x = round(float(x or 0), 2)
    return f"{int(x):,}" if x == int(x) else f"{x:,.2f}"


def build_lines(proc) -> tuple[list, float]:
    """ข้อความรายการค่าใช้จ่ายในบันทึก จัดกลุ่มตามประเภท -> ([บรรทัด], ยอดรวม)

    บรรทัดหลัก: "1. ค่าวัสดุ จำนวน 3 รายการ เป็นเงิน 4,500 บาท ตามรายละเอียดดังแนบ"
    บรรทัดย่อย (ค่าใช้จ่ายอื่น): "   1.1 ค่าอาหารว่าง จำนวน 50 คน ๆ ละ 35 บาท เป็นเงิน 1,750 บาท"
    """
    groups = {t: {"items": [], "extra": []} for t in _ORDER}
    for it in proc.items:
        groups[item_type(it, proc.proc_type)]["items"].append(it)
    for x in parse_extra(getattr(proc, "budget_extra", "")):
        groups[x["type"]]["extra"].append(x)
    lines, total, n = [], 0.0, 0
    for t in _ORDER:
        g = groups[t]
        if not g["items"] and not g["extra"]:
            continue
        n += 1
        it_sum = sum(float(i.quantity or 0) * float(i.unit_price or 0) for i in g["items"])
        ex_sum = sum(x["qty"] * x["price"] for x in g["extra"])
        sub = it_sum + ex_sum
        total += sub
        if g["items"] and not g["extra"]:
            lines.append({"text": f"{n}. {t} จำนวน {len(g['items'])} รายการ เป็นเงิน {_num(sub)} บาท ตามรายละเอียดดังแนบ", "sub": False})
            continue
        lines.append({"text": f"{n}. {t} เป็นเงิน {_num(sub)} บาท ดังนี้", "sub": False})
        k = 0
        if g["items"]:
            k += 1
            lines.append({"text": f"{n}.{k} รายการตามรายละเอียดดังแนบ จำนวน {len(g['items'])} รายการ เป็นเงิน {_num(it_sum)} บาท", "sub": True})
        for x in g["extra"]:
            k += 1
            unit = f" {x['unit']}" if x["unit"] else ""
            lines.append({"text": f"{n}.{k} {x['name']} จำนวน {_num(x['qty'])}{unit} ๆ ละ {_num(x['price'])} บาท เป็นเงิน {_num(x['qty'] * x['price'])} บาท", "sub": True})
    return lines, round(total, 2)


def budget_numbers(db, proc) -> dict:
    """ข้อ 1-5: ได้รับอนุมัติ / ใช้ไปแล้ว / คงเหลือ / ขอครั้งนี้ / คงเหลือยกไป (จากทะเบียนโครงการ)"""
    from app.models import Project
    from app.services.budget import project_budget, project_remaining
    _, req = build_lines(proc)
    proj = db.get(Project, proc.project_id) if getattr(proc, "project_id", None) else None
    if not proj:
        return {"approved": None, "used": None, "left": None, "request": req, "carry": None}
    approved = float(project_budget(proj) or 0)
    left = float(project_remaining(proj) or 0)
    if proc.project_id == proj.id:          # ยอดของเรื่องนี้ถูกนับเป็น "ใช้ไปแล้ว" ด้วย -> ไม่นับซ้ำ
        left += float(proc.total_amount or 0)
    used = approved - left
    return {"approved": approved, "used": used, "left": left, "request": req, "carry": left - req}
