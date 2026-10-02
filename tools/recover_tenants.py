# -*- coding: utf-8 -*-
"""
recover_tenants.py - หาสาเหตุที่แถวโรงเรียนหาย และกู้คืนกลับมา

ใช้คู่กับ tools/check_tenants.py เมื่อพบว่ามีโฟลเดอร์ข้อมูลที่ไม่มีแถวในฐานข้อมูลแล้ว

ขั้นที่ 1 ดูอย่างเดียว (ไม่แก้อะไรเลย) - รันอันนี้ก่อนเสมอ
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.recover_tenants

ขั้นที่ 2 กู้คืน (สร้างแถวโรงเรียนกลับ โดยใช้เลขเดิมให้ตรงกับโฟลเดอร์ข้อมูล)
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.recover_tenants --fix

สิ่งที่สคริปต์นี้บอกได้ (ใช้ชี้สาเหตุ)
  - บัญชีผู้ใช้ของโรงเรียนนั้นยังอยู่ไหม
      ยังอยู่  = มีอะไรลบเฉพาะแถวโรงเรียน (ไม่ใช่ purge_tenant ซึ่งลบบัญชีด้วย)
      หายด้วย = ถูกลบทั้งชุดแบบเดียวกับ purge_tenant แต่ไม่มีร่องรอยใน audit log
  - ชื่อโรงเรียนและข้อมูลที่ยังอยู่ในไฟล์ (นักเรียน/ครุภัณฑ์/รายการเงิน)
  - เวลาที่ไฟล์ถูกแก้ล่าสุด เทียบกับ audit log รอบนั้น
"""
import sqlite3
import sys
from datetime import date, datetime, timedelta


def _peek(dbfile):
    """อ่านข้อมูลสรุปจากไฟล์โรงเรียน โดยไม่แตะไฟล์ (เปิดแบบอ่านอย่างเดียว)"""
    out = {"name": "", "counts": {}}
    try:
        con = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT name FROM school LIMIT 1").fetchone()
            out["name"] = (row[0] if row and row[0] else "") or ""
            for table, label in (("student", "นักเรียน"), ("person", "บุคลากร"),
                                 ("asset", "ครุภัณฑ์"), ("procurement", "เรื่องจัดซื้อ"),
                                 ("finance_txn", "รายการเงิน")):
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    if n:
                        out["counts"][label] = n
                except Exception:
                    pass
        finally:
            con.close()
    except Exception as e:      # noqa: BLE001
        out["error"] = str(e)
    return out


