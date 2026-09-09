# -*- coding: utf-8 -*-
"""
retention.py - ลบข้อมูลโรงเรียนที่ไม่มีการใช้งานนาน (พร้อมแจ้งเตือนล่วงหน้า 3 ครั้ง)

เหตุผล: PDPA กำหนดว่าไม่ควรเก็บข้อมูลส่วนบุคคลนานเกินความจำเป็น
และการเก็บข้อมูลนักเรียนของโรงเรียนที่เลิกใช้ไปแล้วคือความเสี่ยงเปล่า ๆ

กำหนดการ (นับจากล็อกอินครั้งล่าสุดของคนใดคนหนึ่งในโรงเรียน):
    12 เดือน  -> เตือนครั้งที่ 1
    13 เดือน  -> เตือนครั้งที่ 2 (บอกวิธีดาวน์โหลดข้อมูล)
    14 เดือน  -> เตือนครั้งสุดท้าย "อีก 30 วันจะลบ"
    15 เดือน  -> ลบถาวร

รันจาก cron วันละครั้ง:
    /opt/ddoc/.venv/bin/python -m app.services.retention
ดูก่อนว่าจะเกิดอะไรขึ้นโดยไม่แตะข้อมูลจริง:
    /opt/ddoc/.venv/bin/python -m app.services.retention --dry-run

กติกาความปลอดภัย (สำคัญกว่ากำหนดการ - ป้องกันลบข้อมูลลูกค้าโดยไม่ตั้งใจ):
  1) โรงเรียนที่ยังจ่ายเงินอยู่ (สมาชิกที่ยังไม่หมดอายุ) ไม่ลบเด็ดขาด ไม่ว่าเงียบไปนานแค่ไหน
  2) ลบได้เฉพาะโรงเรียนที่ "เตือนครบ 3 ครั้งแล้ว" จริง ๆ ตามที่บันทึกไว้ใน DB
     -> ต่อให้วันที่ในข้อมูลเพี้ยน ระบบก็ลบอะไรไม่ได้ในวันแรกที่เปิดใช้ฟีเจอร์นี้
  3) เตือนแต่ละครั้งต้องห่างกันอย่างน้อย 25 วัน -> รันซ้ำหลายรอบก็ไม่เร่งกำหนดลบ
  4) ทุกการเตือนและการลบบันทึกลง audit log
"""
import sys
from datetime import datetime, timedelta

DAY = 24 * 3600
STAGE_DAYS = [365, 395, 425]      # เตือนครั้งที่ 1/2/3 (12 / 13 / 14 เดือน)
DELETE_DAYS = 455                 # ลบเมื่อครบ 15 เดือน
MIN_GAP_DAYS = 25                 # เตือนสองครั้งต้องห่างกันอย่างน้อยเท่านี้
MAX_DELETE_PER_RUN = 20           # กันพลาดครั้งใหญ่: รอบหนึ่งลบได้ไม่เกินนี้


def _days(dt) -> int:
    if not dt:
        return 0
    return max(0, (datetime.now() - dt).days)


def _protected(t) -> str:
    """คืนเหตุผลถ้าโรงเรียนนี้ห้ามลบ · คืน "" ถ้าลบได้"""
    from datetime import date
    if not t.active:
        return ""                     # ถูกระงับไว้ = ลบได้ตามกำหนด
    paid = (t.plan == "member")
    not_expired = (t.expiry_date is None) or (t.expiry_date >= date.today())
    if paid and not_expired:
        return "เป็นสมาชิกที่ยังไม่หมดอายุ"
    return ""


def _owner_emails(tenant_id) -> list:
    """อีเมลที่จะส่งเตือน = ไอดีหลักของโรงเรียน (ชื่อผู้ใช้เป็นอีเมลตอนสมัคร)"""
    from app.accounts import acc_session, Account
    db = acc_session()
    try:
        rows = (db.query(Account)
                .filter_by(tenant_id=tenant_id, active=True, is_owner=True).all())
        return [a.username for a in rows if "@" in (a.username or "")]
    finally:
        db.close()


