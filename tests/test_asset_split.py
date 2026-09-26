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
    # ปีเก็บเป็นสตริงตามที่เขียนไว้ (รหัสทรัพย์สินบางแบบใช้ปี 2 หลัก เช่น /59)
    assert _parse_code("7440-001-0001/2569") == ("7440-001", 1, 4, "2569")
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


def test_split_total_cost_divides(db):
    """ราคาทุนที่กรอกเป็น 'ราคารวม' -> หารเฉลี่ย ผลรวมต้องเท่าเดิมเป๊ะ ไม่บวมเป็น N เท่า"""
    a = _asset(db, cost=138000.0, quantity=5)
    lock_numbers(db)
    split_asset(db, a, cost_mode="total")
    db.commit()
    costs = [r.cost for r in db.query(Asset).all()]
    assert len(costs) == 5
    assert round(sum(costs), 2) == 138000.0, costs      # รวมเท่าเดิม
    assert all(c == 27600.0 for c in costs), costs


def test_split_total_cost_keeps_remainder(db):
    """หารไม่ลงตัว -> เศษสตางค์ยกให้ชิ้นแรก ผลรวมยังเท่าเดิม"""
    a = _asset(db, cost=100.0, quantity=3)
    lock_numbers(db)
    split_asset(db, a, cost_mode="total")
    db.commit()
    costs = sorted(r.cost for r in db.query(Asset).all())
    assert round(sum(costs), 2) == 100.0, costs
    assert costs == [33.33, 33.33, 33.34], costs


def test_split_each_cost_keeps_value(db):
    """ราคาต่อชิ้น -> ทุกชิ้นราคาเดิม (ราคาทุนรวมเพิ่มเป็น N เท่า ซึ่งถูกต้อง)"""
    a = _asset(db, cost=2500.0, quantity=4)
    lock_numbers(db)
    split_asset(db, a, cost_mode="each")
    db.commit()
    costs = [r.cost for r in db.query(Asset).all()]
    assert costs == [2500.0] * 4


def test_cost_groups_finds_duplicates(db):
    """แถวที่ ชื่อ+ประเภท+วันที่ได้มา+เรื่องจัดซื้อ ตรงกัน = กลุ่มเดียวกัน"""
    from app.services.asset_numbering import cost_groups
    for i in range(5):
        _asset(db, name="Smart TV 55 นิ้ว", cost=138000.0, quantity=1, asset_code=f"TV-{i:04d}")
    _asset(db, name="โต๊ะทำงาน", cost=3000.0, quantity=1, asset_code="DESK-0001")
    groups = cost_groups(db)
    assert len(groups) == 1, [g["name"] for g in groups]   # โต๊ะตัวเดียว ไม่นับเป็นกลุ่ม
    g = groups[0]
    assert g["name"] == "Smart TV 55 นิ้ว" and g["n"] == 5
    assert g["total"] == 690000.0 and g["same_cost"] is True


def test_set_group_cost_total(db):
    """กรอกราคารวมทั้งกลุ่ม -> หารเฉลี่ย ผลรวมเท่าที่กรอกพอดี"""
    from app.services.asset_numbering import cost_groups, set_group_cost
    for i in range(5):
        _asset(db, name="Smart TV 55 นิ้ว", cost=138000.0, quantity=1, asset_code=f"TV-{i:04d}")
    g = cost_groups(db)[0]
    assert set_group_cost(db, g["ids"].split(","), "total", 138000) == 5
    db.commit()
    costs = [r.cost for r in db.query(Asset).all()]
    assert round(sum(costs), 2) == 138000.0 and set(costs) == {27600.0}


def test_set_group_cost_each(db):
    from app.services.asset_numbering import cost_groups, set_group_cost
    for i in range(3):
        _asset(db, name="โน้ตบุ๊ก", cost=99999.0, quantity=1, asset_code=f"NB-{i:04d}")
    g = cost_groups(db)[0]
    set_group_cost(db, g["ids"].split(","), "each", 21500)
    db.commit()
    assert [r.cost for r in db.query(Asset).all()] == [21500.0] * 3


