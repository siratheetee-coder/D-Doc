# -*- coding: utf-8 -*-
"""
seller_config.py - ข้อมูลผู้ขาย/ผู้ประกอบการ (แก้ที่เดียว ใช้ทั้งหน้าเว็บ + ใบเสนอราคา + ใบเสร็จ)

หมายเหตุความปลอดภัย: ไฟล์นี้อยู่ในเรป (public) จึงใส่แค่ค่า placeholder
ข้อมูลส่วนตัวจริง (ชื่อ/ที่อยู่/เลขบัตร ปชช./เบอร์/บัญชี) ให้ใส่ในไฟล์ app/seller_local.py
ซึ่งไม่ขึ้น git (อยู่ใน .gitignore) - ระบบจะโหลดมาแทนที่ค่าด้านล่างให้อัตโนมัติ
"""
SELLER = {
    # ---- ตัวตนผู้ขาย (ขึ้นหัวใบเสนอราคา/ใบเสร็จ) ----
    "name": "(ตั้งชื่อผู้ขายใน app/seller_local.py)",
    "address": "(ตั้งที่อยู่ใน app/seller_local.py)",
    "tax_id": "",                             # เลขประจำตัวผู้เสียภาษี (เลขบัตร ปชช.)
    "phone": "",
    "email": "",
    "signer": "",                             # ผู้ลงนาม/ผู้รับเงิน
    "logo": "/static/logo.png",

    # ---- ช่องทางรับเงิน (หน้า checkout) ----
    "promptpay_id": "",                       # เบอร์ (10 หลัก) หรือเลขบัตร ปชช. (13 หลัก) ที่ผูกพร้อมเพย์ -> ระบบสร้าง QR ตามยอดเงินให้เอง
    "promptpay_qr": "/static/landing/promptpay.png",   # (สำรอง) รูป QR แบบตายตัว ถ้าไม่ตั้ง promptpay_id
    "bank_name": "(ตั้งใน app/seller_local.py)",
    "bank_account_no": "xxx-x-xxxxx-x",
    "bank_account_name": "",
    "facebook": "https://www.facebook.com/profile.php?id=61590718498881&locale=th_TH",

    # ---- เงื่อนไขใบเสนอราคา ----
    "quote_valid_days": 30,                   # ยืนราคากี่วัน

    # ---- AI key กลาง (หลังบ้านอย่างเดียว) เปิดใช้เฉพาะสมาชิก ----
    "ai_api_key": "",                         # Anthropic API key ของคุณ (ตั้งใน seller_local.py) เว้นว่าง = ปิด AI

    # ---- แคมเปญบนการ์ดแพ็กเกจ (นับถอยหลัง + สิทธิ์คงเหลือ) ----
    # ตอนนี้ใช้ "ราคาปัจจุบัน" เป็นราคาแคมเปญเลย - ไม่ลดซ้ำ จึง **ไม่ระบุ bundle**
    # (ไม่ระบุคีย์ราคาไหน = ใช้ราคาปกติจาก REGULAR_PRICES ทั้งหมด)
    #
    # ตัวเลขที่แสดงเป็นของจริงทั้งคู่:
    #   - นับถอยหลัง = start + days (วันที่คุณตั้งเอง)
    #   - สิทธิ์คงเหลือ = slots ลบจำนวนโรงเรียนที่สมัครจริงตั้งแต่ start (members_since)
    # ถ้าหมดเวลาแล้วราคายังเท่าเดิม ควรเลื่อน start หรือปิด (enabled: False)
    # มิฉะนั้นจะกลายเป็นการเร่งเร้าที่ไม่ตรงความจริง
    "promo": {
        "enabled": True,                      # ปิดนับถอยหลัง/สิทธิ์ -> False
        "start": "2026-07-17",                # วันเริ่มนับ (พ.ศ. 2569)
        "days": 30,                           # แคมเปญกี่วัน
        "slots": 30,                          # จำนวนสิทธิ์ราคานี้
        # "bundle": ...,                      # ใส่ตัวเลขที่นี่ถ้าจะลดราคาช่วงแคมเปญเพิ่ม
    },

    # ---- SMTP สำหรับส่งอีเมลยืนยัน (ตั้งใน seller_local.py) ----
    # ถ้าไม่ตั้ง -> ระบบข้ามการยืนยันอีเมล (ใช้งาน local ได้เลย)
    "smtp_host": "",                          # เช่น smtp.gmail.com
    "smtp_port": 587,
    "smtp_user": "",                          # อีเมลผู้ส่ง
    "smtp_pass": "",                          # App Password (ไม่ใช่รหัสอีเมลปกติ)
    "smtp_from": "",                          # ชื่อ/อีเมลที่แสดงเป็นผู้ส่ง (ว่าง = ใช้ smtp_user)
    "base_url": "",                           # โดเมนจริง เช่น https://ddoc.example.com (ไว้ทำลิงก์ยืนยัน)
}

