# -*- coding: utf-8 -*-
"""
nav.py
------
ฟังก์ชันสำหรับแถบนำทาง/แจ้งเตือนที่ใช้ได้ทุกหน้า (ลงทะเบียนเป็น Jinja global)
- nav_alerts()   : กระดิ่งแจ้งเตือน พัสดุ/การเงิน/บุคคล/รอ ผอ. อนุมัติ ตามสิทธิ์ของบัญชี
- nav_holidays() : ข้อมูลวันหยุดสำหรับปฏิทินลอย

แยกออกจาก routers เพื่อให้หลาย router ใช้ร่วมกันได้โดยไม่เกิด circular import
"""
from datetime import datetime
from functools import lru_cache

from app.models import Procurement, Contract
from app.services.thai_holidays import holiday_map

_CONTRACT_ALERT_DAYS = 15   # เตือนล่วงหน้ากี่วันก่อนสัญญาครบกำหนด (ให้ตรงกับหน้าทะเบียนคุมสัญญา)


_HEALTH_TTL = 180            # วินาที: ผลตรวจสุขภาพการเงินในกระดิ่ง (ตรวจ 27 ข้อทุกหน้าหนักไป จึงจำไว้ครู่หนึ่ง)
_health_cache = {}


def _alert(level, title, reason, href, tag):
    return {"level": level, "title": title, "reason": reason, "href": href, "tag": tag}


def _procurement_alerts(db, today):
    out, drafts, waiting = [], 0, 0
    for p in db.query(Procurement).filter(Procurement.status.in_(["ร่าง", "อนุมัติ"])).all():
        if p.status == "ร่าง":
            drafts += 1
            continue
        due = p.delivery_due_date
        d = (due.date() - today).days if due else None
        title = f"{p.memo_no or ''} {p.proc_type or ''}{p.subject or ''}".strip()
        if d is not None and d < 0:
            out.append(_alert("urgent", title, f"เลยกำหนดส่งมอบ {abs(d)} วัน", f"/procurement/{p.id}", "พัสดุ"))
        elif d is not None and d <= 7:
            out.append(_alert("warn", title, f"ใกล้ครบกำหนดส่งมอบ (อีก {d} วัน)", f"/procurement/{p.id}", "พัสดุ"))
        else:
            waiting += 1
    if waiting:
        out.append(_alert("info", f"รอตรวจรับ {waiting} เรื่อง", "อนุมัติแล้ว รอส่งมอบและตรวจรับ", "/procurement", "พัสดุ"))
    if drafts:
        out.append(_alert("info", f"ร่างค้าง {drafts} เรื่อง", "ยังไม่ได้อนุมัติ", "/procurement", "พัสดุ"))
    for c in db.query(Contract).filter(Contract.status != "สิ้นสุด", Contract.end_date.isnot(None)).all():
        dl = (c.end_date.date() - today).days
        if dl > _CONTRACT_ALERT_DAYS:
            continue
        title = " ".join(x for x in [c.contract_no, c.party or c.subject] if x) or "สัญญา"
        out.append(_alert("urgent" if dl < 0 else "warn", title,
                          f"สัญญาเลยกำหนด {abs(dl)} วัน" if dl < 0 else f"สัญญาใกล้ครบกำหนด (อีก {dl} วัน)",
                          f"/procurement/contracts?year={c.fiscal_year}", "พัสดุ"))
    return out


def _finance_alerts(db, sid):
    """ข้อที่ "ควรแก้" ในตรวจสุขภาพการเงิน + เงินยืม/ขอเบิก/เช็คที่ค้าง"""
    import time
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    hit = _health_cache.get((sid, fy))
    if hit and time.time() - hit[0] < _HEALTH_TTL:
        return hit[1]
    from app.services.finance_health import run
    h = run(db, fy)
    out = [_alert("urgent", i["title"], f"ควรแก้ {i['total']} รายการ", "/finance/health", "การเงิน") for i in h["fix"]]
    for i in h["check"]:
        if i["key"] in ("loans_overdue", "memo_unpaid_long", "checks_not_cleared"):
            out.append(_alert("warn", i["title"], f"{i['total']} รายการ", i["href"] or "/finance/health", "การเงิน"))
    _health_cache[(sid, fy)] = (time.time(), out)
    return out


def _hr_alerts(db):
    from app.models import LeaveRequest, TravelRequest
    out = []
    n = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").count()
    if n:
        out.append(_alert("warn", f"ใบลารอฝ่ายบุคคลตรวจ {n} เรื่อง", "ตรวจแล้วส่งต่อ ผอ.", "/hr/leave-requests?status=pending", "บุคคล"))
    n = db.query(TravelRequest).filter(TravelRequest.status == "pending").count()
    if n:
        out.append(_alert("warn", f"คำขอไปราชการรอฝ่ายบุคคลตรวจ {n} เรื่อง", "ตรวจแล้วส่งต่อ ผอ.", "/hr/travel-requests", "บุคคล"))
    return out


def _director_alerts(db):
    from app.models import LeaveRequest, TravelRequest, IncomingLetter
    out = []
    n = (db.query(LeaveRequest).filter(LeaveRequest.status == "personnel").count()
         + db.query(TravelRequest).filter(TravelRequest.status == "personnel").count())
    if n:
        out.append(_alert("warn", f"รอ ผอ. อนุมัติ {n} เรื่อง", "ใบลาและคำขอไปราชการ", "/approvals", "อนุมัติ"))
    n = db.query(IncomingLetter).filter(IncomingLetter.route_status == "director").count()
    if n:
        out.append(_alert("warn", f"หนังสือรอ ผอ. สั่งการ {n} ฉบับ", "สั่งการแล้วระบบเวียนถึงครูให้",
                          "/approvals#letters", "อนุมัติ"))
    return out


def nav_alerts(session=None):
    """กระดิ่ง topbar: งานที่ต้องทำ แยกตามงานที่บัญชีนี้เข้าได้ เรียงด่วนสุดก่อน
    session=None (โค้ดเก่า) = แสดงเฉพาะงานพัสดุ"""
    from app.tenancy import current_school_id, session_for
    sid = current_school_id.get()
    if sid is None:                 # ยังไม่ได้เลือกโรงเรียน (เช่น หน้า login) -> ไม่มีแจ้งเตือน
        return []
    if session is None:
        allowed, director = {"procurement"}, False
    else:
        from app.services.search import allowed_modules
        allowed, director = allowed_modules(session, sid), bool(session.get("director"))
    db = session_for(sid)
    try:
        today = datetime.now().date()
        alerts = []
        for mod, fn in (("procurement", lambda: _procurement_alerts(db, today)),
                        ("finance", lambda: _finance_alerts(db, sid)),
                        ("hr", lambda: _hr_alerts(db))):
            if mod in allowed:
                try:
                    alerts += fn()
                except Exception as e:  # noqa: BLE001  งานหนึ่งพัง กระดิ่งยังต้องขึ้น
                    print("[bell]", mod, repr(e))
        if director:
            try:
                alerts += _director_alerts(db)
            except Exception as e:  # noqa: BLE001
                print("[bell] director", repr(e))
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
        return [{"id": n.id, "title": n.title, "reason": n.reason, "tag": "ถึงคุณ",
                 "level": n.level or "info", "href": f"/notices/{n.id}"} for n in rows]
    finally:
        db.close()
