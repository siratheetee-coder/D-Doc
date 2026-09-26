# -*- coding: utf-8 -*-
"""การ์ดกันพลาดของงานจำหน่ายพัสดุ ระดับ HTTP

ครอบบั๊กที่เคยเจอจริง
  - ทางด่วนขออนุมัติจำหน่าย ตัดครุภัณฑ์ออกจากทะเบียนตั้งแต่ยังไม่อนุมัติ
  - ครุภัณฑ์ชิ้นเดียวเปิดได้หลายสำนวนพร้อมกัน -> จำหน่ายซ้ำ
  - ขั้นของสำนวนย้อนกลับเมื่อบันทึกจากหน้าที่ค้างอยู่
  - กรอกแต่ยอดขายรวม แล้วมูลค่าที่จำหน่ายได้รายชิ้นเป็น 0
"""
import pathlib
import tempfile
from datetime import datetime

import pytest


@pytest.fixture()
def client(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.database as dbm, app.tenancy as tn, app.accounts as ac
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    # engine ถูกแคชไว้ในตัวแปรระดับโมดูล ถ้าใช้ของเดิม เทสนี้จะไปเปิดฐานข้อมูลของเทสก่อนหน้า
    #  - tenancy: ฐานของโรงเรียน -> เห็นครุภัณฑ์ของเทสอื่น
    #  - accounts: ฐานบัญชี ซึ่งเก็บ "จำนวนครั้งที่ล็อกอินผิด" ต่อ IP ไว้ด้วย
    #    พอสะสมครบ 8 ครั้งจากเทสอื่น ตัวจำกัดอัตราจะบล็อก ทำให้ล็อกอินไม่ผ่านทั้งไฟล์
    # ใช้ monkeypatch เพื่อให้ "คืนค่าเดิม" ตอนจบเทส ห้ามล้างทิ้งเฉย ๆ ไม่งั้นพังเทสถัดไป
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    import app.routers.auth as auth_mod, app.main as main_mod
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(auth_mod, "authenticate", lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
        "display_name": "x", "must_change": False})
    monkeypatch.setattr(main_mod, "can_use_module", lambda tid, mod: True)
    monkeypatch.setattr(main_mod, "tenant_state", lambda tid: {
        "active": True, "expired": False, "name": "รร.ทดสอบ", "expiry_date": None})
    monkeypatch.setattr(main_mod, "get_account_access", lambda uid: {
        "is_owner": True, "modules": "", "active": True, "welcomed": True})
    c = TestClient(app)
    r = c.post("/login", data={"username": "t", "password": "x"}, follow_redirects=False)
    assert r.status_code in (302, 303), f"ล็อกอินไม่ผ่าน ({r.status_code}) — ตรวจการแยกเทส"
    return c


def _seed(costs=(30000.0, 10000.0)):
    from app.tenancy import session_for
    from app.models import School, Asset
    db = session_for(1)
    sc = db.query(School).first() or School()
    if sc.id is None:
        db.add(sc)
    sc.name = "โรงเรียนทดสอบ"
    sc.director_name = "นายเอนก ทดสอบ"
    for i, cost in enumerate(costs, 1):
        db.add(Asset(asset_code=f"7440-001-{i:04d}/2569", name=f"ของ {i}",
                     category="ครุภัณฑ์สำนักงาน", cost=cost, quantity=1, unit="เครื่อง",
                     useful_life=8, status="ชำรุด", acquired_date=datetime(2023, 8, 31)))
    db.commit()
    ids = [str(a.id) for a in db.query(Asset).order_by(Asset.id).all()]
    db.close()
    return ids


