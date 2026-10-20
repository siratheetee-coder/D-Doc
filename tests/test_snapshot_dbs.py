# -*- coding: utf-8 -*-
"""deploy/snapshot_dbs.py: สำรองฐาน SQLite ให้ครบ (รวมข้อมูลที่ยังอยู่ใน -wal) + จับฐานเสีย
เจอจากการซ้อมกู้ 2026-10-20: backup.sh ใช้ cp (เครื่องไม่มีคำสั่ง sqlite3) ได้ accounts.db ที่ดัชนีไม่ตรง
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_snapshot_dbs.py
"""
import importlib.util
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("snapshot_dbs", ROOT / "deploy" / "snapshot_dbs.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)


def _wal_db(path: Path):
    """ฐานโหมด WAL ที่ "แอปกำลังเปิดอยู่" ข้อมูลล่าสุดยังไม่ checkpoint (อยู่ใน -wal)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, action TEXT)")
    c.execute("CREATE INDEX ix_audit_log_action ON audit_log(action)")
    c.executemany("INSERT INTO audit_log (action) VALUES (?)", [(f"a{i}",) for i in range(500)])
    c.commit()
    return c


def test_snapshot_includes_wal_data_that_cp_misses(tmp_path):
    data = tmp_path / "data"
    app_conn = _wal_db(data / "accounts.db")
    try:
        assert (data / "accounts.db-wal").stat().st_size > 0
        # วิธีเดิม: cp แค่ .db -> ไม่มีข้อมูลที่อยู่ใน -wal
        shutil.copyfile(data / "accounts.db", tmp_path / "cp.db")
        old = sqlite3.connect(tmp_path / "cp.db")
        try:
            got = old.execute("SELECT count(*) FROM sqlite_master WHERE name='audit_log'").fetchone()[0]
        finally:
            old.close()
        assert got == 0, "ยืนยันปัญหาเดิม: cp ไม่ได้ข้อมูลใน -wal"
        stage = tmp_path / "stage"
        stage.mkdir()
        assert snap.main([str(data), str(stage)]) == 0
        c = sqlite3.connect(stage / "accounts.db")
        try:
            assert c.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 500
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete", "สำเนาเป็นไฟล์เดียว"
        finally:
            c.close()
        assert not (stage / "accounts.db-wal").exists()
    finally:
        app_conn.close()


def test_subfolders_skip_and_check_live(tmp_path, capsys):
    data = tmp_path / "data"
    for rel in ("accounts.db", "schools/1/school.db", "schools/2/school.db", "backups/old.db", "documents/x.db"):
        _wal_db(data / rel).close()
    stage = tmp_path / "stage"
    stage.mkdir()
    assert snap.main([str(data), str(stage)]) == 0
    got = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*.db"))
    assert got == ["accounts.db", "schools/1/school.db", "schools/2/school.db"], "ไม่สำรองโฟลเดอร์ backups/documents"
    before = sorted(p.name for p in data.rglob("*"))
    assert snap.main([str(data), "--check-live"]) == 0
    assert "ตรวจฐานข้อมูล 3 ไฟล์ · เสีย 0" in capsys.readouterr().out
    assert sorted(p.name for p in data.rglob("*")) == before


def _break_index(db: Path):
    """ทำให้เกิด "wrong # of entries in index" แบบเดียวกับที่เจอบน VPS: ซ่อนดัชนีจาก schema ชั่วคราว
    เพิ่มแถว (ดัชนีไม่ถูกอัปเดต) แล้วคืนดัชนีกลับ"""
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=DELETE")
    row = c.execute("SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master WHERE name='ix_audit_log_action'").fetchone()
    c.execute("PRAGMA writable_schema=ON")
    c.execute("DELETE FROM sqlite_master WHERE name='ix_audit_log_action'")
    c.commit(); c.close()
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO audit_log (action) VALUES (?)", [(f"b{i}",) for i in range(20)])
    c.commit(); c.close()
    c = sqlite3.connect(db)
    c.execute("PRAGMA writable_schema=ON")
    c.execute("INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) VALUES (?,?,?,?,?)", row)
    c.commit(); c.close()


def test_corrupt_index_is_reported_and_fails(tmp_path, capsys):
    data = tmp_path / "data"
    _wal_db(data / "accounts.db").close()
    _break_index(data / "accounts.db")
    c = sqlite3.connect(data / "accounts.db")
    assert "wrong # of entries in index ix_audit_log_action" in " ".join(r[0] for r in c.execute("PRAGMA integrity_check"))
    c.close()
    stage = tmp_path / "stage"
    stage.mkdir()
    assert snap.main([str(data), str(stage)]) == 1
    assert "เสีย accounts.db" in capsys.readouterr().err
    assert snap.main([str(data), "--check-live"]) == 1


def test_refuses_stage_inside_data(tmp_path):
    data = tmp_path / "data"
    _wal_db(data / "accounts.db").close()
    assert snap.main([str(data), str(data / "stage")]) == 2


spec2 = importlib.util.spec_from_file_location("reindex_db", ROOT / "deploy" / "reindex_db.py")
rx = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(rx)


def test_reindex_repairs_index_only_damage_without_losing_rows(tmp_path, capsys):
    db = tmp_path / "accounts.db"
    _wal_db(db).close()
    _break_index(db)
    c = sqlite3.connect(db)
    before = c.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    c.close()
    assert rx.repair(db) == 0
    out = capsys.readouterr().out
    assert "ซ่อมเสร็จ ตรวจผ่าน" in out and "จำนวนแถวเท่าเดิม" in out
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before == 520
    c.close()
    baks = list(tmp_path.glob("accounts.db.before-reindex-*"))
    assert len(baks) == 1, "สำรองฐานเดิมไว้ก่อนซ่อม"
    b = sqlite3.connect(baks[0])
    assert b.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 520
    b.close()
    assert rx.repair(db) == 0 and "ไม่ต้องซ่อม" in capsys.readouterr().out


def test_reindex_refuses_non_index_damage(tmp_path, capsys):
    db = tmp_path / "accounts.db"
    _wal_db(db).close()
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()
    raw = bytearray(db.read_bytes())
    raw[4096 + 8: 4096 + 4000] = bytes([255]) * 3992          # ทำหน้าตารางพัง (ไม่ใช่แค่ดัชนี)
    db.write_bytes(bytes(raw))
    before = db.read_bytes()
    code = rx.repair(db)
    assert code == 3
    assert db.read_bytes() == before, "ความเสียหายแบบอื่น ไม่แตะไฟล์"
    assert not list(tmp_path.glob("accounts.db.before-reindex-*"))


def test_reindex_refuses_mixed_damage_reported_without_crash(tmp_path, capsys):
    """integrity_check รายงานปัญหาอื่นนอกจากดัชนี (หน้าไม่ถูกใช้) = หยุด ไม่ซ่อม ไม่แตะไฟล์"""
    db = tmp_path / "accounts.db"
    _wal_db(db).close()
    _break_index(db)
    c = sqlite3.connect(db)
    c.execute("PRAGMA writable_schema=ON")
    c.execute("CREATE INDEX ix_extra ON audit_log(id)")
    c.commit()
    c.execute("DELETE FROM sqlite_master WHERE name='ix_extra'")       # หน้าของดัชนีนี้กลายเป็นหน้ากำพร้า
    c.commit(); c.close()
    c = sqlite3.connect(db)
    report = [r[0] for r in c.execute("PRAGMA integrity_check")]
    c.close()
    assert any("never used" in r for r in report) and any("index ix_audit_log_action" in r for r in report)
    before = db.read_bytes()
    assert rx.repair(db) == 3
    assert "ไม่ใช่แค่ดัชนี" in capsys.readouterr().out
    assert db.read_bytes() == before and not list(tmp_path.glob("accounts.db.before-reindex-*"))
