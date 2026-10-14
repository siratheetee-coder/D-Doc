# -*- coding: utf-8 -*-
"""
signup_cleanup.py - ดู/ลบการสมัครที่ไม่เคยยืนยันอีเมล (สั่งเองเท่านั้น ไม่ลบอัตโนมัติ)

!! ไม่มีการลบอัตโนมัติ: ตรวจของจริงบนเซิร์ฟเวอร์ (2026-10-14) พบว่าส่วนใหญ่เป็นครูจริงที่ยังไม่ได้กดยืนยัน
   (อีเมลยืนยันอาจไปอยู่ในสแปม) การลบเองจะเสียรายชื่อลูกค้า · ลบได้เฉพาะเมื่อสั่งพร้อม --confirm

ตอนสมัคร ระบบสร้างโรงเรียน + คำขอ "ทดลองใช้ฟรี" ไว้ก่อนยืนยันอีเมล
ระหว่างยังไม่ยืนยัน: ไม่นับในตัวเลขหน้า landing (public_stats) แต่ยังอยู่ในระบบ

ลบเฉพาะที่ปลอดภัยแน่นอน:
  - plan = trial เท่านั้น (สมาชิกที่จ่ายเงินไม่แตะ)
  - ไอดีหลักทุกบัญชีของโรงเรียนนั้นยังไม่ยืนยันอีเมล และไม่มีบัญชีอื่นที่ยืนยันแล้ว
  - สมัครมานานเกิน UNVERIFIED_DAYS วัน

ดูรายชื่อ (ไม่ลบ):
    /opt/ddoc/.venv/bin/python -m app.services.signup_cleanup
ลบจริง (ทุกรายการในรายชื่อ):
    /opt/ddoc/.venv/bin/python -m app.services.signup_cleanup --confirm
"""
import sys
from datetime import datetime, timedelta

UNVERIFIED_DAYS = 3


def candidates(now: datetime | None = None) -> list:
    """[(tenant_id, ชื่อโรงเรียน, [อีเมล])] ที่เข้าเกณฑ์ลบ"""
    from app.accounts import acc_session, Account, Tenant
    cut = (now or datetime.now()) - timedelta(days=UNVERIFIED_DAYS)
    db = acc_session()
    try:
        out = []
        for t in db.query(Tenant).filter(Tenant.plan == "trial", Tenant.created_at < cut):
            accs = db.query(Account).filter_by(tenant_id=t.id).all()
            if accs and not any(a.verified for a in accs):
                out.append((t.id, t.name, [a.username for a in accs]))
        return out
    finally:
        db.close()


def spam_status(days: int = 7) -> dict:
    """คอนโซล: บอทที่ถูกกันใน N วัน + การสมัครที่ยังไม่ยืนยันอีเมล (รอลบอัตโนมัติ)"""
    from app.accounts import acc_session, Account, AuditLog, Tenant
    db = acc_session()
    try:
        since = datetime.now() - timedelta(days=days)
        bots = db.query(AuditLog).filter(AuditLog.action == "bot.blocked", AuditLog.at >= since).count()
        pending = 0
        for t in db.query(Tenant).filter(Tenant.plan == "trial"):
            accs = db.query(Account).filter_by(tenant_id=t.id).all()
            if accs and not any(a.verified for a in accs):
                pending += 1
        return {"bots": bots, "pending": pending, "days": days, "keep": UNVERIFIED_DAYS}
    finally:
        db.close()


def purge_unverified(now: datetime | None = None, dry_run: bool = False, verbose: bool = False) -> int:
    from app.accounts import acc_session, Lead, audit, purge_tenant
    rows = candidates(now)
    if verbose:
        print(f"[signup_cleanup] สมัครแต่ไม่ยืนยันอีเมลเกิน {UNVERIFIED_DAYS} วัน: {len(rows)} รายการ"
              + (" (ดูอย่างเดียว ไม่ลบ)" if dry_run else ""))
        for tid, name, users in rows[:50]:
            print(f"  - #{tid} {name} · {', '.join(users)}")
    if dry_run:
        return len(rows)
    for tid, name, users in rows:
        purge_tenant(tid)
        db = acc_session()
        try:
            db.query(Lead).filter(Lead.kind == "trial", Lead.tenant_id == tid).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
    if rows:
        audit("signup.unverified_purged", tenant_id=None, uid=None, target=f"{len(rows)} รายการ",
              detail=", ".join(n for _, n, _ in rows)[:400])
    return len(rows)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    purge_unverified(dry_run="--confirm" not in sys.argv, verbose=True)     # ไม่ใส่ --confirm = ดูอย่างเดียว