def _new_disposal(client, ids):
    r = client.post("/assets/disposal", data={"year": "2569", "asset_ids": ids},
                    follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def test_quick_memo_does_not_remove_from_register(client):
    """ออกบันทึกขออนุมัติจำหน่าย = ยังไม่จำหน่าย สถานะในทะเบียนต้องไม่เปลี่ยน
    (ระเบียบฯ ข้อ 218 ให้ลงจ่ายหลังจำหน่ายเสร็จจริงเท่านั้น)"""
    from app.tenancy import session_for
    from app.models import Asset
    ids = _seed(costs=(25000.0,))
    r = client.post("/assets/dispose", data={
        "asset_ids": ids, "doc_no": "ศธ 04166/1", "doc_date": "12/10/2569",
        "reason": "ชำรุด", "method": "ขายทอดตลาด", "dispose_value": "3000"})
    assert r.status_code == 200 and len(r.content) > 20000
    db = session_for(1)
    a = db.get(Asset, int(ids[0]))
    assert a.status == "ชำรุด", a.status              # ห้ามเป็น "จำหน่ายแล้ว"
    assert a.dispose_doc_ref == "ศธ 04166/1"          # แต่ยังจำเจตนาไว้
    db.close()


def test_asset_cannot_sit_in_two_open_disposals(client):
    ids = _seed()
    _new_disposal(client, ids)
    r = client.post("/assets/disposal", data={"year": "2569", "asset_ids": ids},
                    follow_redirects=False)
    assert "err=busy" in r.headers["location"]


def test_partial_overlap_skips_only_the_busy_ones(client):
    from app.tenancy import session_for
    from app.models import Asset, AssetDisposal
    ids = _seed()
    _new_disposal(client, ids)
    db = session_for(1)
    extra = Asset(asset_code="7440-001-0003/2569", name="ของ 3", cost=5000.0,
                  quantity=1, unit="เครื่อง", status="ชำรุด")
    db.add(extra)
    db.commit()
    eid = str(extra.id)
    db.close()
    loc = _new_disposal(client, [ids[0], eid])
    assert "skipped=1" in loc
    did = int(loc.split("?")[0].rsplit("/", 1)[1])
    db = session_for(1)
    dp = db.get(AssetDisposal, did)
    assert [it.asset.asset_code for it in dp.items] == ["7440-001-0003/2569"]
    db.close()


def test_stage_is_derived_not_trusted_from_form(client):
    """ขั้นของสำนวนคิดจากวันที่ที่กรอกจริง หน้าเก่าที่ค้างอยู่ต้องทำให้ย้อนขั้นไม่ได้"""
    from app.tenancy import session_for
    from app.models import AssetDisposal
    ids = _seed()
    did = int(_new_disposal(client, ids).split("?")[0].rsplit("/", 1)[1])
    base = {"sale_mode": "specific", "sale_total": "0", "revenue_kind": "แผ่นดิน",
            "fact_days": "7"}

    def stage_after(extra):
        client.post(f"/assets/disposal/{did}", data={**base, **extra},
                    follow_redirects=False)
        db = session_for(1)
        st = db.get(AssetDisposal, did).stage
        db.close()
        return st

    assert stage_after({"stage": "fact"}) == "fact"
    assert stage_after({"order_date": "12/10/2569"}) == "approve"
    assert stage_after({"order_date": "12/10/2569", "sale_date": "20/10/2569"}) == "sell"
    # หน้าเก่าส่ง stage=fact กลับมา ต้องไม่ย้อนขั้น
    assert stage_after({"order_date": "12/10/2569", "sale_date": "20/10/2569",
                        "stage": "fact"}) == "sell"


def test_write_off_spreads_total_when_no_per_item_price(client):
    """กรอกแต่ยอดขายรวม -> เฉลี่ยลงรายชิ้นตามสัดส่วนราคาทุน ผลรวมต้องเท่าที่กรอก"""
    from app.tenancy import session_for
    from app.models import AssetDisposal
    ids = _seed(costs=(30000.0, 10000.0))
    did = int(_new_disposal(client, ids).split("?")[0].rsplit("/", 1)[1])
    client.post(f"/assets/disposal/{did}",
                data={"sale_mode": "specific", "sale_total": "20000",
                      "revenue_kind": "แผ่นดิน", "fact_days": "7"},
                follow_redirects=False)
    client.post(f"/assets/disposal/{did}/write-off", follow_redirects=False)
    db = session_for(1)
    dp = db.get(AssetDisposal, did)
    got = sorted((it.asset.asset_code, it.sold_price) for it in dp.items)
    assert [p for _, p in got] == [15000.0, 5000.0], got     # 3:1 ตามราคาทุน
    assert all(it.asset.status == "จำหน่ายแล้ว" for it in dp.items)
    assert dp.stage == "closed" and dp.written_off_date
    db.close()


def test_write_off_is_what_removes_from_register(client):
    """ก่อนกดลงจ่าย ครุภัณฑ์ต้องยังอยู่ในทะเบียน"""
    from app.tenancy import session_for
    from app.models import Asset
    ids = _seed()
    did = int(_new_disposal(client, ids).split("?")[0].rsplit("/", 1)[1])
    client.get(f"/assets/disposal/{did}/doc/request.docx")
    db = session_for(1)
    assert db.query(Asset).filter_by(status="จำหน่ายแล้ว").count() == 0
    db.close()
    client.post(f"/assets/disposal/{did}/write-off", follow_redirects=False)
    db = session_for(1)
    assert db.query(Asset).filter_by(status="จำหน่ายแล้ว").count() == len(ids)
    db.close()
