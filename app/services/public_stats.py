# -*- coding: utf-8 -*-
"""
public_stats.py - ตัวเลขจริงบนหน้า landing ("ใช้งานไปแล้ว ... ครั้ง จากทั้งหมด ... โรงเรียน")

  - คำนวณวันละครั้ง (แคชตามวันที่) ไม่ต้องคิดใหม่ทุกครั้งที่มีคนเปิดหน้า
  - จำนวนโรงเรียน = ทุกโรงเรียนที่เคยสมัคร (เจ้าของกำหนด) รวมที่ถูกลบ/ระงับไปแล้ว
    นับจากบันทึกการสมัคร (Lead kind=trial ไม่ถูกลบตอนลบโรงเรียน) + โรงเรียนที่ยังอยู่ ไม่นับอีเมลซ้ำ
    ไม่รวมระบบตัวอย่างและโรงเรียนสาธิต (slug demo)
  - ครั้งที่ใช้งาน / เอกสาร = ยอดรายวันที่ยังเก็บอยู่ + ยอดสะสมของวันที่ถูกลบไปแล้ว (UsageLifetime)
    รวมโรงเรียนที่ถูกลบไปแล้วด้วย · ไม่รวมโรงเรียนสาธิตและระบบตัวอย่าง
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


def ever_registered(db) -> int:
    """จำนวนโรงเรียนที่เคยสมัครทั้งหมด (ไม่นับอีเมล/ไอดีซ้ำ)"""
    from app.accounts import Account, Lead, Tenant
    keys = {(e or "").strip().lower() for (e,) in db.query(Lead.email).filter(Lead.kind == "trial")}
    keys |= {(u or "").strip().lower() for (u,) in db.query(Account.username)
             .join(Tenant, Account.tenant_id == Tenant.id)
             .filter(Account.is_owner.is_(True), Tenant.plan != "sandbox", Tenant.slug != "demo")}
    demo = {(u or "").strip().lower() for (u,) in db.query(Account.username)
            .join(Tenant, Account.tenant_id == Tenant.id).filter(Tenant.slug == "demo")}
    return len(keys - demo - {""})


def compute(today: date | None = None) -> dict:
    from sqlalchemy import func
    from app.accounts import acc_session, Tenant, UsageDay, UsageLifetime
    today = today or date.today()
    db = acc_session()
    try:
        skip = [tid for (tid,) in db.query(Tenant.id).filter(
            (Tenant.slug == "demo") | (Tenant.plan == "sandbox"))]
        h, d = db.query(func.sum(UsageDay.hits), func.sum(UsageDay.docs)).filter(
            UsageDay.tenant_id.notin_(skip)).one()
        lh, ld = db.query(func.sum(UsageLifetime.hits), func.sum(UsageLifetime.docs)).filter(
            UsageLifetime.tenant_id.notin_(skip)).one()
        hits, docs = (h or 0) + (lh or 0), (d or 0) + (ld or 0)
        schools = ever_registered(db)
    finally:
        db.close()
    return {"schools": schools, "hits": int(hits), "docs": int(docs),
            "as_of": f"{today.day} {_MS[today.month]} {today.year + 543}",
            "show": schools >= min_schools() and hits > 0}


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
