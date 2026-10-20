# -*- coding: utf-8 -*-
"""หน้า "เริ่มต้นใน 10 นาที" (/start) - รวมขั้นที่จำเป็นจริง ๆ ของทุกงานที่โรงเรียนใช้ไว้หน้าเดียวตามลำดับ

ไม่ตรวจข้อมูลเอง: หยิบขั้นจากรายการเริ่มต้นของแต่ละงาน (*_setup.setup_steps / module_setup.*_steps)
มาเป็นตัวตั้ง ติ๊กตรงกับกล่องในหน้างานนั้นเสมอ · แต่ละขั้นมีเวลาโดยประมาณ รวมแล้วราว 10 นาที
ขั้นที่เหลือของแต่ละงานอยู่ในหน้างานนั้น (การ์ด "ทำต่อในแต่ละงาน")
"""
from app.modules import MODULE_KEYS, MODULE_LABELS

# (งาน, ชื่อขั้นในรายการของงานนั้น (ขึ้นต้นด้วย), นาทีโดยประมาณ)
CORE = {
    "finance": [("สร้างบัญชีเงิน", 1), ("กรอกยอดยกมาแยกหมวด", 1)],
    "procurement": [("เพิ่มผู้ขายหรือผู้รับจ้าง", 1)],
    "academic": [("ตั้งปฏิทินปีการศึกษา", 1), ("สร้างห้องเรียนและดึงนักเรียน", 1)],
    "admin": [("ตั้งอักษรนำเลขที่หนังสือ", 1)],
    "lunch": [("ตั้งโครงการปีการศึกษา", 1)],
    "hr": [("ตั้งอีเมลผู้อนุมัติ", 1)],
}
BASIC = [("procurement", "กรอกข้อมูลโรงเรียนและผู้ลงนาม", 2), ("procurement", "เพิ่มรายชื่อบุคลากร", 2),
         ("hr", "อัปโหลดลายเซ็นผู้อำนวยการ", 1)]


def module_setups(db, school, modules) -> dict:
    """{งาน: รายการเริ่มต้นเต็มของงานนั้น} (ตัวเดียวกับกล่องในหน้างาน)"""
    from app.thai_utils import current_fiscal_year
    from app.routers.academic import _acad_year
    from app.services import module_setup as ms
    fy = current_fiscal_year()
    out = {}
    for m in modules:
        try:
            if m == "finance":
                from app.services.finance_setup import setup_steps
                out[m] = setup_steps(db, fy, school)
            elif m == "procurement":
                from app.services.procurement_setup import setup_steps
                out[m] = setup_steps(db, fy, school)
            elif m == "academic":
                from app.services.academic_setup import setup_steps
                out[m] = setup_steps(db, _acad_year(db))
            elif m == "admin":
                out[m] = ms.admin_steps(db, school)
            elif m == "lunch":
                out[m] = ms.lunch_steps(db, _acad_year(db))
            elif m == "hr":
                out[m] = ms.hr_steps(db, school)
        except Exception as e:  # noqa: BLE001  งานไหนคำนวณไม่ได้ อย่าให้ทั้งหน้าพัง
            print("[quick-start]", m, e)
    return out


def _find(setup, title):
    return next((s for s in (setup or {}).get("steps", []) if s["title"].startswith(title)), None)


def build(db, school, modules) -> dict:
    """{sections: [{key, label, steps:[{title, detail, href, cta, done, minutes}]}],
        total, done, minutes_left, rest: [{key, label, done, total, href}]}"""
    modules = [m for m in MODULE_KEYS if m in set(modules)] or list(MODULE_KEYS)
    # ขั้นพื้นฐานใช้รายการของพัสดุ/บุคคลเป็นตัวตั้ง แม้โรงเรียนไม่ได้ใช้สองงานนั้น (ข้อมูลโรงเรียน/บุคลากรใช้ทุกงาน)
    setups = module_setups(db, school, set(modules) | {"procurement", "hr"})
    sections, seen = [], set()

    def take(mod, title, minutes):
        s = _find(setups.get(mod), title)
        if not s or s["title"] in seen:
            return None
        seen.add(s["title"])
        return dict(title=s["title"], detail=s.get("detail", ""), href=s["href"], cta=s.get("cta", "ไปทำ"),
                    done=bool(s["done"]), minutes=minutes)

    basic = [x for x in (take(m, t, n) for m, t, n in BASIC) if x]
    sections.append(dict(key="basic", label="พื้นฐาน ใช้ร่วมกันทุกงาน", steps=basic))
    for m in modules:
        steps = [x for x in (take(m, t, n) for t, n in CORE.get(m, [])) if x]
        if steps:
            sections.append(dict(key=m, label=MODULE_LABELS[m], steps=steps))

    all_steps = [s for sec in sections for s in sec["steps"]]
    n = 0
    for s in all_steps:
        n += 1
        s["n"] = n
    nxt = next((s for s in all_steps if not s["done"]), None)
    rest = []
    for m in modules:
        st = setups.get(m)
        if st:
            rest.append(dict(key=m, label=MODULE_LABELS[m], done=st["done"], total=st["total"],
                             complete=st["complete"], href=_module_home(m)))
    return dict(sections=sections, total=len(all_steps), done=sum(s["done"] for s in all_steps),
                minutes_total=sum(s["minutes"] for s in all_steps),
                minutes_left=sum(s["minutes"] for s in all_steps if not s["done"]),
                next=nxt, complete=nxt is None, rest=rest)


def _module_home(m) -> str:
    return {"procurement": "/procurement", "admin": "/admin", "finance": "/finance", "lunch": "/lunch",
            "hr": "/hr", "academic": "/academic"}[m]


def tenant_modules(tenant_id) -> list:
    """งานที่โรงเรียนเปิดใช้ · ทดลองใช้/ข้อมูลว่าง = ทุกงาน"""
    if not tenant_id:
        return list(MODULE_KEYS)
    try:
        from app.accounts import acc_session, Tenant, parse_modules
        db = acc_session()
        try:
            t = db.get(Tenant, tenant_id)
            mods = parse_modules(t.modules) if t else set()
            if not t or (t.plan or "") in ("trial", "sandbox") or not mods:
                return list(MODULE_KEYS)
            return [m for m in MODULE_KEYS if m in mods]
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return list(MODULE_KEYS)
