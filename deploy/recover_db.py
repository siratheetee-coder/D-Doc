#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recover_db.py - ดึงข้อมูลจากฐาน SQLite ที่เสีย (ตัวข้อมูลเสีย ไม่ใช่แค่ดัชนี) ไปสร้างฐานใหม่

ใช้แทน .recover ของ sqlite3 (บางเครื่องคอมไพล์มาไม่มี sqlite_dbpage)

    python3 recover_db.py <ฐานที่เสีย> <ฐานใหม่>

- ไม่แก้ไฟล์ต้นทาง (เปิดแบบ immutable อ่านอย่างเดียว)
- สร้างตารางจาก schema เดิม แล้วไล่อ่านทีละตาราง ถ้าอ่านสะดุดกลางทาง จะอ่านต่อจาก rowid ถัดไป
- แถวที่ rowid ซ้ำหรือชนเงื่อนไข unique ไม่ใส่ แต่จดไว้ใน <ฐานใหม่>.conflicts.txt ให้คนดู
- สร้างดัชนีทีหลัง แล้วตรวจ integrity ของฐานใหม่
"""
import sqlite3
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    src_p, dst_p = Path(sys.argv[1]), Path(sys.argv[2])
    if dst_p.exists():
        sys.exit(f"มีไฟล์ {dst_p} อยู่แล้ว ลบก่อน")
    src = sqlite3.connect(f"file:{src_p}?immutable=1", uri=True)
    dst = sqlite3.connect(dst_p)
    log = open(str(dst_p) + ".conflicts.txt", "w", encoding="utf-8")

    objs = src.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                       "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
    tables = [(n, s) for t, n, _tb, s in objs if t == "table"]
    others = [(n, s) for t, n, _tb, s in objs if t in ("index", "trigger", "view")]
    for n, s in tables:
        dst.execute(s)
    dst.commit()

    total_bad = 0
    for name, _s in tables:
        cols = [r[1] for r in dst.execute(f'PRAGMA table_info("{name}")')]
        ph = ",".join("?" * (len(cols) + 1))
        ins = f'INSERT INTO "{name}" (rowid,{",".join(chr(34)+c+chr(34) for c in cols)}) VALUES ({ph})'
        last, n_ok, n_bad, n_err, seen = None, 0, 0, 0, set()
        while True:
            q = f'SELECT rowid, * FROM "{name}"' + ("" if last is None else " WHERE rowid > ?") + " ORDER BY rowid"
            try:
                cur = src.execute(q, () if last is None else (last,))
                done = True
                for row in cur:
                    rid = row[0]
                    last = rid
                    if len(row) != len(cols) + 1:
                        n_bad += 1
                        log.write(f"{name}\trowid={rid}\tจำนวนคอลัมน์ไม่ตรง\t{row!r}\n")
                        continue
                    if rid in seen:
                        n_bad += 1
                        log.write(f"{name}\trowid={rid}\trowid ซ้ำ\t{row!r}\n")
                        continue
                    seen.add(rid)
                    try:
                        dst.execute(ins, row)
                        n_ok += 1
                    except sqlite3.IntegrityError as e:
                        n_bad += 1
                        log.write(f"{name}\trowid={rid}\t{e}\t{row!r}\n")
            except sqlite3.DatabaseError as e:
                n_err += 1
                log.write(f"{name}\tอ่านสะดุดหลัง rowid={last}\t{e}\n")
                done = n_err > 50
                if last is None:
                    last = 0
                else:
                    last += 1
            if done:
                break
        dst.commit()
        total_bad += n_bad
        note = f"  ชน/ซ้ำ {n_bad}" if n_bad else ""
        note += f"  อ่านสะดุด {n_err}" if n_err else ""
        print(f"{name}: {n_ok}{note}")

    for n, s in others:
        try:
            dst.execute(s)
        except sqlite3.DatabaseError as e:
            print(f"สร้าง {n} ไม่ได้: {e}")
            log.write(f"สร้าง {n} ไม่ได้\t{e}\n")
    dst.commit()
    chk = dst.execute("PRAGMA integrity_check").fetchall()
    print("integrity ฐานใหม่:", chk[0][0] if len(chk) == 1 else f"{len(chk)} บรรทัด")
    print(f"แถวที่ไม่ได้ใส่ทั้งหมด {total_bad} ดูที่ {dst_p}.conflicts.txt")
    log.close()


if __name__ == "__main__":
    main()
