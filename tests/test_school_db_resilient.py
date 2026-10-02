# -*- coding: utf-8 -*-
"""ขั้นตอนซ่อมข้อมูลตอนเปิดฐานข้อมูลโรงเรียน ต้องพังทีละขั้น ไม่ลากทั้งโรงเรียนล่ม

เดิมขั้นตอนทั้งหมดเรียงต่อกันโดยไม่มีตัวกัน ถ้าตัวใดตัวหนึ่งพังกับข้อมูลของ
โรงเรียนใดโรงเรียนหนึ่ง engine จะสร้างไม่สำเร็จ แปลว่า "ทุกหน้า" ของโรงเรียนนั้นขึ้น 500 ทั้งหมด
ซึ่งหนักกว่าการที่งานย่อยงานเดียวไม่สมบูรณ์มาก

รัน: .venv\\Scripts\\python.exe -m pytest tests/test_school_db_resilient.py
"""
import pathlib
import tempfile

import pytest


@pytest.fixture()
def engine(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.database as dbm
    import app.tenancy as tn
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp)
    monkeypatch.setattr(tn, "get_data_dir", lambda: tmp)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    return tn, dbm


def test_one_broken_repair_step_does_not_take_the_school_down(engine, monkeypatch, capsys):
    tn, dbm = engine

    def boom(_engine):
        raise RuntimeError("ข้อมูลเดิมซ้ำ สร้างดัชนีไม่ได้")

    monkeypatch.setattr(dbm, "_prune_stale_procurement_docnos", boom)
    db = tn.session_for(1)          # ต้องเปิดได้ ไม่ใช่โยน error
    try:
        from app.models import School
        db.add(School(name="โรงเรียนทดสอบ"))
        db.commit()
        assert db.query(School).first().name == "โรงเรียนทดสอบ"
    finally:
        db.close()
    assert "ข้ามขั้นตอน" in capsys.readouterr().out


def test_tables_are_still_created(engine):
    """ตัวกันต้องไม่กลืนปัญหาร้ายแรง: ไม่มีตาราง = ใช้งานไม่ได้จริง ต้องยังสร้างให้ครบ"""
    tn, dbm = engine
    db = tn.session_for(3)
    try:
        from app.models import FinanceAccount, Procurement, Student, SubsidyRate
        for model in (Student, Procurement, FinanceAccount, SubsidyRate):
            assert db.query(model).count() == 0
    finally:
        db.close()
