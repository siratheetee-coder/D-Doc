# -*- coding: utf-8 -*-
"""
recover_accounts.py - กู้ไอดีผู้ใช้ของโรงเรียนที่แถวบัญชีถูกลบไป

ใช้ต่อจาก tools/recover_tenants.py --fix (ที่คืนตัวโรงเรียนกลับมาแล้ว แต่ยังไม่มีไอดี)

รหัสผ่านเดิมกู้ไม่ได้ เพราะเก็บเป็นค่าแฮช ไม่ได้เก็บตัวรหัส (ถูกต้องตามหลักความปลอดภัย)
แต่ "ไอดีล็อกอิน" ยังหาเจอได้ เพราะระบบบันทึกไว้หลายที่ที่ไม่ได้ถูกลบไปด้วย
    1) audit_log  - ทุกครั้งที่ล็อกอินสำเร็จ บันทึกชื่อผู้ใช้ + เลขโรงเรียนไว้
    2) usage_day  - สรุปการใช้งานรายวัน เก็บชื่อผู้ใช้ + ชื่อที่แสดงไว้
    3) lead       - ใบสมัคร/ใบสั่งซื้อ เก็บอีเมลผู้ติดต่อไว้

ขั้นที่ 1 ดูอย่างเดียว
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.recover_accounts

ขั้นที่ 2 สร้างไอดีกลับ พร้อมรหัสผ่านชั่วคราว (ระบบบังคับให้เปลี่ยนตอนล็อกอินครั้งแรก)
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.recover_accounts --fix

เอารหัสชั่วคราวที่พิมพ์ออกมาแจ้งโรงเรียน หรือให้เขากด "ลืมรหัสผ่าน" เองก็ได้
"""
import secrets
import string
import sys
from collections import Counter


def _candidates(db, tenant_id: int, school_name: str) -> list:
    """หาไอดีล็อกอินเดิมของโรงเรียนนี้ จากร่องรอยที่ยังเหลืออยู่"""
    from app.accounts import AuditLog, Lead, UsageDay
    found = {}        # username -> {"display": ..., "seen": [ที่มา], "last": เวลาที่เจอล่าสุด}

    def add(username, display, source, when=None):
        u = (username or "").strip()
        if not u or "@" not in u and len(u) < 3:
            return
        row = found.setdefault(u, {"display": "", "seen": [], "last": None})
        if display and not row["display"]:
            row["display"] = display
        if source not in row["seen"]:
            row["seen"].append(source)
        if when and (row["last"] is None or when > row["last"]):
            row["last"] = when

    for r in (db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
              .order_by(AuditLog.at.desc()).limit(400).all()):
        add(r.username, "", "เคยล็อกอิน", r.at)
    for r in db.query(UsageDay).filter(UsageDay.tenant_id == tenant_id).all():
        add(r.username, r.display_name, "มีสถิติการใช้งาน")
    if school_name:
        for r in db.query(Lead).all():
            same_tenant = (getattr(r, "tenant_id", None) == tenant_id)
            same_name = school_name and r.school_name and school_name.strip() in r.school_name
            if same_tenant or same_name:
                add(r.email, r.contact_name or "", "อยู่ในใบสมัคร")
                add(getattr(r, "login_user", ""), r.contact_name or "", "อยู่ในใบสมัคร")

    out = []
    for username, row in found.items():
        out.append({"username": username, "display": row["display"],
                    "seen": row["seen"], "last": row["last"]})
    # ไอดีที่เคยล็อกอินล่าสุด = น่าจะเป็นไอดีหลักที่สุด
    out.sort(key=lambda x: (x["last"] is None, -(x["last"].timestamp() if x["last"] else 0)))
    return out


def _temp_password() -> str:
    """รหัสชั่วคราวที่พิมพ์ต่อทางโทรศัพท์ได้ไม่สับสน (ตัด 0 O l 1 ออก)"""
    pool = "".join(c for c in string.ascii_letters + string.digits if c not in "0Ol1I")
    return "Ekk-" + "".join(secrets.choice(pool) for _ in range(8))


def main(fix: bool = False) -> int:
    from app.accounts import Account, Tenant, acc_session, audit, hash_password

    db = acc_session()
    try:
        empty = [t for t in db.query(Tenant).order_by(Tenant.id).all()
                 if db.query(Account).filter_by(tenant_id=t.id).count() == 0]
        if not empty:
            print("ทุกโรงเรียนมีไอดีผู้ใช้ครบแล้ว ไม่มีอะไรต้องกู้")
            return 0

        print("=" * 72)
        print(f"  โรงเรียนที่ยังไม่มีไอดีผู้ใช้ {len(empty)} แห่ง")
        print("=" * 72)
        plan = []
        for t in empty:
            cands = _candidates(db, t.id, t.name or "")
            print(f"\n  #{t.id}  {t.name}")
            if not cands:
                print("    หาไอดีเดิมไม่เจอเลย -> ต้องถามโรงเรียนว่าใช้อีเมลอะไรสมัคร")
                continue
            for i, c in enumerate(cands):
                mark = "  <-- จะกู้ไอดีนี้เป็นไอดีหลัก" if i == 0 else ""
                when = c["last"].strftime("%d/%m/%Y %H:%M") if c["last"] else "-"
                print(f"    {c['username']:<34} {' · '.join(c['seen'])}"
                      f"  ล่าสุด {when}{mark}")
            plan.append((t, cands[0]))

        print("\n" + "=" * 72)
        if not fix:
            print("  โหมดดูอย่างเดียว ยังไม่สร้างอะไร")
            print("  ถ้าถูกต้องแล้วให้รันซ้ำแล้วเติม --fix")
            print("=" * 72)
            return 0

        print("  กำลังสร้างไอดีกลับ")
        print("=" * 72)
        made = []
        for t, c in plan:
            if db.query(Account).filter_by(username=c["username"]).first():
                print(f"  ข้าม #{t.id}: ไอดี {c['username']} ถูกใช้โดยบัญชีอื่นแล้ว")
                continue
            pw = _temp_password()
            db.add(Account(tenant_id=t.id, username=c["username"],
                           password_hash=hash_password(pw),
                           display_name=c["display"] or (t.name or ""),
                           role="user", is_owner=True, active=True, verified=True,
                           must_change_password=True))
            made.append((t, c["username"], pw))
        db.commit()
        for t, username, _pw in made:
            audit("admin.account_recover", tenant_id=t.id, target=username,
                  detail="สร้างไอดีหลักกลับหลังข้อมูลบัญชีหาย")

        print()
        for t, username, pw in made:
            print(f"  #{t.id}  {t.name}")
            print(f"      ไอดี        {username}")
            print(f"      รหัสชั่วคราว {pw}")
            print("      (ระบบบังคับเปลี่ยนรหัสตอนล็อกอินครั้งแรก)")
        print("\n  แจ้งรหัสนี้ให้โรงเรียน หรือบอกให้กด 'ลืมรหัสผ่าน' ที่หน้าเข้าสู่ระบบก็ได้")
        print("  รหัสชุดนี้แสดงครั้งเดียว ไม่มีเก็บไว้ที่ไหน")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(fix="--fix" in sys.argv))
