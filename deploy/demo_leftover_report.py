#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_leftover_report.py - หาโรงเรียนที่มีข้อมูลตัวอย่างค้าง (อ่านอย่างเดียว ไม่ลบ ไม่แก้อะไร)

ที่มา: ก่อนแก้ 888431d โรงเรียนใหม่ที่ได้เลข id ซ้ำกับระบบตัวอย่างที่ลบไปแล้ว ได้ข้อมูลตัวอย่างติดมา
(บุคลากรตัวอย่าง 12 ชื่อ ผู้ขายตัวอย่าง เรื่องจัดซื้อ การเงิน ฯลฯ) สคริปต์นี้แค่รายงาน ให้เจ้าของดูก่อนตัดสินใจ

    sudo -u ddoc /opt/ddoc/.venv/bin/python /opt/ddoc/deploy/demo_leftover_report.py /opt/ddoc/data
    ... /opt/ddoc/data --detail            # แจกแจงรายตารางที่มีข้อมูลเกินต้นแบบ ทุกโรงเรียน
    ... /opt/ddoc/data --detail 126 247    # เฉพาะบางโรงเรียน

เปิดฐานแบบ mode=ro ทั้งหมด รันด้วยผู้ใช้ ddoc (ไม่ใช่ root) ไม่ import แอป
คอลัมน์สำคัญ:
  ตัวอย่าง   = ชื่อบุคลากรตัวอย่างที่พบ (จาก 12 ชื่อ)
  คนอื่น     = บุคลากรที่ไม่ใช่ชื่อตัวอย่าง (โรงเรียนเพิ่มเอง)
  เกินต้นแบบ = จำนวนแถวที่มากกว่าข้อมูลตัวอย่างต้นแบบ รวมทุกตาราง (ข้อมูลที่โรงเรียนกรอกเองโดยประมาณ)
"""
import sqlite3
import sys
from pathlib import Path

DEMO_PEOPLE = ["นายวิชัย รักเรียน", "นางสาวสมใจ ใจดี", "นายประเสริฐ มั่นคง", "นางมาลี สุขสันต์", "นายธนากร ศรีสว่าง",
               "นางสาวกนกพร แสงทอง", "นายอนุชา พงษ์ไพร", "นางสุภาพร บุญมา", "นางสาวปิยะนุช ทองดี",
               "นายชาญวิทย์ เก่งกาจ", "นางสาวรัตนา พึ่งบุญ", "นายสมศักดิ์ ขยันงาน"]
DEMO_SCHOOL = "โรงเรียนบ้านตัวอย่างวิทยา"
SKIP_TABLES = {"app_data_migration", "sqlite_sequence", "alembic_version"}


def ro(path):
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=10)


def counts(db):
    out = {}
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in SKIP_TABLES:
            continue
        try:
            out[t] = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except sqlite3.Error:
            pass
    return out


def main(argv):
    detail = "--detail" in argv
    only = {int(x) for x in argv if x.isdigit()}
    argv = [a for a in argv if not a.startswith("--") and not a.isdigit()]
    if len(argv) != 1:
        print(__doc__)
        return 2
    data = Path(argv[0])
    details = []
    templates = sorted((data / "sandbox").glob("template-*.db"))
    base = {}
    if templates:
        t = ro(templates[-1])
        base = counts(t)
        t.close()
        print(f"ต้นแบบข้อมูลตัวอย่าง: {templates[-1].name}")
    else:
        print("ไม่พบไฟล์ต้นแบบ (data/sandbox/template-*.db) คอลัมน์ 'เกินต้นแบบ' จะนับทุกแถว")
    acc = ro(data / "accounts.db")
    tenants = acc.execute("SELECT id, name, plan, created_at, last_active_at, active FROM tenant "
                          "WHERE plan != 'sandbox' ORDER BY id").fetchall()
    users = dict(acc.execute("SELECT tenant_id, COUNT(*) FROM account GROUP BY tenant_id").fetchall())
    acc.close()
    rows = []
    for tid, name, plan, created, last, active in tenants:
        f = data / "schools" / str(tid) / "school.db"
        if not f.exists():
            continue
        try:
            db = ro(f)
            people = [r[0] for r in db.execute("SELECT name FROM person")]
            sch = db.execute("SELECT name FROM school LIMIT 1").fetchone()
            c = counts(db)
            db.close()
        except sqlite3.Error as e:
            print(f"  ! อ่าน {tid} ไม่ได้: {e}")
            continue
        demo = sum(1 for p in people if p in DEMO_PEOPLE)
        if not demo and not (sch and sch[0] == DEMO_SCHOOL):
            continue
        extra = sum(max(0, n - base.get(t, 0)) for t, n in c.items())
        rows.append((tid, name or "", plan, (created or "")[:10], (last or "")[:10], active, users.get(tid, 0),
                     demo, len(people) - demo, (sch[0] if sch else ""), extra))
        if detail and (not only or tid in only):
            more = sorted(((t, n, base.get(t, 0)) for t, n in c.items() if n > base.get(t, 0)), key=lambda x: -(x[1] - x[2]))
            details.append((tid, name or "", [p for p in people if p not in DEMO_PEOPLE], more))
    print(f"\nพบโรงเรียนที่มีข้อมูลตัวอย่าง {len(rows)} แห่ง (ไม่รวมระบบตัวอย่าง)\n")
    print("id | ชื่อโรงเรียนในบัญชี | แผน | สมัคร | ใช้ล่าสุด | เปิดอยู่ | ผู้ใช้ | ตัวอย่าง/12 | คนอื่น | ชื่อในข้อมูลโรงเรียน | เกินต้นแบบ")
    for r in rows:
        print(" | ".join(str(x) for x in r))
    for tid, name, others, more in details:
        print(f"\n== {tid} {name}")
        if others:
            print("   บุคลากรที่โรงเรียนเพิ่มเอง:", ", ".join(others))
        for t, n, b in more:
            print(f"   {t}: {n} แถว (ต้นแบบ {b}) เกิน {n - b}")
        if not more:
            print("   ไม่มีตารางที่เกินต้นแบบ")
    print("\nอ่านอย่างเดียว ไม่ได้แก้ข้อมูลใด ๆ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
