# -*- coding: utf-8 -*-
"""ซ้อมกู้ข้อมูล: ต้องไม่แตะข้อมูลจริงเลย ไม่ว่าผลจะผ่านหรือไม่ผ่าน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_restore_drill.py
"""
import hashlib
import io
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services import restore_drill as rd

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="ไม่มี openssl")


def _make_live(d: Path, tenants):
    """data/ จำลอง: accounts.db + schools/<id>/school.db"""
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(d / "accounts.db")
    con.execute("CREATE TABLE tenant (id INTEGER PRIMARY KEY, name TEXT, plan TEXT, created_at TEXT)")
    for tid, plan, created in tenants:
        con.execute("INSERT INTO tenant VALUES (?,?,?,?)", (tid, f"โรงเรียน {tid}", plan, created))
    con.commit(); con.close()
    for tid, _plan, _c in tenants:
        p = d / "schools" / str(tid)
        p.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(p / "school.db")
        con.execute("CREATE TABLE student (id INTEGER PRIMARY KEY, name TEXT)")
        con.execute("CREATE TABLE finance_txn (id INTEGER PRIMARY KEY, amount REAL)")
        con.executemany("INSERT INTO student (name) VALUES (?)", [(f"นักเรียน {i}",) for i in range(5)])
        con.execute("INSERT INTO finance_txn (amount) VALUES (100)")
        con.commit(); con.close()
    (d / "secret.key").write_text("k", encoding="utf-8")


def _snapshot(d: Path) -> dict:
    """ทุกไฟล์ในโฟลเดอร์จริง: เนื้อหา + เวลาแก้ไข (ต้องเหมือนเดิมเป๊ะหลังซ้อม)"""
    return {p.relative_to(d).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(d.rglob("*")) if p.is_file()}


def _backup(src: Path, out: Path, key: Path = None, mtime: float = None) -> Path:
    raw = out.with_suffix("") if key else out
    with tarfile.open(raw, "w:gz") as tf:
        tf.add(src, arcname=".")
    if key:
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt",
                        "-pass", f"file:{key}", "-in", str(raw), "-out", str(out)], check=True)
        raw.unlink()
    if mtime:
        os.utime(out, (mtime, mtime))
    return out