# โหลดข้อมูลจริงจากไฟล์ที่ไม่ขึ้น git (กันข้อมูลส่วนตัวรั่วในเรปสาธารณะ)
try:
    from app.seller_local import SELLER_LOCAL   # type: ignore
    SELLER.update(SELLER_LOCAL)
except ImportError:
    pass


# ---- ราคาปกติ (ยึดเป็นราคาตั้งต้น/ราคาขีดฆ่าตอนมีโปร) ----
# รวมงานแยก = 890+690+590+190+390+690 = 3,440 · แพ็กครบทุกงาน (bundle) = 2,690 (ประหยัด 750)
REGULAR_PRICES = {"p_proc": 890, "p_fin": 690, "p_admin": 590, "p_lunch": 190, "p_hr": 390,
                  "p_acad": 690, "bundle": 2690}

# ส่วนลดตามจำนวนงานที่เลือก (ยิ่งซื้อยิ่งลด) · ครบทุกงานใช้ราคา bundle แทน
TIER_DISCOUNT = {2: 100, 3: 200, 4: 300, 5: 400}


def pricing_context():
    """คืนราคาที่ใช้จริง + สถานะโปรโมชั่น (สำหรับหน้า landing/checkout)

    - โปรปิด หรือยังไม่ถึง/เลยกำหนด -> ใช้ราคาปกติ (promo_active=False)
    - โปรเปิดและอยู่ในช่วง -> ใช้ราคาโปร + นับวันเหลือ (promo_active=True)
    """
    from datetime import date, timedelta
    reg = dict(REGULAR_PRICES)
    promo = SELLER.get("promo") or {}
    active, days_left = False, 0
    if promo.get("enabled") and promo.get("start"):
        try:
            start = date.fromisoformat(str(promo["start"]).strip())
            end = start + timedelta(days=int(promo.get("days", 7)))
            if start <= date.today() <= end:
                active = True
                days_left = (end - date.today()).days + 1   # รวมวันนี้
        except (ValueError, TypeError):
            pass
    def _extra(px):
        """ราคารวมงานแยก (ราคาเต็ม/ขีดฆ่า) + ส่วนที่ประหยัดเมื่อซื้อ bundle"""
        from app.modules import MODULE_KEYS, MODULE_PRICE_KEY
        full = sum(px[MODULE_PRICE_KEY[k]] for k in MODULE_KEYS)
        return {"full_sum": full, "bundle_save": max(0, full - px["bundle"]),
                "tier_discount": dict(TIER_DISCOUNT)}

    if active:
        eff = {k: promo.get(k, reg[k]) for k in reg}
        slots = int(promo.get("slots", 30))
        try:
            from app.accounts import members_since
            used = members_since(promo["start"])
        except Exception:
            used = 0
        return {"prices": eff, "regular": reg, "promo_active": True,
                "promo_days_left": days_left, "promo_slots": slots,
                "promo_slots_left": max(0, slots - used),
                "promo_end_iso": end.isoformat(), **_extra(eff)}
    return {"prices": reg, "regular": reg, "promo_active": False,
            "promo_days_left": 0, "promo_slots": 0,
            "promo_slots_left": 0, "promo_end_iso": "", **_extra(reg)}


def price_for(modules) -> dict:
    """คำนวณราคาของชุดงานที่เลือก - **แหล่งความจริงเดียวของราคา**

    ฝั่งเซิร์ฟเวอร์ต้องเรียกอันนี้เสมอ ห้ามเชื่อยอดเงินที่ส่งมาจากหน้าเว็บ
    (JS บนหน้า checkout/landing มีหน้าที่แค่แสดงผลให้ตรงกับสูตรนี้)

    คืน {modules, count, list_sum, discount, total, label}
    """
    from app.modules import MODULE_KEYS, MODULE_PRICE_KEY, parse_modules, modules_csv, label_for
    px = pricing_context()["prices"]
    mods = parse_modules(modules_csv(modules))
    n = len(mods)
    list_sum = sum(px[MODULE_PRICE_KEY[k]] for k in MODULE_KEYS if k in mods)
    if n == len(MODULE_KEYS):                 # ครบทุกงาน -> ราคาแพ็ก
        total = px["bundle"]
    else:
        total = max(0, list_sum - TIER_DISCOUNT.get(n, 0))
    return {"modules": modules_csv(mods), "count": n, "list_sum": list_sum,
            "discount": max(0, list_sum - total), "total": total, "label": label_for(mods)}
