#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_cleanup.py - ลบข้อมูลตัวอย่างที่หลุดเข้าโรงเรียนจริง (ก่อนแก้ 888431d) แบบระวังสุด

    cd /opt/ddoc && sudo -u ddoc .venv/bin/python deploy/demo_cleanup.py /opt/ddoc/data 187 249          # ดูก่อน
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python deploy/demo_cleanup.py /opt/ddoc/data 187 249 --apply  # ลบจริง

วิธีคิด (ผิดพลาดไปทางเหลือข้อมูลตัวอย่าง ดีกว่าลบข้อมูลจริงของโรงเรียน):
1. สร้างข้อมูลตัวอย่างใหม่ด้วยโค้ดเดียวกัน ตามวันที่ใกล้วันสมัครของโรงเรียน (ไฟล์ชั่วคราว นอกโฟลเดอร์ข้อมูล)
2. แถวในโรงเรียนที่ "เหมือนทุกช่อง" กับข้อมูลตัวอย่าง (รวมเลข id ไม่นับช่องเวลาบันทึก) = ข้อมูลตัวอย่าง
   แถวที่โรงเรียนแก้หรือเพิ่มเอง ไม่เหมือน จึงไม่ถูกลบ
3. แถวตัวอย่างที่แถวของโรงเรียนยังอ้างถึง (เช่น เรื่องจัดซื้อจริงใช้ผู้ขายตัวอย่าง) เก็บไว้ ไม่ให้ข้อมูลจริงขาดหาย
4. --apply: สำรองไฟล์ด้วย backup API ก่อน (school.db.before-democlean-เวลา) แล้วลบใน transaction เดียว
"""
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SKIP = {"sqlite_sequence", "app_data_migration", "alembic_version"}


def is_time_col(c):
    c = c.lower()
    return c.endswith("_at") or c in ("created", "updated", "updated_on", "created_on")


def build_template(day, out):
    """ข้อมูลตัวอย่างของวันนั้น (โค้ด demo_seed ปัจจุบัน) ลงไฟล์ชั่วคราว"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import init_school_db
    from app.services.demo_seed import seed_school
    eng = create_engine(f"sqlite:///{out}")
    try:
        init_school_db(eng)
        s = sessionmaker(bind=eng)()
        try:
            seed_school(s, today=day)
        finally:
            s.close()
    finally:
        eng.dispose()


def table_cols(db, t):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]


NAME_TABLES = ("vendor", "project")     # จับคู่ด้วยชื่อ + เลข id เดียวกับต้นแบบ (ชื่อเหมือนอย่างเดียวไม่พอ)


def demo_name_ids(paths):
    out = {}
    for p in paths:
        db = sqlite3.connect(p)
        for t in NAME_TABLES:
            try:
                for i, n in db.execute(f'SELECT id, name FROM "{t}"'):
                    out.setdefault(t, set()).add((i, n))
            except sqlite3.Error:
                pass
        db.close()
    return out


def demo_keys(paths):
    """{table: set(tuple ของค่าทุกช่องที่ไม่ใช่เวลา)} จากต้นแบบหลายวัน"""
    out = {}
    for p in paths:
        db = sqlite3.connect(p)
        for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if t in SKIP:
                continue
            cols = [c for c in table_cols(db, t) if not is_time_col(c)]
            if not cols:
                continue
            sel = ", ".join(f'"{c}"' for c in cols)
            out.setdefault(t, {})
            for row in db.execute(f'SELECT {sel} FROM "{t}"'):
                out[t].setdefault(tuple(cols), set()).add(row)
        db.close()
    return out


def references(db, tables):
    """[(ตารางลูก, คอลัมน์, ตารางแม่)] จาก FK ที่ประกาศไว้ + ชื่อคอลัมน์ <ตาราง>_id"""
    refs = set()
    for t in tables:
        for r in db.execute(f'PRAGMA foreign_key_list("{t}")'):
            refs.add((t, r[3], r[2]))
        for c in table_cols(db, t):
            if c.endswith("_id") and c[:-3] in tables:
                refs.add((t, c, c[:-3]))
    return refs


