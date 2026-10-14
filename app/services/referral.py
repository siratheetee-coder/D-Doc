# -*- coding: utf-8 -*-
"""
referral.py - แนะนำเพื่อน

  - ทุกโรงเรียนมีลิงก์ /r/<รหัส> และรหัสแนะนำ (พิมพ์ในหน้าสมัครก็ได้)
  - เพื่อนสมัครผ่านลิงก์/รหัส -> บันทึกว่าใครแนะนำ (Referral)
  - เพื่อนจ่ายเงินครั้งแรก -> ได้ใช้ฟรีเพิ่มทั้งคู่ คนละ BONUS_DAYS วัน (ต่อท้ายวันหมดอายุ)
    ผู้แนะนำที่ยังทดลองใช้/หมดอายุอยู่ -> เก็บสิทธิ์ไว้ ได้ตอนตัวเองจ่ายเงิน
  - ให้รางวัลตอน "จ่ายเงิน" เท่านั้น สมัครเฉย ๆ ไม่ได้ (กันสมัครบัญชีปลอมมาปั่น)
"""
import re
import secrets
from datetime import date, datetime, timedelta

COOKIE = "ee_invite"
COOKIE_AGE = 60 * 24 * 3600
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # ไม่มี 0/O 1/I ที่อ่านสับสนเวลาบอกกันปากเปล่า


def bonus_days() -> int:
    from app.seller_config import SELLER
    try:
        return max(0, int(SELLER.get("referral_bonus_days") or 30))
    except (TypeError, ValueError):
        return 30


def clean_code(v) -> str:
    return re.sub(r"[^A-Z0-9]", "", (v or "").upper())[:12]


def code_for(tenant_id) -> str:
    """รหัสแนะนำของโรงเรียน (สร้างครั้งแรกที่ขอ แล้วใช้ตลอด)"""
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return ""
        if not t.ref_code:
            while True:
                c = "".join(secrets.choice(_ALPHABET) for _ in range(6))
                if not db.query(Tenant).filter_by(ref_code=c).first():
                    break
            t.ref_code = c
            db.commit()
        return t.ref_code
    finally:
        db.close()


def referrer_by_code(code):
    """{id, name} ของโรงเรียนเจ้าของรหัส หรือ None (ระบบตัวอย่างแนะนำใครไม่ได้)"""
    from app.accounts import acc_session, Tenant
    code = clean_code(code)
    if not code:
        return None
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(ref_code=code).first()
        if not t or (t.plan or "") == "sandbox" or not t.active:
            return None
        return {"id": t.id, "name": t.name}
    finally:
        db.close()


def link(new_tenant_id, code) -> bool:
    """ผูกโรงเรียนที่เพิ่งสมัครกับผู้แนะนำ (ครั้งเดียว ห้ามแนะนำตัวเอง)"""
    from app.accounts import acc_session, Tenant, Referral
    ref = referrer_by_code(code)
    if not ref or not new_tenant_id or ref["id"] == new_tenant_id:
        return False
    db = acc_session()
    try:
        t = db.get(Tenant, new_tenant_id)
        if not t or t.referred_by or db.query(Referral).filter_by(referred_id=new_tenant_id).first():
            return False
        t.referred_by = ref["id"]
        db.add(Referral(referrer_id=ref["id"], referred_id=new_tenant_id))
        db.commit()
        return True
    finally:
        db.close()


def _extend(t, days, today):
    """ต่อท้ายวันหมดอายุ (หมดไปแล้ว = นับจากวันนี้) · ไม่มีวันหมดอายุ = ใช้ได้ไม่จำกัดอยู่แล้ว"""
    if t.expiry_date is None:
        return
    base = t.expiry_date if t.expiry_date >= today else today
    t.expiry_date = base + timedelta(days=days)


def _is_paying(t, today) -> bool:
    return (t.plan or "") == "member" and (t.expiry_date is None or t.expiry_date >= today)


