# -*- coding: utf-8 -*-
"""
seller_config.py — ข้อมูลผู้ขาย/ผู้ประกอบการ (แก้ที่เดียว ใช้ทั้งหน้าเว็บ + ใบเสนอราคา + ใบเสร็จ)

หมายเหตุความปลอดภัย: ไฟล์นี้อยู่ในเรป (public) จึงใส่แค่ค่า placeholder
ข้อมูลส่วนตัวจริง (ชื่อ/ที่อยู่/เลขบัตร ปชช./เบอร์/บัญชี) ให้ใส่ในไฟล์ app/seller_local.py
ซึ่งไม่ขึ้น git (อยู่ใน .gitignore) — ระบบจะโหลดมาแทนที่ค่าด้านล่างให้อัตโนมัติ
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
