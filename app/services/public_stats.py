# -*- coding: utf-8 -*-
"""
public_stats.py - ตัวเลขจริงบนหน้า landing ("ใช้งานไปแล้ว ... ครั้ง จากทั้งหมด ... โรงเรียน")

  - คำนวณวันละครั้ง (แคชตามวันที่) ไม่ต้องคิดใหม่ทุกครั้งที่มีคนเปิดหน้า
  - นับเฉพาะโรงเรียนจริง: ไม่รวมระบบตัวอย่าง โรงเรียนสาธิต (slug demo) และโรงเรียนที่ถูกระงับ
  - ครั้งที่ใช้งาน / เอกสาร = ยอดรายวันที่ยังเก็บอยู่ + ยอดสะสมของวันที่ถูกลบไปแล้ว (UsageLifetime)
  - โรงเรียนยังน้อยกว่าเกณฑ์ -> ไม่แสดง (ตัวเลขเล็กทำให้ดูไม่น่าเชื่อถือ) ตั้งได้ที่ landing_stats_min_schools
"""
from datetime import date

_MS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
_cache: dict = {}


def min_schools() -> int:
    from app.seller_config import SELLER
    try:
        return max(0, int(SELLER.get("landing_stats_min_schools") or 10))
    except (TypeError, ValueError):
        return 10


def compute(today: date | None = None) -> dict:
    from sqlalchemy import func
    from app.accounts import acc_session, Tenant, UsageDay, UsageLifetime
    today = today or date.today()
    db = acc_session()
    try:
        ids = [tid for (tid,) in db.query(Tenant.id).filter(
            Tenant.plan != "sandbox", Tenant.slug != "demo", Tenant.active.is_(True))]
        hits = docs = 0
        if ids:
            h, d = db.query(func.sum(UsageDay.hits), func.sum(UsageDay.docs)).filter(
                UsageDay.tenant_id.in_(ids)).one()
            lh, ld = db.query(func.sum(UsageLifetime.hits), func.sum(UsageLifetime.docs)).filter(
                UsageLifetime.tenant_id.in_(ids)).one()
            hits, docs = (h or 0) + (lh or 0), (d or 0) + (ld or 0)
    finally:
        db.close()
    return {"schools": len(ids), "hits": int(hits), "docs": int(docs),
            "as_of": f"{today.day} {_MS[today.month]} {today.year + 543}",
            "show": len(ids) >= min_schools() and hits > 0}


def landing_stats(today: date | None = None) -> dict | None:
    """ตัวเลขของวันนี้ (คิดครั้งแรกของวัน) · None = ยังไม่ถึงเกณฑ์ ไม่ต้องแสดง"""
    today = today or date.today()
    key = today.isoformat()
    if key not in _cache:
        try:
            _cache.clear()
            _cache[key] = compute(today)
        except Exception as e:  # noqa: BLE001  หน้า landing ต้องเปิดได้เสมอ
            print("[public_stats] คำนวณไม่สำเร็จ:", e)
            return None
    s = _cache[key]
    return s if s["show"] else None