def on_paid(tenant_id, today: date | None = None) -> dict:
    """เรียกหลังโรงเรียนนี้จ่ายเงิน/เป็นสมาชิก
    1) ถ้าโรงเรียนนี้ถูกแนะนำมาและเพิ่งจ่ายครั้งแรก -> ให้วันฟรีทั้งคู่ (ผู้แนะนำยังไม่จ่าย = เก็บไว้ก่อน)
    2) ถ้าโรงเรียนนี้เคยแนะนำคนอื่นแล้วมีสิทธิ์ค้าง -> ให้ตอนนี้"""
    from app.accounts import acc_session, Tenant, Referral
    today = today or date.today()
    now = datetime.now()
    out = {"referred": 0, "referrer": 0, "pending": 0}
    if not tenant_id:
        return out
    db = acc_session()
    try:
        me = db.get(Tenant, tenant_id)
        if not me or not _is_paying(me, today):
            return out
        r = db.query(Referral).filter_by(referred_id=tenant_id).first()
        if r and not r.paid_at:
            r.paid_at = now
            r.bonus_days = bonus_days()
            _extend(me, r.bonus_days, today)
            r.referred_bonus_at = now
            out["referred"] = r.bonus_days
            boss = db.get(Tenant, r.referrer_id)
            if boss and _is_paying(boss, today):
                _extend(boss, r.bonus_days, today)
                r.referrer_bonus_at = now
                out["referrer"] = r.bonus_days
            else:
                out["pending"] = r.bonus_days
        for p in (db.query(Referral).filter(Referral.referrer_id == tenant_id, Referral.paid_at.isnot(None),
                                            Referral.referrer_bonus_at.is_(None))):
            _extend(me, p.bonus_days, today)
            p.referrer_bonus_at = now
            out["referrer"] += p.bonus_days
        db.commit()
        return out
    finally:
        db.close()


def status(tenant_id) -> dict:
    """ข้อมูลหน้า "แนะนำเพื่อน" ของโรงเรียนนี้"""
    from app.accounts import acc_session, Tenant, Referral
    db = acc_session()
    try:
        rows = db.query(Referral).filter_by(referrer_id=tenant_id).order_by(Referral.id.desc()).all()
        names = {t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_([r.referred_id for r in rows]))} \
            if rows else {}
        friends = []
        for r in rows:
            if r.referrer_bonus_at:
                st, cls = f"ได้รับ {r.bonus_days} วันแล้ว", "ok"
            elif r.paid_at:
                st, cls = f"รอรับ {r.bonus_days} วัน เมื่อท่านสมัครสมาชิก", "wait"
            else:
                st, cls = "ทดลองใช้อยู่", "trial"
            friends.append({"name": names.get(r.referred_id, "(โรงเรียนลบบัญชีแล้ว)"), "since": r.created_at,
                            "status": st, "cls": cls})
        return {"friends": friends, "signed": len(rows), "paid": sum(1 for r in rows if r.paid_at),
                "earned": sum(r.bonus_days for r in rows if r.referrer_bonus_at),
                "pending": sum(r.bonus_days for r in rows if r.paid_at and not r.referrer_bonus_at)}
    finally:
        db.close()


def all_rows() -> list:
    """ทุกคู่ที่แนะนำกัน (คอนโซล > ลูกค้ามาจากไหน)"""
    from app.accounts import acc_session, Tenant, Referral
    db = acc_session()
    try:
        rows = db.query(Referral).order_by(Referral.id.desc()).all()
        ids = {r.referrer_id for r in rows} | {r.referred_id for r in rows}
        names = {t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_(ids))} if rows else {}
        return [{"referrer": names.get(r.referrer_id, "-"), "referred": names.get(r.referred_id, "-"),
                 "since": r.created_at, "paid_at": r.paid_at, "days": r.bonus_days,
                 "referrer_done": bool(r.referrer_bonus_at)} for r in rows]
    finally:
        db.close()