def plan(school_db, keys, signup, name_ids):
    """{table: set(id ที่ลบได้)} + จำนวนที่ต้องเก็บไว้เพราะถูกอ้างถึง"""
    db = sqlite3.connect(f"file:{school_db}?mode=ro", uri=True)
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if t not in SKIP]
    cand, total = {}, {}
    for t in tables:
        cols_all = table_cols(db, t)
        total[t] = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        if "id" not in cols_all or t not in keys:
            continue
        cols = [c for c in cols_all if not is_time_col(c)]
        known = keys[t].get(tuple(cols))
        if not known:
            continue
        sel = ", ".join(f'"{c}"' for c in cols)
        idx = cols.index("id")
        cand[t] = {row[idx] for row in db.execute(f'SELECT {sel} FROM "{t}"') if row in known}
    refs = references(db, tables)
    # ---- รอบ 2: แถวตัวอย่างที่จับคู่ทุกช่องไม่ได้ (ข้อมูลตัวอย่างรุ่นเก่า) ----
    sig = str(signup)[:19]
    sday = sig[:10]
    parents = {}
    for child, col, parent in refs:
        parents.setdefault(child, []).append((col, parent))
    more = True
    while more:
        more = False
        for t in tables:
            cols = table_cols(db, t)
            if "id" not in cols:
                continue
            have = cand.setdefault(t, set())
            pcols = [(c, pt) for c, pt in parents.get(t, []) if cand.get(pt)]
            if "created_at" in cols:
                q = f'SELECT id FROM "{t}" WHERE created_at IS NOT NULL AND created_at < ?'
                new = {r[0] for r in db.execute(q, (sig,))} - have
            elif t in NAME_TABLES and "name" in cols:
                new = {i for i, n in db.execute(f'SELECT id, name FROM "{t}"') if (i, n) in name_ids.get(t, ())} - have
            elif pcols:
                new = set()
                datecol = "date" if "date" in cols else None
                for c, pt in pcols:
                    sel = f'SELECT id, "{c}"' + (f', "{datecol}"' if datecol else "") + f' FROM "{t}"'
                    for row in db.execute(sel):
                        if row[1] in cand[pt] and (not datecol or (row[2] and str(row[2])[:10] < sday)):
                            new.add(row[0])
                new -= have
            else:
                new = set()
            if new:
                have |= new
                more = True
    protected = 0
    changed = True
    while changed:                      # แถวที่ยังเก็บไว้ อ้างถึงแถวตัวอย่าง -> เก็บแถวตัวอย่างนั้นด้วย
        changed = False
        for child, col, parent in refs:
            if parent not in cand or not cand[parent]:
                continue
            keep_ids = cand.get(child, set())
            try:
                rows = db.execute(f'SELECT id, "{col}" FROM "{child}" WHERE "{col}" IS NOT NULL').fetchall()
            except sqlite3.Error:
                continue
            for rid, ref in rows:
                if rid in keep_ids:
                    continue
                if ref in cand[parent]:
                    cand[parent].discard(ref)
                    protected += 1
                    changed = True
    db.close()
    return cand, total, protected


def main(argv):
    apply = "--apply" in argv
    short = "--short" in argv
    tids = [int(a) for a in argv[1:] if a.isdigit()]
    if not argv or not tids:
        print(__doc__)
        return 2
    data = Path(argv[0])
    acc = sqlite3.connect(f"file:{data / 'accounts.db'}?mode=ro", uri=True)
    info = {r[0]: r[1:] for r in acc.execute("SELECT id, name, created_at, plan FROM tenant")}
    linked = {}
    for tid, pid in acc.execute("SELECT tenant_id, person_id FROM account WHERE person_id IS NOT NULL"):
        linked.setdefault(tid, set()).add(pid)
    acc.close()
    tmpd = Path(tempfile.mkdtemp(prefix="democlean-"))
    try:
        for tid in tids:
            if tid not in info or info[tid][2] == "sandbox":
                print(f"\n== {tid}: ไม่พบ หรือเป็นระบบตัวอย่าง ข้าม")
                continue
            name, created, _plan = info[tid]
            f = data / "schools" / str(tid) / "school.db"
            if not f.exists():
                print(f"\n== {tid}: ไม่มีไฟล์ข้อมูล ข้าม")
                continue
            d0 = datetime.fromisoformat(str(created)[:19]).date() if created else date.today()
            paths = []
            for k in (0, 1, 2):            # ระบบตัวอย่างอายุ 24 ชม. ไฟล์อาจมาจากวันก่อนหน้า
                day = d0 - timedelta(days=k)
                p = tmpd / f"t-{day:%Y%m%d}.db"
                if not p.exists():
                    build_template(day, p)
                paths.append(p)
            cand, total, protected = plan(f, demo_keys(paths), created or "9999", demo_name_ids(paths))
            # บุคลากรที่ผูกกับบัญชีผู้ใช้ ห้ามลบ
            if "person" in cand:
                keep = cand["person"] & linked.get(tid, set())
                cand["person"] -= keep
                protected += len(keep)
            n_del = sum(len(v) for v in cand.values())
            print(f"\n== {tid} {name} (สมัคร {str(created)[:10]})  ลบได้ {n_del} แถว  เก็บไว้เพราะถูกอ้างถึง {protected}")
            for t in sorted(cand, key=lambda x: -len(cand[x])):
                if cand[t] and not short:
                    print(f"   {t}: ลบ {len(cand[t])} จาก {total[t]} เหลือ {total[t] - len(cand[t])}")
            left = {t: total[t] - len(cand.get(t, ())) for t in total if total[t] - len(cand.get(t, ())) > 0}
            print("   เหลือหลังลบ:", ", ".join(f"{t} {n}" for t, n in sorted(left.items(), key=lambda x: -x[1])[:20]) or "-")
            if not apply:
                continue
            bak = f.with_name(f"school.db.before-democlean-{time.strftime('%Y%m%d-%H%M%S')}")
            src = sqlite3.connect(str(f), timeout=30)
            dst = sqlite3.connect(str(bak))
            src.backup(dst)
            dst.close()
            src.execute("PRAGMA busy_timeout=10000")
            src.execute("PRAGMA foreign_keys=OFF")
            try:
                src.execute("BEGIN IMMEDIATE")
                for t, ids in cand.items():
                    ids = list(ids)
                    for i in range(0, len(ids), 500):
                        part = ids[i:i + 500]
                        src.execute(f'DELETE FROM "{t}" WHERE id IN ({",".join("?" * len(part))})', part)
                src.execute("COMMIT")
                print(f"   ลบแล้ว สำรองไว้ที่ {bak.name}")
            except Exception:
                src.execute("ROLLBACK")
                raise
            finally:
                src.close()
    finally:
        for p in tmpd.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmpd.rmdir()
        except OSError:
            pass
    if not apply:
        print("\nดูอย่างเดียว ยังไม่ได้ลบ ถ้าถูกต้องให้รันซ้ำพร้อม --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
