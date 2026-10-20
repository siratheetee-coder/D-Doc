#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_dbs.py - คัดลอกฐานข้อมูล SQLite ทุกไฟล์ให้ "ครบและสอดคล้อง" ด้วย backup API ของ SQLite

    python3 snapshot_dbs.py <data_dir> <stage_dir>     # ใช้ใน backup.sh
    python3 snapshot_dbs.py <data_dir> --check-live    # ตรวจฐานจริงว่าเสียไหม (ผ่านสำเนาชั่วคราว แล้วลบทิ้ง)

ทำไมไม่ cp: ฐานโหมด WAL เก็บข้อมูลที่บันทึกล่าสุดไว้ในไฟล์ -wal จนกว่าจะ checkpoint
  cp แค่ไฟล์ .db = ได้ข้อมูลไม่ครบ/ดัชนีไม่ตรงกับตาราง (เจอจากการซ้อมกู้ 2026-10-20)
backup API อ่านทั้ง .db และ -wal ให้ได้ภาพเดียวกัน ณ เวลาหนึ่ง แม้แอปกำลังเขียนอยู่

ควรรันด้วยผู้ใช้ ddoc (backup.sh ใช้ runuser ให้แล้ว) เพราะการเปิดฐาน WAL อาจสร้างไฟล์ -wal/-shm ข้างฐานจริง
ถ้าสร้างด้วย root บริการ (ผู้ใช้ ddoc) จะเขียนฐานนั้นไม่ได้
ไม่ import อะไรจากแอป ใช้ได้แม้แอปพัง
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

SKIP_TOP = {"backups", "documents"}


def databases(data: Path):
    for p in sorted(data.rglob("*.db")):
        rel = p.relative_to(data)
        if rel.parts[0] in SKIP_TOP or ".before-restore-" in str(p):
            continue
        yield p, rel


def snapshot(src: Path, dst: Path) -> str:
    """คัดลอกแบบสอดคล้อง แล้ว quick_check สำเนา · คืน "" ถ้าดี หรือข้อความปัญหา"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=30)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")       # สำเนาเป็นไฟล์เดียว ไม่ต้องพก -wal
        res = [r[0] for r in d.execute("PRAGMA integrity_check").fetchall()]
        return "" if res == ["ok"] else "; ".join(res[:3])
    finally:
        d.close()
        s.close()


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    data = Path(argv[0]).resolve()
    check_only = argv[1] == "--check-live"
    stage = Path(tempfile.mkdtemp(prefix="ddoc-check-")) if check_only else Path(argv[1]).resolve()
    if stage == data or data in stage.parents:
        print("โฟลเดอร์ปลายทางอยู่ในโฟลเดอร์ข้อมูลจริง ยกเลิก", file=sys.stderr)
        return 2
    n, bad = 0, []
    try:
        for src, rel in databases(data):
            n += 1
            try:
                why = snapshot(src, stage / rel)
            except sqlite3.Error as e:
                why = f"คัดลอกไม่ได้: {e}"
            if why:
                bad.append((rel.as_posix(), why))
    finally:
        if check_only:
            shutil.rmtree(stage, ignore_errors=True)
    for rel, why in bad:
        print(f"เสีย {rel}: {why}", file=sys.stderr)
    print(f"{'ตรวจ' if check_only else 'สำรอง'}ฐานข้อมูล {n} ไฟล์ · เสีย {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
