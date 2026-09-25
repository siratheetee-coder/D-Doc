# -*- coding: utf-8 -*-
"""แยกครุภัณฑ์รายการที่มีจำนวนมากกว่า 1 ออกเป็นรายชิ้น

ทะเบียนคุมทรัพย์สินกำหนดให้ครุภัณฑ์ 1 ชิ้น = 1 เลขครุภัณฑ์ ถ้ารวมไว้แถวเดียว
จะแจ้งชำรุด/จำหน่ายเฉพาะบางชิ้นไม่ได้
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.database as dbm
from app.models import Asset, AssetNumberUsed
from app.services.asset_numbering import (_parse_code, next_codes_like, split_asset,
                                          lock_numbers)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    dbm.init_school_db(eng)
    with Session(bind=eng) as s:
        yield s


def _asset(db, **kw):
    base = dict(name="เก้าอี้สำนักงาน", category="ครุภัณฑ์สำนักงาน", cost=2500.0,
                useful_life=8, salvage_value=1.0, quantity=5, unit="ตัว",
                location="ห้องธุรการ", status="ใช้งาน",
                acquired_date=dt.datetime(2026, 6, 1), asset_code="7440-001-0001/2569")
    base.update(kw)
    a = Asset(**base)
    db.add(a)
    db.commit()
    return a


def test_parse_code():
    assert _parse_code("7440-001-0001/2569") == ("7440-001", 1, 4, 2569)
    assert _parse_code("7440-0012") == ("7440", 12, 4, None)
    assert _parse_code("ครุภัณฑ์") is None
    assert _parse_code("") is None


def test_next_codes_run_in_same_series(db):
    _asset(db)
    assert next_codes_like(db, "7440-001-0001/2569", 4) == [
        "7440-001-0002/2569", "7440-001-0003/2569",
        "7440-001-0004/2569", "7440-001-0005/2569"]


def test_next_codes_skip_taken(db):
    _asset(db)
    _asset(db, asset_code="7440-001-0002/2569", quantity=1)   # เลขนี้ถูกใช้แล้ว
    assert next_codes_like(db, "7440-001-0001/2569", 2) == [
        "7440-001-0003/2569", "7440-001-0004/2569"]


def test_split_creates_one_row_per_unit(db):
    a = _asset(db)
    lock_numbers(db)
    added = split_asset(db, a)
    db.commit()
    assert added == 4
    rows = db.query(Asset).order_by(Asset.asset_code).all()
    assert len(rows) == 5
    assert [r.asset_code for r in rows] == [f"7440-001-{i:04d}/2569" for i in range(1, 6)]
    assert all(int(r.quantity) == 1 for r in rows)
    # ข้อมูลอื่นต้องคัดลอกมาครบ · ราคาทุนต่อหน่วยคงเดิม
    for r in rows:
        assert r.name == "เก้าอี้สำนักงาน" and r.location == "ห้องธุรการ"
        assert r.cost == 2500.0 and r.useful_life == 8 and r.unit == "ตัว"
        assert r.acquired_date == dt.datetime(2026, 6, 1)
    # เลขที่ออกใหม่ต้องถูกจองไว้ กันนำไปใช้ซ้ำ
    for i in range(2, 6):
        assert db.get(AssetNumberUsed, f"7440-001-{i:04d}/2569")


def test_split_then_mark_one_broken(db):
    """เป้าหมายจริงของฟีเจอร์: แยกแล้วแจ้งชำรุดทีละชิ้นได้"""
    a = _asset(db)
    lock_numbers(db)
    split_asset(db, a)
    db.commit()
    one = db.query(Asset).filter_by(asset_code="7440-001-0003/2569").one()
    one.status = "ชำรุด"
    db.commit()
    assert db.query(Asset).filter_by(status="ใช้งาน").count() == 4
    assert db.query(Asset).filter_by(status="ชำรุด").count() == 1


def test_split_without_code_leaves_blank(db):
    """ไม่มีเลข/เลขอ่านรูปแบบไม่ได้ -> ชิ้นที่เพิ่มเว้นเลขไว้ให้กรอกเอง ไม่เดาเลขมั่ว"""
    a = _asset(db, asset_code="", quantity=3)
    lock_numbers(db)
    assert split_asset(db, a) == 2
    db.commit()
    assert [r.asset_code for r in db.query(Asset).all()] == ["", "", ""]


def test_split_rejects_single(db):
    a = _asset(db, quantity=1)
    with pytest.raises(ValueError):
        split_asset(db, a)
