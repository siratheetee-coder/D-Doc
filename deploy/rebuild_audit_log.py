#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild_audit_log.py - สร้างตาราง audit_log ใน accounts.db ใหม่ เมื่อตารางนี้เสีย ("database disk image is malformed")

    sudo systemctl stop ddoc
    sudo -u ddoc /opt/ddoc/.venv/bin/python /opt/ddoc/deploy/rebuild_audit_log.py /opt/ddoc/data/accounts.db
    sudo systemctl start ddoc

ทำอะไร
  - สำรองฐานทั้งไฟล์ก่อน: <ฐาน>.before-auditfix-<เวลา>
  - อ่านแถว audit_log ทีละช่วง id เก็บเฉพาะแถวที่อ่านได้ (ช่วงที่เสียข้ามไป)
  - DROP ตารางเดิม (รวมดัชนี) แล้วสร้างใหม่ตามโครงเดิม ใส่แถวที่กู้ได้กลับ
  - ไม่แตะตารางอื่น ตรวจ integrity_check ท้ายสุด ไม่ผ่าน = คืนไฟล์สำรอง
audit_log เป็นแค่บันทึกการใช้งาน ถ้าหายบางแถวไม่กระทบการทำงานของระบบ
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

COLS = "id, at, tenant_id, uid, username, action, target, detail, ip"
SCHEMA = [
    """CREATE TABLE audit_log (
        id INTEGER NOT NULL PRIMARY KEY, at DATETIME, tenant_id INTEGER, uid INTEGER,
        username VARCHAR, action VARCHAR, target VARCHAR, detail VARCHAR, ip VARCHAR)""",
    "CREATE INDEX ix_audit_log_at ON audit_log (at)",
    "CREATE INDEX ix_audit_log_tenant_id ON audit_log (tenant_id)",
    "CREATE INDEX ix_audit_log_action ON audit_log (action)",
]


def salvage(con):
    rows, bad = [], 0
    try:
        top = con.execute("SELECT max(id) FROM audit_log NOT INDEXED").fetchone()[0] or 0
    except sqlite3.DatabaseError:
        top = 10_000_000
    step = 500
    for lo in range(0, top + 1, step):
        try:
            rows += con.execute(f"SELECT {COLS} FROM audit_log WHERE id >= ? AND id < ?",
                                (lo, lo + step)).fetchall()
        except sqlite3.DatabaseError:
            for i in range(lo, lo + step):      # ช่วงนี้เสีย ลองทีละแถว
                try:
                    rows += con.execute(f"SELECT {COLS} FROM audit_log WHERE id = ?", (i,)).fetchall()
                except sqlite3.DatabaseError:
                    bad += 1
    return rows, bad


def main(db: Path) -> int:
    if not db.is_file():
        print(f"ไม่พบไฟล์ {db}")
        return 2
    bak = db.with_name(f"{db.name}.before-auditfix-{datetime.now():%Y%m%d-%H%M%S}")
    src = sqlite3.connect(db, timeout=30)
    dst = sqlite3.connect(bak)
    src.backup(dst)
    dst.close()
    print(f"สำรองไว้ที่ {bak}")
    rows, bad = salvage(src)
    print(f"กู้แถวได้ {len(rows)} แถว อ่านไม่ได้ {bad} แถว")
    try:
        src.execute("PRAGMA writable_schema=OFF")
        src.execute("DROP TABLE IF EXISTS audit_log")
        for s in SCHEMA:
            src.execute(s)
        src.executemany(f"INSERT OR IGNORE INTO audit_log ({COLS}) VALUES (?,?,?,?,?,?,?,?,?)", rows)
        src.commit()
        src.execute("VACUUM")
        res = [r[0] for r in src.execute("PRAGMA integrity_check").fetchall()]
    except sqlite3.DatabaseError as e:
        res = [str(e)]
    src.close()
    if res != ["ok"]:
        print("ตรวจหลังซ่อมไม่ผ่าน คืนไฟล์สำรอง:", res[:10])
        for ext in ("-wal", "-shm"):
            Path(str(db) + ext).unlink(missing_ok=True)
        shutil.copy2(bak, db)
        return 3
    print("เสร็จ ฐานข้อมูลผ่าน integrity_check")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
