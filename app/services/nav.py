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

from app.models import Procurement, Contract
from app.services.thai_holidays import holiday_map

_CONTRACT_ALERT_DAYS = 15   # เตือนล่วงหน้ากี่วันก่อนสัญญาครบกำหนด (ให้ตรงกับหน้าทะเบียนคุมสัญญา)


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
                "href": f"/procurement/{p.id}",
            })
        # ---- สัญญาใกล้/เกินกำหนด (ตรรกะเดียวกับหน้าทะเบียนคุมสัญญา) ----
        try:
            crows = (db.query(Contract)
                     .filter(Contract.status != "สิ้นสุด", Contract.end_date.isnot(None)).all())
            for c in crows:
                dl = (c.end_date.date() - today).days
                if dl < 0:
                    level, reason = "urgent", f"สัญญาเลยกำหนด {abs(dl)} วัน"
                elif dl <= _CONTRACT_ALERT_DAYS:
                    level, reason = "warn", f"สัญญาใกล้ครบกำหนด (อีก {dl} วัน)"
                else:
                    continue
                alerts.append({
                    "id": c.id, "level": level, "reason": reason,
                    "title": " ".join(x for x in [c.contract_no, c.party or c.subject] if x) or "สัญญา",
                    "href": f"/procurement/contracts?year={c.fiscal_year}",
                })
        except Exception:
            pass
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


# ==================== แจ้งเตือนรายบุคคล (กระดิ่ง) ====================
def create_notice(db, person_id, title, reason="", link="", level="info"):
    """สร้างแจ้งเตือนให้บุคคล (ผู้เรียกเป็นคน commit เอง) - ข้ามถ้าไม่มี person_id"""
    if not person_id:
        return
    from app.models import Notification
    db.add(Notification(person_id=person_id, title=title, reason=reason, link=link, level=level))


def my_notices(person_id):
    """แจ้งเตือนที่ยังไม่อ่านของบุคคลนี้ (สำหรับกระดิ่ง) - รูปแบบเดียวกับ nav_alerts"""
    if not person_id:
        return []
    from app.tenancy import current_school_id, session_for
    from app.models import Notification
    sid = current_school_id.get()
    if sid is None:
        return []
    db = session_for(sid)
    try:
        rows = (db.query(Notification)
                .filter(Notification.person_id == person_id, Notification.read_at.is_(None))
                .order_by(Notification.created_at.desc()).limit(30).all())
        return [{"id": n.id, "title": n.title, "reason": n.reason,
                 "level": n.level or "info", "href": f"/notices/{n.id}"} for n in rows]
    finally:
        db.close()
