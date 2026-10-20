#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reindex_db.py - ซ่อมดัชนีของฐาน SQLite ที่ไม่ตรงกับตาราง (เช่น "wrong # of entries in index ...")

    sudo systemctl stop ddoc
    sudo -u ddoc /opt/ddoc/.venv/bin/python /opt/ddoc/deploy/reindex_db.py /opt/ddoc/data/accounts.db
    sudo systemctl start ddoc

ป้องกันในตัว
  - ซ่อมเฉพาะเมื่อปัญหาที่ integrity_check รายงาน "เป็นเรื่องดัชนีทั้งหมด" ถ้ามีความเสียหายแบบอื่น หยุด ไม่แตะอะไร
  - สำรองฐานเดิม (backup API ได้ครบรวม -wal) ไว้ข้างกัน: <ฐาน>.before-reindex-<เวลา>
  - นับแถวทุกตารางก่อน/หลัง ต้องเท่ากันทุกตาราง (REINDEX สร้างดัชนีใหม่จากตาราง ไม่ลบข้อมูล)
  - ตรวจซ้ำหลังซ่อม ไม่ผ่านหรือจำนวนแถวไม่ตรง = คืนจากฉบับสำรองทันที
ให้รันด้วยผู้ใช้ ddoc (ไฟล์ที่สร้างเป็นของ ddoc) และหยุดบริการก่อน (ไม่มีการเขียนแทรกระหว่างซ่อม)
"""
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

INDEX_ONLY = re.compile(r"^(wrong # of entries in index \S+|row \d+ missing from index \S+|"
                        r"non-unique entry in index \S+|NULL value in \S+ in index \S+)$")


def integrity(con) -> list:
    return [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]


def counts(con) -> dict:
    """จำนวนแถวจริงจากตัวตาราง · NOT INDEXED สำคัญ: count(*) เฉย ๆ SQLite นับผ่านดัชนีที่เล็กที่สุด
    ซึ่งคือดัชนีที่เพี้ยนอยู่ ตัวเลข "ก่อนซ่อม" จะผิด แล้วเครื่องมือย้อนกลับเองทั้งที่ซ่อมถูก (เจอบน VPS)"""
    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: con.execute(f'SELECT count(*) FROM "{t}" NOT INDEXED').fetchone()[0] for t in tables}


def repair(db: Path) -> int:
    if not db.is_file():
        print(f"ไม่พบไฟล์ {db}")
        return 2
    con = sqlite3.connect(db, timeout=30)
    try:
        try:
            problems = integrity(con)
        except sqlite3.DatabaseError as e:
            print(f"ฐานข้อมูลเสียหนักกว่าดัชนี ({e}) หยุด ไม่แตะอะไร · กู้จากไฟล์สำรองแทน")
            return 3
        if problems == ["ok"]:
            print("ฐานข้อมูลปกติ ไม่ต้องซ่อม")
            return 0
        other = [p for p in problems if not INDEX_ONLY.match(p)]
        if other:
            print("พบความเสียหายที่ไม่ใช่แค่ดัชนี หยุด ไม่แตะอะไร (ส่งข้อความนี้ให้ผู้ดูแล):")
            for p in other[:10]:
                print("  ", p)
            return 3
        print("ปัญหาที่พบ (ดัชนีทั้งหมด):")
        for p in problems[:10]:
            print("  ", p)
        bak = db.with_name(f"{db.name}.before-reindex-{datetime.now():%Y%m%d-%H%M%S}")
        b = sqlite3.connect(bak)
        try:
            con.backup(b)
            b.execute("PRAGMA journal_mode=DELETE")
        finally:
            b.close()
        print(f"สำรองฐานเดิมไว้แล้ว: {bak}")
        before = counts(con)
        con.execute("REINDEX")
        con.commit()
        after_check, after = integrity(con), counts(con)
        if after_check != ["ok"] or after != before:
            print("ซ่อมแล้วยังไม่ผ่าน หรือจำนวนแถวไม่ตรง -> คืนจากฉบับสำรอง")
            src = sqlite3.connect(bak)
            try:
                src.backup(con)
            finally:
                src.close()
            return 1
        print(f"ซ่อมเสร็จ ตรวจผ่าน (ok) · จำนวนแถวเท่าเดิมทุกตาราง ({len(after)} ตาราง, รวม {sum(after.values()):,} แถว)")
        print(f"ใช้งานปกติ 1-2 วันแล้วลบฉบับสำรองได้: rm {bak}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(repair(Path(sys.argv[1])))