def main(fix: bool = False) -> int:
    from app.accounts import Account, AuditLog, Tenant, acc_session, audit
    from app.database import get_data_dir

    folder = get_data_dir() / "schools"
    db = acc_session()
    try:
        ids = {t.id for t in db.query(Tenant).all()}
        on_disk = sorted(int(p.name) for p in folder.iterdir()
                         if p.is_dir() and p.name.isdigit()) if folder.exists() else []
        orphan = [i for i in on_disk if i not in ids]

        if not orphan:
            print("ไม่มีโฟลเดอร์ข้อมูลที่ขาดแถวโรงเรียน (ไม่มีอะไรต้องกู้)")
            return 0

        print("=" * 72)
        print(f"  พบข้อมูลค้าง {len(orphan)} โรงเรียน")
        print("=" * 72)
        plan = []
        for tid in orphan:
            dbfile = folder / str(tid) / "school.db"
            info = _peek(dbfile)
            accs = db.query(Account).filter_by(tenant_id=tid).all()
            mtime = (datetime.fromtimestamp(dbfile.stat().st_mtime) if dbfile.exists() else None)
            print(f"\n  โรงเรียน #{tid}")
            print(f"    ชื่อในไฟล์ข้อมูล : {info.get('name') or '(อ่านไม่ได้)'}")
            if info.get("counts"):
                print("    ข้อมูลที่ยังอยู่  : "
                      + " · ".join(f"{k} {v:,}" for k, v in info["counts"].items()))
            print(f"    แก้ไขล่าสุด      : "
                  + (mtime.strftime('%d/%m/%Y %H:%M') if mtime else '-'))
            if accs:
                print(f"    บัญชีผู้ใช้       : ยังอยู่ {len(accs)} บัญชี  <-- ลบเฉพาะแถวโรงเรียน")
                for a in accs:
                    print(f"        {a.username}  ({'ไอดีหลัก' if a.is_owner else 'ไอดีย่อย'})")
            else:
                print("    บัญชีผู้ใช้       : หายไปด้วย  <-- ถูกลบทั้งชุด")
            plan.append({"id": tid, "name": info.get("name") or f"โรงเรียน #{tid}",
                         "accounts": len(accs), "mtime": mtime})

        # ---------- audit log รอบเวลาที่เกิดเหตุ ----------
        times = [p["mtime"] for p in plan if p["mtime"]]
        if times:
            lo = min(times) - timedelta(hours=6)
            hi = max(times) + timedelta(hours=6)
            print("\n" + "=" * 72)
            print(f"  audit log ช่วง {lo:%d/%m/%Y %H:%M} ถึง {hi:%d/%m/%Y %H:%M}")
            print("=" * 72)
            rows = (db.query(AuditLog).filter(AuditLog.at >= lo, AuditLog.at <= hi)
                    .order_by(AuditLog.at).limit(60).all())
            if not rows:
                print("  ไม่มีรายการใด ๆ เลยในช่วงนั้น")
                print("  -> ไม่มีใครกดลบผ่านคอนโซล และงานลบอัตโนมัติก็ไม่ได้ทำงาน")
            for r in rows:
                print(f"  {r.at:%d/%m %H:%M}  {r.action:<24} {(r.username or '-')[:26]:<28} "
                      f"{(r.target or '')[:28]}")

        # ---------- กู้คืน ----------
        print("\n" + "=" * 72)
        if not fix:
            print("  โหมดดูอย่างเดียว ยังไม่แก้อะไร")
            print("  ถ้าจะกู้คืน ให้รันซ้ำแล้วเติม --fix")
            print("  สิ่งที่จะทำ: สร้างแถวโรงเรียนกลับโดยใช้เลขเดิม "
                  "(ข้อมูลในไฟล์ไม่ถูกแตะต้อง)")
            print("=" * 72)
            return 0

        print("  กำลังกู้คืน")
        print("=" * 72)
        for p in plan:
            slug = f"recover-{p['id']}"
            t = Tenant(id=p["id"], name=p["name"], slug=slug, active=True,
                       plan="trial", max_users=3,
                       created_at=p["mtime"] or datetime.now(),
                       expiry_date=date.today() + timedelta(days=30),
                       trial_expiry_date=date.today() + timedelta(days=30))
            db.add(t)
            db.flush()
            print(f"  คืนแถวโรงเรียน #{p['id']} {p['name']}"
                  + (f" (บัญชีเดิม {p['accounts']} บัญชียังอยู่ ใช้งานต่อได้ทันที)"
                     if p["accounts"] else "  ** ไม่มีบัญชีผู้ใช้ ต้องสร้างไอดีให้ใหม่ในคอนโซล **"))
        db.commit()
        for p in plan:
            audit("admin.tenant_recover", tenant_id=None,
                  target=f"#{p['id']} {p['name']}",
                  detail="กู้คืนแถวโรงเรียนจากโฟลเดอร์ข้อมูลที่ยังอยู่")
        print("\n  เสร็จแล้ว เปิดคอนโซลตรวจอีกครั้งได้เลย")
        print("  โรงเรียนที่ไม่มีบัญชีผู้ใช้ ให้เพิ่มไอดีหลักให้ในคอนโซล แล้วแจ้งโรงเรียนตั้งรหัสใหม่")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(fix="--fix" in sys.argv))