def _warn_html(school: str, stage: int, left_days: int, base_url: str) -> tuple:
    head = {1: "บัญชีของท่านไม่มีการใช้งานมา 12 เดือน",
            2: "บัญชีของท่านไม่มีการใช้งานมา 13 เดือน",
            3: f"แจ้งเตือนครั้งสุดท้าย: ข้อมูลจะถูกลบในอีก {left_days} วัน"}[stage]
    extra = ""
    if stage >= 2:
        extra = (f'<p><b>ต้องการเก็บข้อมูลไว้?</b> เข้าสู่ระบบแล้วไปที่ '
                 f'<b>ตั้งค่าโรงเรียน → สำรอง/กู้คืนข้อมูล → ดาวน์โหลดไฟล์สำรอง</b> '
                 f'เพื่อเก็บข้อมูลทั้งหมดไว้ในเครื่องของท่าน</p>')
    html = f"""
    <p>เรียน ผู้ดูแลระบบของ <b>{school}</b></p>
    <p>{head}</p>
    <p>ตามนโยบายคุ้มครองข้อมูลส่วนบุคคล ระบบจะ<b>ลบข้อมูลของโรงเรียนที่ไม่มีการใช้งาน
    ติดต่อกันเกิน 15 เดือน</b>ออกอย่างถาวร เพื่อไม่เก็บข้อมูลนักเรียนและบุคลากรไว้นานเกินจำเป็น</p>
    <p><b>เพียงเข้าสู่ระบบ 1 ครั้ง</b> การนับจะเริ่มใหม่ทันที และท่านจะไม่ได้รับอีเมลนี้อีก</p>
    {extra}
    <p><a href="{base_url}/login">เข้าสู่ระบบที่นี่</a></p>
    <p style="color:#64748b;font-size:13px">อีเมลนี้ส่งอัตโนมัติจากระบบ Easy Ekkasan</p>
    """
    subject = f"[Easy Ekkasan] {head} — {school}"
    return subject, html


def _base_url() -> str:
    try:
        from app.seller_config import SELLER
        return (SELLER.get("base_url") or "").rstrip("/") or "https://easy-ekkasan.com"
    except Exception:
        return "https://easy-ekkasan.com"


