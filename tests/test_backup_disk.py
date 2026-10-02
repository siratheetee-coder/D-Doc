# -*- coding: utf-8 -*-
"""ไฟล์สำรองต้องไม่ค้างในเครื่องจนดิสก์เต็ม

เหตุการณ์จริง 02/10/2569: ระบบขึ้น sqlite3.OperationalError: disk I/O error
ทุกครั้งที่ล็อกอิน ซึ่งเกิดจากดิสก์เขียนไม่ได้ ไม่ใช่บั๊กของหน้าใดหน้าหนึ่ง

รอยรั่วที่เจอ: ปุ่ม "สำรองทันที" ในคอนโซลสร้างไฟล์ซิปเกือบร้อยเมกฯ ทุกครั้ง
แต่ไม่เคยลบไฟล์เก่าเลย (มีแต่ตัวจับเวลาที่ลบให้)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_backup_disk.py
"""
import pathlib
import tempfile

import pytest


@pytest.fixture()
def bk(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "accounts.db").write_bytes(b"x" * 1024)
    import app.services.backup as backup
    monkeypatch.setattr(backup, "get_data_dir", lambda: tmp)
    monkeypatch.setattr(backup, "_s3", lambda: (None, None, "ไม่ได้ตั้งค่า S3"))
    return backup, tmp


def _zips(tmp):
    return sorted((tmp / "backups").glob("ddoc-backup-*.zip"))


def test_manual_backup_does_not_pile_up_files(bk):
    """กดปุ่มสำรองรัว ๆ ต้องไม่ทิ้งไฟล์ค้างเป็นสิบชุด"""
    backup, tmp = bk
    for _ in range(8):
        backup.manual_backup()
    assert len(_zips(tmp)) <= backup.KEEP_LOCAL, [p.name for p in _zips(tmp)]


def test_scheduled_backup_also_prunes(bk):
    backup, tmp = bk
    for i in range(6):
        (tmp / f"file{i}.txt").write_text(str(i), encoding="utf-8")
        backup.run_backup(force=True)
    assert len(_zips(tmp)) <= backup.KEEP_LOCAL


def test_refuses_to_back_up_when_the_disk_is_nearly_full(bk, monkeypatch):
    """ดิสก์ใกล้เต็มแล้วยังสำรอง = เร่งให้เต็มเร็วขึ้น ต้องหยุดและบอกเหตุผล"""
    backup, tmp = bk
    monkeypatch.setattr(backup, "_free_gb", lambda: 0.2)
    msg = backup.manual_backup()
    assert "พื้นที่ดิสก์เหลือ" in msg, msg
    assert not _zips(tmp), "ดิสก์ใกล้เต็ม ต้องไม่สร้างไฟล์สำรองเพิ่ม"


def test_prune_keeps_the_newest(bk):
    backup, tmp = bk
    d = tmp / "backups"
    d.mkdir(exist_ok=True)
    names = [f"ddoc-backup-2026100{i}-120000.zip" for i in range(1, 7)]
    for n in names:
        (d / n).write_bytes(b"x")
    backup.prune_local(keep=2)
    left = {p.name for p in _zips(tmp)}
    assert left == set(names[-2:]), left
