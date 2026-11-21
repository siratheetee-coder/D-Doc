"""ไฟล์ -wal หาย 26 ต.ค. และ 14 พ.ย. 2569: โค้ดในแอปเปิด/คัดลอกไฟล์ .db ตรง ๆ ทำให้ล็อก SQLite
ของโปรเซสหลุด (POSIX lock) โปรเซสอื่นจึงลบ -wal ทิ้งได้ เทสต์นี้กันไม่ให้กลับมาอีก"""
import re
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"


def _wal_db(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES ('อยู่ใน wal')")
    c.commit()
    return c                    # เปิดค้างไว้ ข้อมูลยังไม่ลงไฟล์หลัก


def test_snapshot_includes_wal_data(tmp_path):
    from app.services.db_snapshot import snapshot, snapshot_bytes
    live = tmp_path / "live.db"
    keep = _wal_db(live)
    try:
        snapshot(live, tmp_path / "copy.db")
        assert sqlite3.connect(tmp_path / "copy.db").execute("SELECT x FROM t").fetchone()[0] == "อยู่ใน wal"
        raw = tmp_path / "b.db"; raw.write_bytes(snapshot_bytes(live))
        assert sqlite3.connect(raw).execute("SELECT count(*) FROM t").fetchone()[0] == 1
        assert (tmp_path / "live.db-wal").exists()      # ของจริงไม่ถูกแตะ
    finally:
        keep.close()


def test_restore_into_live_db_while_open(tmp_path):
    from app.services.db_snapshot import restore_into, snapshot_bytes
    live = tmp_path / "live.db"
    keep = _wal_db(live)
    other = tmp_path / "other.db"
    c = sqlite3.connect(other); c.execute("CREATE TABLE t(x)"); c.execute("INSERT INTO t VALUES ('ใหม่')"); c.commit(); c.close()
    try:
        restore_into(live, snapshot_bytes(other))
        assert keep.execute("SELECT x FROM t").fetchall() == [("ใหม่",)]   # คนที่เปิดอยู่เห็นข้อมูลใหม่
    finally:
        keep.close()


def test_backup_zip_has_no_wal_and_full_data(tmp_path, monkeypatch):
    import app.services.backup as backup
    monkeypatch.setattr(backup, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(backup, "_s3", lambda: (None, None, "x"))
    keep = _wal_db(tmp_path / "accounts.db")
    try:
        z = zipfile.ZipFile(backup._make_zip())
        names = z.namelist()
        assert "accounts.db" in names and not any(n.endswith(("-wal", "-shm")) for n in names)
        (tmp_path / "out.db").write_bytes(z.read("accounts.db"))
        assert sqlite3.connect(tmp_path / "out.db").execute("SELECT x FROM t").fetchone()[0] == "อยู่ใน wal"
    finally:
        keep.close()


# รูปแบบที่ห้ามในโปรเซสแอป: เปิด/คัดลอก/ซิปไฟล์ฐานข้อมูลตรง ๆ
BAD = re.compile(r"(shutil\.copy\w*|open|\.write_bytes|\.read_bytes|z\.write)\s*\(\s*[^)]*(db_path|\.db\b|school_db_path|accounts\.db)")
ALLOWED = {"services/db_snapshot.py", "services/restore_drill.py"}   # restore_drill รันเป็นโปรเซสแยก ไม่มีการเชื่อมต่อค้าง


def test_no_raw_file_access_to_databases_in_app_code():
    bad = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if BAD.search(code):
                bad.append(f"{rel}:{i}: {line.strip()}")
    assert not bad, "ห้ามเปิด/คัดลอกไฟล์ฐานข้อมูลตรง ๆ ใช้ app/services/db_snapshot.py แทน\n" + "\n".join(bad)