def run(dry_run: bool = False, verbose: bool = True) -> dict:
    """ตรวจทุกโรงเรียน -> ส่งเตือน / ลบตามกำหนด · คืนสรุปผล"""
    from app.accounts import acc_session, Tenant, audit, purge_tenant

    def say(*a):
        if verbose:
            print(*a)

    db = acc_session()
    try:
        tenants = db.query(Tenant).all()
        rows = [{"id": t.id, "name": t.name, "days": _days(t.last_active_at),
                 "stage": t.inactive_stage or 0,
                 "last_notice": t.inactive_notified_at,
                 "protected": _protected(t)} for t in tenants]
    finally:
        db.close()

    warned, deleted, skipped = [], [], []
    base = _base_url()
    say(f"[retention] ตรวจ {len(rows)} โรงเรียน"
        + (" (โหมดดูอย่างเดียว ไม่แตะข้อมูล)" if dry_run else ""))

    for r in rows:
        why = r["protected"]
        if why:
            if r["days"] >= STAGE_DAYS[0]:
                skipped.append((r["name"], why))
            continue

        # ---------- ถึงกำหนดลบไหม ----------
        if r["days"] >= DELETE_DAYS:
            # กติกาข้อ 2: ต้องเตือนครบ 3 ครั้งก่อน ไม่งั้นแค่เตือนต่อ ไม่ลบ
            if r["stage"] < len(STAGE_DAYS):
                say(f"  - {r['name']}: ครบกำหนดลบแล้วแต่ยังเตือนไม่ครบ "
                    f"({r['stage']}/3) -> เตือนก่อน ยังไม่ลบ")
            else:
                if len(deleted) >= MAX_DELETE_PER_RUN:
                    say(f"  ! ถึงเพดาน {MAX_DELETE_PER_RUN} โรงเรียนต่อรอบ - ที่เหลือรอรอบหน้า")
                    break
                say(f"  X ลบ {r['name']} (ไม่ใช้งาน {r['days']} วัน)")
                if not dry_run:
                    audit("retention.delete", tenant_id=None,
                          target=f"#{r['id']} {r['name']}",
                          detail=f"ไม่มีการใช้งาน {r['days']} วัน · เตือนครบ 3 ครั้งแล้ว")
                    purge_tenant(r["id"])
                deleted.append(r["name"])
                continue

        # ---------- ถึงกำหนดเตือนไหม ----------
        want = 0
        for i, d in enumerate(STAGE_DAYS, 1):
            if r["days"] >= d:
                want = i
        if want == 0 or want <= r["stage"]:
            continue
        # กติกาข้อ 3: เตือนถี่เกินไปไม่ได้
        if r["last_notice"] and (datetime.now() - r["last_notice"]).days < MIN_GAP_DAYS:
            continue

        stage = r["stage"] + 1                    # เตือนทีละขั้น ไม่ข้ามขั้น
        left = max(0, DELETE_DAYS - r["days"])
        mails = _owner_emails(r["id"])
        say(f"  ! เตือนครั้งที่ {stage}: {r['name']} (ไม่ใช้งาน {r['days']} วัน, "
            f"เหลือ {left} วัน) -> {', '.join(mails) or 'ไม่พบอีเมล'}")
        if not dry_run:
            subject, html = _warn_html(r["name"], stage, left, base)
            for to in mails:
                try:
                    from app.services.mailer import send_email
                    send_email(to, subject, html)
                except Exception as e:
                    say(f"    ส่งอีเมลไม่สำเร็จ ({to}): {e}")
            db = acc_session()
            try:
                t = db.get(Tenant, r["id"])
                if t:
                    t.inactive_stage = stage
                    t.inactive_notified_at = datetime.now()
                    db.commit()
            finally:
                db.close()
            audit("retention.warn", tenant_id=r["id"], target=r["name"],
                  detail=f"เตือนครั้งที่ {stage} · ไม่ใช้งาน {r['days']} วัน · เหลือ {left} วัน")
        warned.append((r["name"], stage))

    say(f"[retention] เตือน {len(warned)} · ลบ {len(deleted)} · "
        f"ข้าม (ยังเป็นสมาชิก) {len(skipped)}")
    return {"warned": warned, "deleted": deleted, "skipped": skipped, "dry_run": dry_run}


def tenant_status(t) -> dict | None:
    """สถานะไม่ใช้งานของโรงเรียน (ใช้โชว์ในคอนโซลผู้ดูแลระบบ)
    -> {days, left, stage} หรือ None ถ้ายังไม่เข้าข่าย

    หมายเหตุ: ไม่ทำเป็นแบนเนอร์ในระบบให้โรงเรียนเห็น เพราะพอล็อกอินเข้ามา
    สถานะจะถูกรีเซ็ตทันที (ถือว่ากลับมาใช้งานแล้ว) แบนเนอร์จึงไม่มีวันแสดง
    การเตือนจึงต้องเป็นทางอีเมลเท่านั้น
    """
    if not t or _protected(t):
        return None
    d = _days(getattr(t, "last_active_at", None))
    if d < STAGE_DAYS[0] - 60:              # เริ่มโชว์ล่วงหน้า 2 เดือนก่อนเตือนครั้งแรก
        return None
    return {"days": d, "left": max(0, DELETE_DAYS - d),
            "stage": getattr(t, "inactive_stage", 0) or 0}


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    run(dry_run=dry)