@pytest.fixture()
def setup(tmp_path):
    old = (datetime.now() - timedelta(days=30)).isoformat()
    live = tmp_path / "live" / "data"
    _make_live(live, [(1, "member", old), (2, "trial", old), (3, "sandbox", old)])
    key = tmp_path / "backup.key"
    key.write_text("รหัสลับทดสอบ-1234567890", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    return live, key, work, tmp_path


@needs_openssl
def test_good_backup_passes_and_live_untouched(setup):
    live, key, work, tmp = setup
    bk = _backup(live, tmp / "ddoc-backup-20261020-020001.tar.gz.enc", key)
    before = _snapshot(live)
    r = rd.drill(bk, key, live, str(work))
    assert r["ok"], r["problems"]
    assert r["stats"]["schools_in_backup"] == 2 and r["stats"]["schools_live"] == 2, "ไม่นับระบบตัวอย่าง"
    assert r["stats"]["rows_student"] == 15 and r["stats"]["databases_bad"] == 0
    assert _snapshot(live) == before, "ข้อมูลจริงต้องเหมือนเดิมทุกไบต์ ไม่มีไฟล์ใหม่ (-wal/-shm)"
    assert list(work.iterdir()) == [] and r["cleaned"], "ลบสำเนาชั่วคราว (มีข้อมูลนักเรียน) แล้ว"
    text = rd.format_report(r)
    assert "ผ่าน" in text and "นักเรียน 0" not in text, "สรุปมีแต่ตัวเลข ไม่มีชื่อ"


@needs_openssl
def test_wrong_key_fails_without_touching_live(setup):
    live, key, work, tmp = setup
    bk = _backup(live, tmp / "ddoc-backup-x.tar.gz.enc", key)
    other = tmp / "other.key"
    other.write_text("ไม่ใช่รหัสนี้", encoding="utf-8")
    before = _snapshot(live)
    r = rd.drill(bk, other, live, str(work))
    assert not r["ok"] and "ถอดรหัส" in " ".join(r["problems"])
    assert _snapshot(live) == before and list(work.iterdir()) == []


def test_school_missing_from_backup_is_a_problem(setup):
    live, key, work, tmp = setup
    stale = tmp / "stale" / "data"
    shutil.copytree(live, stale)
    con = sqlite3.connect(stale / "accounts.db")
    con.execute("DELETE FROM tenant WHERE id = 2"); con.commit(); con.close()
    bk = _backup(stale, tmp / "ddoc-backup-old.tar.gz", mtime=time.time())
    r = rd.drill(bk, key, live, str(work))
    assert not r["ok"] and any("ไม่อยู่ในไฟล์สำรอง" in p and "[2]" in p for p in r["problems"])
    # โรงเรียนที่สมัครหลังเวลาสำรอง ไม่ใช่ปัญหา
    con = sqlite3.connect(live / "accounts.db")
    con.execute("UPDATE tenant SET created_at = ? WHERE id = 2", (datetime.now().isoformat(),))
    con.commit(); con.close()
    bk2 = _backup(stale, tmp / "ddoc-backup-old2.tar.gz", mtime=time.time() - 7200)
    assert rd.drill(bk2, key, live, str(work))["ok"]


def test_corrupt_database_in_backup_is_a_problem(setup):
    live, key, work, tmp = setup
    bad = tmp / "bad" / "data"
    shutil.copytree(live, bad)
    p = bad / "schools" / "1" / "school.db"
    b = bytearray(p.read_bytes())
    b[100:4000] = b"\x00" * 3900
    p.write_bytes(bytes(b))
    r = rd.drill(_backup(bad, tmp / "ddoc-backup-bad.tar.gz"), key, live, str(work))
    assert not r["ok"] and any("ฐานข้อมูลเสีย schools/1/school.db" in x for x in r["problems"])
    assert list(work.iterdir()) == []


def test_tar_path_traversal_rejected(setup):
    live, key, work, tmp = setup
    out = tmp / "ddoc-backup-evil.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        data = b"x"
        ti = tarfile.TarInfo("../../evil.txt"); ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    before = _snapshot(live)
    r = rd.drill(out, key, live, str(work))
    assert not r["ok"] and not (tmp / "evil.txt").exists() and not (work.parent / "evil.txt").exists()
    assert _snapshot(live) == before


def test_refuses_work_dir_inside_live_data(setup):
    live, key, work, tmp = setup
    bk = _backup(live, tmp / "ddoc-backup-y.tar.gz")
    before = _snapshot(live)
    r = rd.drill(bk, key, live, str(live))
    assert not r["ok"] and "ข้อมูลจริง" in " ".join(r["problems"])
    assert _snapshot(live) == before and not [p for p in live.iterdir() if p.name.startswith("ddoc-drill-")]


def test_latest_backup_and_healthcheck_see_encrypted_files(tmp_path, monkeypatch):
    for i, name in enumerate(("ddoc-backup-1.tar.gz", "ddoc-backup-2.tar.gz.enc")):
        p = tmp_path / name
        p.write_bytes(b"x" * 20000)
        os.utime(p, (time.time() - 100 + i * 50,) * 2)
    assert rd.latest_backup(tmp_path).name == "ddoc-backup-2.tar.gz.enc"
    from app.services import healthcheck as hc
    monkeypatch.setattr(hc, "BACKUP_DIR", tmp_path)
    for p in tmp_path.glob("*.tar.gz"):
        p.unlink()
    r = hc.check_backup()
    assert "ddoc-backup-2.tar.gz.enc" in r["detail"], "healthcheck ต้องเห็นไฟล์สำรองที่เข้ารหัส"


def test_live_wal_database_gets_no_new_files(setup):
    """ฐานจริงโหมด WAL ที่ไม่มี -wal/-shm อยู่ (บริการปิดอยู่) ต้องไม่ถูกสร้างไฟล์ใหม่ข้าง ๆ"""
    live, key, work, tmp = setup
    for db in [live / "accounts.db"] + list(live.glob("schools/*/school.db")):
        c = sqlite3.connect(db); c.execute("PRAGMA journal_mode=WAL"); c.close()
    bk = _backup(live, tmp / "ddoc-backup-wal.tar.gz")
    before = _snapshot(live)
    r = rd.drill(bk, key, live, str(work))
    assert r["ok"], r["problems"]
    assert _snapshot(live) == before, "ไม่มี accounts.db-wal / -shm งอกขึ้นในโฟลเดอร์จริง"


def test_live_wal_with_app_running_reads_recent_rows(setup):
    """บริการกำลังเปิดฐานอยู่ (มี -wal ที่ยังไม่ checkpoint) ต้องเห็นโรงเรียนล่าสุดด้วย"""
    live, key, work, tmp = setup
    c = sqlite3.connect(live / "accounts.db"); c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    bk = _backup(live, tmp / "ddoc-backup-run.tar.gz", mtime=time.time() + 10)
    c.execute("INSERT INTO tenant VALUES (9, 'ใหม่', 'member', ?)", ((datetime.now() - timedelta(days=3)).isoformat(),))
    c.commit()
    try:
        r = rd.drill(bk, key, live, str(work))
        assert r["stats"]["schools_live"] == 3 and any("[9]" in p for p in r["problems"])
    finally:
        c.close()
