# -*- coding: utf-8 -*-
"""
diskspace.py - เฝ้าดูพื้นที่ดิสก์ของเซิร์ฟเวอร์

ทำไมต้องมี: ถ้าดิสก์เต็ม SQLite จะเขียนไม่ได้ (อ่านได้ แต่บันทึกไม่ได้) และที่อันตราย
กว่านั้นคือ "การสำรองข้อมูลจะล้มเหลว" พอดีกับตอนที่ต้องการมันที่สุด จึงต้องรู้ล่วงหน้า

ใช้:
  disk_status()      -> dict สถานะพื้นที่ (โชว์ในคอนโซลผู้ขาย / /healthz)
  check_and_alert()  -> ส่งอีเมลเตือนผู้ขาย (วันละครั้ง) ถ้าพื้นที่เหลือน้อย
"""
import shutil
from datetime import date

from app.database import get_data_dir

WARN_PCT = 80        # ใช้เกิน 80% = เริ่มเตือน
CRIT_PCT = 90        # ใช้เกิน 90% = วิกฤต ต้องรีบจัดการ
MIN_FREE_GB = 2.0    # หรือเหลือน้อยกว่า 2 GB ก็ถือว่าวิกฤต แม้ % จะยังไม่ถึง

_last_alert_date = None      # กันส่งอีเมลซ้ำหลายรอบต่อวัน


def _gb(n: int) -> float:
    return round(n / (1024 ** 3), 2)


def disk_status() -> dict:
    """สถานะพื้นที่ดิสก์ของพาร์ทิชันที่เก็บ data/"""
    try:
        total, used, free = shutil.disk_usage(get_data_dir())
    except OSError as e:
        return {"ok": False, "error": str(e), "level": "unknown"}
    pct = round(used * 100 / total, 1) if total else 0.0
    free_gb = _gb(free)
    if pct >= CRIT_PCT or free_gb < MIN_FREE_GB:
        level = "critical"
    elif pct >= WARN_PCT:
        level = "warn"
    else:
        level = "ok"
    return {"ok": True, "level": level, "percent": pct,
            "total_gb": _gb(total), "used_gb": _gb(used), "free_gb": free_gb}


def status_text(st: dict | None = None) -> str:
    """ข้อความสรุปสั้น ๆ (ภาษาไทย) ไว้โชว์/ส่งอีเมล"""
    st = st or disk_status()
    if not st.get("ok"):
        return f"อ่านพื้นที่ดิสก์ไม่ได้: {st.get('error')}"
    return (f"ใช้ไป {st['percent']}% ({st['used_gb']} GB จาก {st['total_gb']} GB) "
            f"· เหลือ {st['free_gb']} GB")


def check_and_alert() -> dict:
    """เช็กพื้นที่ + ส่งอีเมลเตือนผู้ขายถ้าใกล้เต็ม (ส่งได้วันละครั้ง)"""
    global _last_alert_date
    st = disk_status()
    if st.get("level") not in ("warn", "critical"):
        return st
    today = date.today()
    if _last_alert_date == today:
        return st
    try:
        from app.seller_config import SELLER
        from app.services.mailer import send_email, smtp_configured
        to = (SELLER.get("notify_email") or SELLER.get("email") or "").strip()
        if not (to and smtp_configured()):
            return st
        crit = st["level"] == "critical"
        subject = ("[Easy Ekkasan] พื้นที่ดิสก์วิกฤต - ต้องจัดการด่วน" if crit
                   else "[Easy Ekkasan] พื้นที่ดิสก์ใกล้เต็ม")
        send_email(to, subject,
                   f"<p><b>เซิร์ฟเวอร์เหลือพื้นที่น้อย</b></p><p>{status_text(st)}</p>"
                   "<p>ถ้าดิสก์เต็ม ระบบจะ <b>บันทึกข้อมูลไม่ได้</b> (อ่านได้อย่างเดียว) "
                   "และ <b>การสำรองข้อมูลจะล้มเหลว</b></p>"
                   "<p>แนะนำ: อัปเกรดแพ็กเกจ VPS หรือย้ายไฟล์เก่าออก</p>")
        _last_alert_date = today
    except Exception as e:      # แจ้งเตือนล้มเหลวต้องไม่ทำให้ระบบหลักพัง
        print("[diskspace] ส่งอีเมลเตือนไม่สำเร็จ:", e)
    return st