def test_set_group_cost_rejects_bad_input(db):
    from app.services.asset_numbering import set_group_cost
    a = _asset(db, quantity=1)
    with pytest.raises(ValueError):
        set_group_cost(db, [], "total", 100)
    with pytest.raises(ValueError):
        set_group_cost(db, [str(a.id)], "total", -5)


# ---------------- รหัสทรัพย์สินแบบคู่มือฯ (ย่อโรงเรียน/ประเภท/ชนิด/ตัวที่/ปีงบ) ----------------
def test_parse_slash_code():
    """นอ/01/06/01/59 -> ช่องรองท้ายคือ 'ตัวที่' ที่ต้องรัน · ปีเก็บตามที่เขียน 2 หลัก"""
    assert _parse_code("นอ/01/06/01/59") == ("นอ/01/06/", 1, 2, "59")
    assert _parse_code("นอ/04/01/07/2569") == ("นอ/04/01/", 7, 2, "2569")


def test_next_codes_keep_slash_format(db):
    _asset(db, asset_code="นอ/03/03/01/59", quantity=3)
    assert next_codes_like(db, "นอ/03/03/01/59", 2) == ["นอ/03/03/02/59", "นอ/03/03/03/59"]


def test_lot_code_writes_range():
    """ชุดเดียวกันหลายชิ้นที่เก็บทะเบียนใบเดียว เขียนเป็นช่วง ตามคู่มือฯ น.17"""
    from app.services.asset_numbering import lot_code
    assert lot_code("นอ/04/01/01/59", 10) == "นอ/04/01/01-10/59"
    assert lot_code("7440-001-0001/2569", 5) == "7440-001-0001-0005/2569"
    assert lot_code("นอ/04/01/01/59", 1) == "นอ/04/01/01/59"        # ชิ้นเดียวไม่ต้องเป็นช่วง
    assert lot_code("นอ/04/01/01-10/59", 10) == "นอ/04/01/01-10/59"  # เป็นช่วงแล้วคงเดิม


def test_expand_lot():
    from app.services.asset_numbering import expand_lot
    assert expand_lot("นอ/04/01/01-04/59") == [
        "นอ/04/01/01/59", "นอ/04/01/02/59", "นอ/04/01/03/59", "นอ/04/01/04/59"]
    assert expand_lot("7440-001-0001-0003/2569") == [
        "7440-001-0001/2569", "7440-001-0002/2569", "7440-001-0003/2569"]
    assert expand_lot("นอ/04/01/01/59") == []      # ไม่ใช่ช่วง
    assert expand_lot("") == []


def test_split_lot_uses_range_numbers(db):
    """แยกลอตที่เขียนเป็นช่วง -> ได้เลขตรงตามช่วงเดิมพอดี ไม่รันเลยไป"""
    a = _asset(db, asset_code="นอ/04/01/01-05/59", quantity=5, cost=1200.0)
    lock_numbers(db)
    assert split_asset(db, a) == 4
    db.commit()
    codes = sorted(r.asset_code for r in db.query(Asset).all())
    assert codes == [f"นอ/04/01/0{i}/59" for i in range(1, 6)], codes


def test_lot_reserves_its_whole_range(db):
    """เลขแบบช่วงจองเลขทุกตัวในช่วง ห้ามแจกเลขในช่วงนั้นซ้ำให้ชิ้นอื่น"""
    _asset(db, asset_code="นอ/04/01/01-10/59", quantity=10, cost=1200.0)
    lock_numbers(db)
    assert next_codes_like(db, "นอ/04/01/01/59", 3) == [
        "นอ/04/01/11/59", "นอ/04/01/12/59", "นอ/04/01/13/59"]


def test_lot_range_dash_style_also_reserved(db):
    """รูปแบบขีดกลางก็ต้องกันช่วงเหมือนกัน"""
    _asset(db, asset_code="7440-001-0001-0005/2569", quantity=5)
    lock_numbers(db)
    assert next_codes_like(db, "7440-001-0001/2569", 2) == [
        "7440-001-0006/2569", "7440-001-0007/2569"]
