# -*- coding: utf-8 -*-
"""
nav.py
------
ฟังก์ชันสำหรับแถบนำทาง/แจ้งเตือนที่ใช้ได้ทุกหน้า (ลงทะเบียนเป็น Jinja global)
- nav_alerts()   : กระดิ่งแจ้งเตือนงานพัสดุ (ร่างค้าง/ใกล้ครบ/เลยกำหนด)
- nav_holidays() : ข้อมูลวันหยุดสำหรับปฏิทินลอย

แยกออกจาก routers เพื่อให้หลาย router ใช้ร่วมกันได้โดยไม่เกิด circular import
"""
from datetime import datetime
from functools import lru_cache

from app.models import Procurement
from app.services.thai_holidays import holiday_map


def nav_alerts():
    """รายการที่ต้องดำเนินการ (กระดิ่ง topbar): ร่างค้าง / รอตรวจรับ / ใกล้ครบ / เลยกำหนด
    เรียงด่วนสุดก่อน (เลยกำหนด -> ใกล้ครบ -> อื่น ๆ)"""
    from app.tenancy import current_school_id, session_for
    sid = current_school_id.get()
    if sid is None:                 # ยังไม่ได้เลือกโรงเรียน (เช่น หน้า login) -> ไม่มีแจ้งเตือน
        return []
    db = session_for(sid)
    try:
        today = datetime.now().date()
        rows = (db.query(Procurement)
                .filter(Procurement.status.in_(["ร่าง", "อนุมัติ"]))
                .order_by(Procurement.id.desc()).all())
        alerts = []
        for p in rows:
            if p.status == "ร่าง":
                level, reason = "info", "ยังเป็นร่าง (รออนุมัติ)"
            else:
                due = p.delivery_due_date
                if due:
                    d = (due.date() - today).days
                    if d < 0:
                        level, reason = "urgent", f"เลยกำหนดส่งมอบ {abs(d)} วัน"
                    elif d <= 7:
                        level, reason = "warn", f"ใกล้ครบกำหนดส่งมอบ (อีก {d} วัน)"
                    else:
                        level, reason = "info", "รอตรวจรับ"
                else:
                    level, reason = "info", "รอตรวจรับ"
            alerts.append({
                "id": p.id, "level": level, "reason": reason,
                "title": f"{p.memo_no or ''} {p.proc_type or ''}{p.subject or ''}".strip(),
            })
        rank = {"urgent": 0, "warn": 1, "info": 2}
        alerts.sort(key=lambda a: rank[a["level"]])
        return alerts
    finally:
        db.close()


@lru_cache(maxsize=4)
def _holidays_cached(years_tuple):
    return holiday_map(list(years_tuple))


def nav_holidays():
    """ข้อมูลวันหยุดสำหรับปฏิทินลอย (ทุกหน้า) - ปีปัจจุบัน -1/+2 (cache ไว้)"""
    y = datetime.now().year
    return _holidays_cached((y - 1, y, y + 1, y + 2))
