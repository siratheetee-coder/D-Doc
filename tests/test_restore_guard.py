# -*- coding: utf-8 -*-
"""กันระบบกู้คืนไฟล์สำรองเก่าทับข้อมูลสดตอนเปิดเครื่อง

เหตุการณ์จริง 02/10/2569: โรงเรียน 2 แห่งหายจากคอนโซลหลังรีสตาร์ท
โฟลเดอร์ข้อมูลยังอยู่ครบ แต่แถวโรงเรียนและบัญชีหาย และไม่มีร่องรอยใน audit log
(เพราะ audit log อยู่ในไฟล์ accounts.db ที่ถูกทับไปด้วย)

กติกาที่ต้องถูก
  - มีโฟลเดอร์ข้อมูลโรงเรียนบนดิสก์อยู่แล้ว = ห้ามกู้คืนทับ ไม่ว่ากรณีใด
  - ดิสก์ว่างจริง ก็ยังต้องตั้ง DDOC_RESTORE_ON_EMPTY=1 ก่อนถึงจะกู้ให้
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_restore_guard.py
"""
import pathlib
import tempfile

import pytest


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    monkeypatch.setattr(ac, "get_data_dir", lambda: tmp)
    calls = []
    import app.services.backup as bk
    monkeypatch.setattr(bk, "restore_latest_from_s3", lambda: calls.append("restore") or True)
    monkeypatch.delenv("DDOC_RESTORE_ON_EMPTY", raising=False)
    return tmp, ac, calls


def test_never_restores_over_live_school_data(env, monkeypatch):
    """ข้อมูลโรงเรียนยังอยู่บนดิสก์ แต่ accounts.db หาย -> ห้ามดึงของเก่ามาทับ

    เปิดสวิตช์ไว้ด้วย เพื่อให้เหลือเงื่อนไขเดียวที่กันอยู่คือ "มีข้อมูลสดบนดิสก์"
    ไม่งั้นเทสจะผ่านเพราะสวิตช์ปิด ทั้งที่ตัวกันจริงถูกถอดออกไปแล้ว
    """
    tmp, ac, calls = env
    monkeypatch.setenv("DDOC_RESTORE_ON_EMPTY", "1")
    (tmp / "schools" / "59").mkdir(parents=True)
    (tmp / "schools" / "59" / "school.db").write_bytes(b"x")
    ac._restore_if_truly_empty()
    assert calls == [], "มีข้อมูลสดอยู่ ต้องไม่กู้คืนทับเด็ดขาด"


def test_empty_disk_still_needs_the_switch(env):
    """ดิสก์ว่างจริง แต่ไม่ได้เปิดสวิตช์ไว้ -> เริ่มใหม่ ไม่ดึงของเก่ามา"""
    tmp, ac, calls = env
    ac._restore_if_truly_empty()
    assert calls == []


def test_empty_disk_with_the_switch_restores(env, monkeypatch):
    """โฮสต์ดิสก์ชั่วคราวที่ตั้งใจใช้ท่านี้ ยังทำงานเหมือนเดิม"""
    tmp, ac, calls = env
    monkeypatch.setenv("DDOC_RESTORE_ON_EMPTY", "1")
    ac._restore_if_truly_empty()
    assert calls == ["restore"]


def test_does_nothing_when_accounts_db_is_there(env, monkeypatch):
    tmp, ac, calls = env
    (tmp / "accounts.db").write_bytes(b"x")
    monkeypatch.setenv("DDOC_RESTORE_ON_EMPTY", "1")
    ac._restore_if_truly_empty()
    assert calls == []
