# -*- coding: utf-8 -*-
"""
check_tenants.py - ตรวจว่าโรงเรียนหายไปจริงไหม (อ่านอย่างเดียว ไม่แก้ข้อมูลใด ๆ)

ใช้เมื่อจำนวนโรงเรียนในคอนโซลลดลงโดยไม่ทราบสาเหตุ

รันบนเซิร์ฟเวอร์:
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.check_tenants

สิ่งที่ตรวจ
  1) จำนวนแถวโรงเรียนในฐานข้อมูลจริง เทียบกับตัวเลขแต่ละใบในคอนโซล
     (คอนโซลมีหลายตัวเลข "ทั้งหมด" กับ "ใช้งานอยู่" ไม่เท่ากัน ถ้าหมดอายุ)
  2) โฟลเดอร์ข้อมูลโรงเรียนบนดิสก์ ที่ไม่มีแถวในฐานข้อมูลแล้ว
     -> ถ้าเจอ แปลว่าแถวถูกลบแต่ข้อมูลยังอยู่ กู้คืนได้
  3) เลขโรงเรียนที่ขาดหายไปในลำดับ
  4) ประวัติการลบใน audit log
"""
import sys
from datetime import date, datetime


def main() -> int:
    from app.accounts import Account, Tenant, acc_session
    from app.database import get_data_dir

    db = acc_session()
    try:
        tenants = db.query(Tenant).order_by(Tenant.id).all()
        today = date.today()
        total = len(tenants)
        active = sum(1 for t in tenants
                     if t.active and not (t.expiry_date and t.expiry_date < today))
        suspended = sum(1 for t in tenants if not t.active)
        expired = sum(1 for t in tenants if t.expiry_date and t.expiry_date < today)
        owners = db.query(Account).filter_by(is_owner=True, active=True).count()

        print("=" * 68)
        print("  จำนวนโรงเรียนในฐานข้อมูล")
        print("=" * 68)
        print(f"  แถวโรงเรียนทั้งหมด (ตัวเลขใบ 'โรงเรียนทั้งหมด')   {total}")
        print(f"  ใช้งานอยู่และยังไม่หมดอายุ (ใบ 'ใช้งานอยู่')      {active}")
        print(f"  ถูกระงับ (active = 0)                              {suspended}")
        print(f"  หมดอายุแล้ว                                        {expired}")
        print(f"  ไอดีหลักที่ยังใช้งาน (ใช้ส่งอีเมลประกาศ)           {owners}")
        if total != active:
            print(f"\n  ** คอนโซลมีหลายตัวเลข ถ้าที่เห็นลดลงคือ {active} "
                  f"แต่ {total} เท่าเดิม แปลว่าไม่มีใครถูกลบ **")

        # ---------- โฟลเดอร์ข้อมูลที่ไม่มีเจ้าของแล้ว ----------
        ids = {t.id for t in tenants}
        folder = get_data_dir() / "schools"
        on_disk = set()
        if folder.exists():
            for p in folder.iterdir():
                if p.is_dir() and p.name.isdigit():
                    on_disk.add(int(p.name))
        orphan = sorted(on_disk - ids)
        missing_data = sorted(ids - on_disk)

        print("\n" + "=" * 68)
        print("  ข้อมูลบนดิสก์")
        print("=" * 68)
        print(f"  โฟลเดอร์โรงเรียนบนดิสก์   {len(on_disk)}")
        if orphan:
            print(f"\n  !! มีข้อมูลค้างอยู่ {len(orphan)} โรงเรียน ที่ไม่มีแถวในฐานข้อมูลแล้ว")
            print("     แปลว่าแถวถูกลบไปจริง แต่ไฟล์ข้อมูลยังอยู่ (กู้คืนได้)")
            for tid in orphan:
                dbfile = folder / str(tid) / "school.db"
                size = dbfile.stat().st_size // 1024 if dbfile.exists() else 0
                when = (datetime.fromtimestamp(dbfile.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                        if dbfile.exists() else "-")
                print(f"       โรงเรียน #{tid}  ไฟล์ {size:,} KB  แก้ล่าสุด {when}")
        else:
            print("  ไม่มีข้อมูลค้างที่ไม่มีเจ้าของ (ไม่มีร่องรอยว่ามีใครถูกลบ)")
        if missing_data:
            print(f"\n  !! มีแถวโรงเรียน {len(missing_data)} รายการ ที่ไม่มีโฟลเดอร์ข้อมูล: {missing_data}")

        # ---------- เลขที่ขาดหายในลำดับ ----------
        if ids:
            gaps = sorted(set(range(1, max(ids) + 1)) - ids)
            print(f"\n  เลขโรงเรียนที่ไม่มีในฐานข้อมูล (ตั้งแต่ 1 ถึง {max(ids)}): "
                  + (", ".join(map(str, gaps)) if gaps else "ไม่มี ครบทุกเลข"))
            print("  (เลขขาดเป็นเรื่องปกติถ้าเคยลบโรงเรียนทดลองหรือสมัครไม่สำเร็จ)")

        # ---------- ประวัติการลบ ----------
        print("\n" + "=" * 68)
        print("  ประวัติการลบโรงเรียนใน audit log")
        print("=" * 68)
        try:
            from app.accounts import AuditLog
            rows = (db.query(AuditLog)
                    .filter(AuditLog.action.like("%delete%"))
                    .order_by(AuditLog.id.desc()).limit(25).all())
            if not rows:
                print("  ไม่มีรายการลบเลย")
            for r in rows:
                when = r.at.strftime("%d/%m/%Y %H:%M") if getattr(r, "at", None) else "-"
                print(f"  {when}  {r.action:<22} {r.username or '-':<22} {r.target or ''}")
        except Exception as e:      # noqa: BLE001
            print("  อ่าน audit log ไม่ได้:", e)

        # ---------- 10 โรงเรียนล่าสุด ----------
        print("\n" + "=" * 68)
        print("  10 โรงเรียนที่สมัครล่าสุด")
        print("=" * 68)
        for t in sorted(tenants, key=lambda x: x.id, reverse=True)[:10]:
            when = t.created_at.strftime("%d/%m/%Y") if t.created_at else "-"
            flag = "" if t.active else "  [ระงับ]"
            exp = f" หมดอายุ {t.expiry_date}" if t.expiry_date else ""
            print(f"  #{t.id:<4} {when}  {(t.name or '')[:38]:<40}{exp}{flag}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
