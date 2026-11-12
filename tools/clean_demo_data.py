#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_demo_data.py - ลบข้อมูลตัวอย่าง (ของระบบทดลอง) ที่ติดมาในฐานข้อมูลโรงเรียนจริง

เกิดจากโรงเรียนใหม่ได้เลข id ซ้ำกับระบบตัวอย่างที่ลบไป (แก้แล้วใน commit 888431d)

ดูก่อน ไม่แก้อะไร:
    sudo -u ddoc /opt/ddoc/.venv/bin/python /opt/ddoc/tools/clean_demo_data.py <tenant_id>
ลบจริง (หยุดบริการก่อน):
    sudo systemctl stop ddoc
    sudo -u ddoc /opt/ddoc/.venv/bin/python /opt/ddoc/tools/clean_demo_data.py <tenant_id> --apply
    sudo systemctl start ddoc

วิธีแยก: สร้างฐานตัวอย่างใหม่ในไฟล์ชั่วคราว แล้วดูว่าแต่ละตารางมีแถวตัวอย่างถึงเลข id ไหน
แถวตัวอย่างอยู่ช่วง id ต้น ๆ ส่วนที่โรงเรียนกรอกเองจะได้ id ต่อจากนั้น จึงลบเฉพาะ id <= เลขนั้น
ตาราง school (ตั้งค่าโรงเรียน) ไม่ลบแถว ล้างเฉพาะช่องที่ยังเป็นค่าตัวอย่าง
ป้องกัน
  - ตรวจว่าฐานนี้มีร่องรอยข้อมูลตัวอย่างจริง (ชื่อบุคลากรตัวอย่าง) ไม่งั้นหยุด
  - สำรองฐานเดิมไว้ข้างกัน: school.db.before-clean-<เวลา> ก่อนลบ
  - ทำใน transaction เดียว ผิดพลาด = ไม่มีอะไรเปลี่ยน
ข้อจำกัด: ถ้าโรงเรียนลบแถวตัวอย่างของตารางไหนออกหมดแล้วค่อยเพิ่มของตัวเอง แถวนั้นอาจได้ id เดิม
และโดนลบด้วย จึงต้องดูรายงานก่อน --apply ทุกครั้ง
"""
import sqlite3
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build_template(path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import init_school_db
    from app.services.demo_seed import seed_school
    eng = create_engine(f"sqlite:///{path}")
    try:
        init_school_db(eng)
        db = sessionmaker(bind=eng)()
        try:
            seed_school(db, today=date.today())
        finally:
            db.close()
    finally:
        eng.dispose()


def tables(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if len(args) != 1 or not args[0].isdigit():
        print(__doc__)
        sys.exit(2)
    from app.database import get_data_dir
    from app.services.demo_seed import PEOPLE, DEMO_SCHOOL
    from app.models import School
    target = get_data_dir() / "schools" / args[0] / "school.db"
    if not target.exists():
        sys.exit(f"ไม่พบ {target}")

    tmpdir = tempfile.mkdtemp()
    tpl_path = Path(tmpdir) / "tpl.db"
    build_template(tpl_path)
    tpl = sqlite3.connect(tpl_path)
    con = sqlite3.connect(target)

    demo_names = [p[0] for p in PEOPLE]
    q = ",".join("?" * len(demo_names))
    hits = con.execute(f"SELECT count(*) FROM person WHERE name IN ({q})", demo_names).fetchone()[0]
    print(f"พบชื่อบุคลากรตัวอย่าง {hits}/{len(demo_names)} คน")
    if hits == 0:
        sys.exit("ไม่มีร่องรอยข้อมูลตัวอย่าง หยุด ไม่แตะอะไร")

    tpl_tables = set(tables(tpl))
    plan = []   # (table, max_id, ลบ, เหลือ)
    for t in tables(con):
        if t == "school" or t not in tpl_tables:
            continue
        mx = tpl.execute(f'SELECT max(rowid) FROM "{t}"').fetchone()[0]
        if not mx:
            continue
        n_del = con.execute(f'SELECT count(*) FROM "{t}" WHERE rowid <= ?', (mx,)).fetchone()[0]
        n_keep = con.execute(f'SELECT count(*) FROM "{t}" WHERE rowid > ?', (mx,)).fetchone()[0]
        if n_del:
            plan.append((t, mx, n_del, n_keep))

    # ตั้งค่าโรงเรียน: ช่องที่ค่ายังตรงกับตัวอย่าง -> ล้างเป็นค่าว่าง
    cols = [r[1] for r in con.execute("PRAGMA table_info(school)")]
    tpl_row = dict(zip([r[1] for r in tpl.execute("PRAGMA table_info(school)")],
                       tpl.execute("SELECT * FROM school LIMIT 1").fetchone() or []))
    cur = con.execute("SELECT * FROM school LIMIT 1").fetchone()
    reset = []
    if cur:
        for c, v in zip(cols, cur):
            if c in ("id", "academic_year") or v in (None, ""):
                continue
            col = School.__table__.c.get(c)
            dflt = col.default.arg if (col is not None and col.default is not None
                                       and not callable(col.default.arg)) else None
            if v == dflt:           # ค่าเริ่มต้นของระบบ ไม่ใช่ค่าตัวอย่าง
                continue
            if isinstance(v, str) and tpl_row.get(c) == v:
                reset.append(c)

    print("\nตารางที่จะลบแถวตัวอย่าง (ตาราง: ลบ / เหลือที่โรงเรียนกรอกเอง)")
    for t, mx, d, k in plan:
        print(f"  {t}: ลบ {d} / เหลือ {k}")
    print(f"\nตั้งค่าโรงเรียน ช่องที่จะล้าง: {', '.join(reset) or '-'}")
    if cur and DEMO_SCHOOL in [v for v in cur if isinstance(v, str)]:
        print("  (ชื่อโรงเรียนยังเป็นชื่อตัวอย่าง จะถูกล้าง ต้องตั้งชื่อใหม่ในหน้าตั้งค่า)")

    if not apply:
        print("\nโหมดดูอย่างเดียว ยังไม่ได้แก้อะไร เติม --apply เพื่อลบจริง")
        return

    backup = target.with_name(f"school.db.before-clean-{datetime.now():%Y%m%d-%H%M%S}")
    bk = sqlite3.connect(backup)
    con.backup(bk)
    bk.close()
    print(f"\nสำรองไว้ที่ {backup}")
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN")
        for t, mx, _d, _k in plan:
            con.execute(f'DELETE FROM "{t}" WHERE rowid <= ?', (mx,))
        for c in reset:
            con.execute(f'UPDATE school SET "{c}" = ""')
        con.commit()
    except Exception:
        con.rollback()
        raise
    print("ลบข้อมูลตัวอย่างเรียบร้อย")


if __name__ == "__main__":
    main()
