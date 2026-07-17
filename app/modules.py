# -*- coding: utf-8 -*-
"""
modules.py
----------
นิยาม "งาน" (โมดูล) ของระบบไว้ที่เดียว — ใช้ร่วมกันระหว่าง middleware, เทมเพลต,
หน้าขาย และคอนโซลผู้ขาย เพื่อไม่ให้ตรรกะ path->โมดูล แตกออกเป็นหลายที่แล้วเพี้ยนกัน

หมายเหตุสำคัญ:
- ไฟล์นี้ต้องไม่ import อะไรจาก app.* เพื่อกัน import วน (accounts/templating เรียกไฟล์นี้)
- MODULE_PREFIXES ยกมาจากตรรกะเดิมใน base.html (การตรวจโมดูลจาก path)
"""

MODULE_KEYS = ["procurement", "admin", "finance", "lunch", "hr", "academic"]

MODULE_LABELS = {
    "procurement": "งานพัสดุ",
    "admin": "งานธุรการ",
    "finance": "งานการเงิน",
    "lunch": "งานอาหารกลางวัน",
    "hr": "งานบุคคล",
    "academic": "งานวิชาการ",
}

# คีย์ราคาใน seller_config.REGULAR_PRICES
MODULE_PRICE_KEY = {
    "procurement": "p_proc",
    "admin": "p_admin",
    "finance": "p_fin",
    "lunch": "p_lunch",
    "hr": "p_hr",
    "academic": "p_acad",
}

# path ขึ้นต้นด้วยอะไร -> เป็นของงานไหน
# ระวัง: "/register." (มีจุด) คือ /register.xlsx = ทะเบียนพัสดุ
#        ส่วน "/register" เฉย ๆ คือหน้าสมัครสมาชิก (สาธารณะ) ต้องไม่โดนจับเป็นงานพัสดุ
MODULE_PREFIXES = {
    "admin": ["/admin"],
    "finance": ["/finance"],
    "lunch": ["/lunch"],
    "hr": ["/hr"],
    "academic": ["/academic"],
    "procurement": ["/procurement", "/assets", "/materials", "/requisitions",
                    "/catalog", "/textbooks", "/register."],
}

ALL_MODULES_CSV = ",".join(MODULE_KEYS)


def module_for_path(path: str):
    """คืนคีย์งานของ path นี้ · None = ไม่ใช่ของงานไหน (หน้าเลือกงาน/ตั้งค่า/วิธีใช้ ฯลฯ)

    เทียบแบบ "ตรงพอดี หรือ ตามด้วย /" เท่านั้น จึงไม่จับพลาดข้ามงาน:
      /admin, /admin/letters -> admin   แต่ /admin-console -> None (คอนโซลผู้ขาย ไม่ใช่งานธุรการ)
      /register.xlsx -> procurement     แต่ /register (หน้าสมัครสมาชิก) -> None
    """
    p = (path or "").rstrip("/") or "/"
    for key in MODULE_KEYS:
        for pre in MODULE_PREFIXES[key]:
            if pre.endswith("."):            # "/register." -> จับเฉพาะ /register.xlsx ฯลฯ
                if p.startswith(pre):
                    return key
            elif p == pre or p.startswith(pre + "/"):
                return key
    return None


def parse_modules(csv) -> set:
    """แปลง CSV เป็น set + ทิ้งคีย์แปลกปลอม (กันข้อมูลเพี้ยนใน DB)"""
    if not csv:
        return set()
    return {x.strip() for x in str(csv).split(",") if x.strip() in MODULE_KEYS}


def modules_csv(mods) -> str:
    """แปลง set/list เป็น CSV เรียงตามลำดับมาตรฐาน (MODULE_KEYS)"""
    s = set(mods or ())
    return ",".join(k for k in MODULE_KEYS if k in s)


def label_for(mods) -> str:
    """ข้อความแสดงผลของชุดงาน เช่น 'งานพัสดุ + งานการเงิน' หรือ 'ครบทุกงาน'"""
    s = parse_modules(modules_csv(mods)) if not isinstance(mods, set) else mods
    if not s:
        return ""
    if s == set(MODULE_KEYS):
        return "ครบทุกงาน"
    return " + ".join(MODULE_LABELS[k] for k in MODULE_KEYS if k in s)


def modules_from_label(label: str) -> set:
    """แกะชุดงานจากข้อความเก่า (lead ที่บันทึกไว้ก่อนมีคอลัมน์ modules)"""
    t = (label or "").strip()
    if not t:
        return set()
    if "ครบทุกงาน" in t:
        return set(MODULE_KEYS)
    return {k for k, lab in MODULE_LABELS.items() if lab in t}
