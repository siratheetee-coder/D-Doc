# -*- coding: utf-8 -*-
"""ชุดข้อมูลสาธิตสำหรับถ่ายคลิป (tools/seed_demo.py)

สิ่งที่ต้องกันให้ได้คือ "ห้ามแตะข้อมูลโรงเรียนจริง" ไม่ว่ากรณีใด
"""
import importlib.util
import pathlib
import sys
import tempfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def demo(monkeypatch):
    """โหลด seed_demo บน data dir ชั่วคราว + สร้างโรงเรียน 'จริง' ไว้เทียบว่าไม่ถูกแตะ"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    # เทสไฟล์อื่นแทนที่ authenticate/tenant_state แบบถาวร (ไม่ได้ใช้ monkeypatch)
    # เทสนี้ต้องล็อกอินด้วยของจริง จึงคืนค่าเดิมไว้ก่อน ไม่งั้นจะได้ tenant ของไฟล์อื่น
    import app.routers.auth as auth_mod
    import app.main as main_mod
    monkeypatch.setattr(auth_mod, "authenticate", ac.authenticate)
    monkeypatch.setattr(main_mod, "tenant_state", ac.tenant_state)
    monkeypatch.setattr(main_mod, "can_use_module", ac.can_use_module)
    monkeypatch.setattr(main_mod, "get_account_access", ac.get_account_access)

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from app.accounts import Account, Tenant, acc_session, hash_password
    from app.models import Asset, School
    from app.tenancy import session_for
    with acc_session() as s:
        real = Tenant(name="โรงเรียนจริงของลูกค้า", slug="real", active=True, plan="member")
        s.add(real)
        s.flush()
        s.add(Account(tenant_id=real.id, username="realuser",
                      password_hash=hash_password("Xyz12345!"), is_owner=True))
        s.commit()
        real_id = real.id
    rdb = session_for(real_id)
    rdb.add(School(name="โรงเรียนจริง"))
    rdb.add(Asset(asset_code="REAL-0001", name="ครุภัณฑ์ของจริง", cost=999.0, quantity=1,
                  acquired_date=datetime(2024, 1, 1)))
    rdb.commit()
    rdb.close()
    return mod, real_id, tmp


def _run(mod, *args):
    sys.argv = ["seed_demo.py", *args]
    mod.main()


def _real_intact(real_id):
    from app.models import Asset
    from app.tenancy import session_for
    db = session_for(real_id)
    n = db.query(Asset).count()
    db.close()
    return n == 1


def test_seed_creates_full_demo_school(demo):
    from app.accounts import Account, Tenant, acc_session
    from app.models import (Asset, AssetDisposal, MaterialItem, Person, Procurement,
                            School, Vendor)
    from app.tenancy import session_for
    mod, real_id, _tmp = demo
    _run(mod, "--password", "Demo!2569")

    with acc_session() as s:
        t = s.query(Tenant).filter_by(slug="demo").one()
        a = s.query(Account).filter_by(username="demo").one()
        assert a.is_owner and a.tenant_id == t.id and not a.must_change_password
        assert "procurement" in (t.modules or "")
        tid = t.id
    db = session_for(tid)
    assert db.query(School).first().director_name          # ตั้งค่าโรงเรียนครบ
    assert db.query(Person).count() == 8
    assert db.query(Vendor).count() == 3
    assert db.query(Asset).count() == 12
    assert db.query(MaterialItem).count() == 6
    assert db.query(Procurement).count() == 2
    dp = db.query(AssetDisposal).one()
    assert len(dp.items) == 7
    assert dp.written_off_date is None, "ต้องยังไม่ลงจ่าย จะได้กดสดในคลิปได้"
    # สภาพครุภัณฑ์ต้องคละ ให้เห็นทุกบัญชีตอนถ่าย
    assert {a.status for a in db.query(Asset).all()} >= {
        "ใช้งาน", "ชำรุด", "เสื่อมสภาพ", "สูญไป", "ไม่ใช้"}
    db.close()
    assert _real_intact(real_id)


def test_seed_refuses_to_overwrite_without_reset(demo):
    mod, real_id, _tmp = demo
    _run(mod, "--password", "Demo!2569")
    with pytest.raises(SystemExit):
        _run(mod)
    assert _real_intact(real_id)


def test_reset_rebuilds_demo_only(demo):
    from app.accounts import Tenant, acc_session
    from app.models import Asset
    from app.tenancy import session_for
    mod, real_id, _tmp = demo
    _run(mod, "--password", "Demo!2569")
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    db = session_for(tid)
    db.add(Asset(asset_code="ของที่เผลอเพิ่ม", name="x", cost=1.0, quantity=1))
    db.commit()
    assert db.query(Asset).count() == 13
    db.close()

    _run(mod, "--reset", "--password", "Demo!2569")
    db = session_for(tid)
    assert db.query(Asset).count() == 12          # ล้างแล้วสร้างใหม่
    db.close()
    assert _real_intact(real_id)


def test_refuses_when_slug_belongs_to_someone_else(demo):
    """slug demo ไปชนโรงเรียนอื่น -> ต้องหยุด ทั้งตอน seed และตอน remove"""
    from app.accounts import Tenant, acc_session
    mod, real_id, _tmp = demo
    _run(mod, "--password", "Demo!2569")
    with acc_session() as s:
        t = s.query(Tenant).filter_by(slug="demo").one()
        t.name = "โรงเรียนอื่นที่ดันใช้ slug นี้"
        s.commit()
    with pytest.raises(SystemExit):
        _run(mod)
    with pytest.raises(SystemExit):
        _run(mod, "--remove")
    with acc_session() as s:
        assert s.query(Tenant).filter_by(slug="demo").count() == 1   # ยังไม่ถูกลบ
    assert _real_intact(real_id)


def test_remove_deletes_demo_and_its_files(demo):
    from app.accounts import Account, Tenant, acc_session
    mod, real_id, tmp = demo
    _run(mod, "--password", "Demo!2569")
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    _run(mod, "--remove")
    with acc_session() as s:
        assert s.query(Tenant).filter_by(slug="demo").count() == 0
        assert s.query(Account).filter_by(username="demo").count() == 0
        assert s.query(Tenant).filter_by(slug="real").count() == 1
    assert not (tmp / "schools" / str(tid)).exists()
    assert _real_intact(real_id)


def test_demo_pages_and_documents_work(demo):
    """ล็อกอินด้วยไอดีสาธิตจริง แล้วทุกหน้าที่จะถ่ายต้องเปิดได้ และออกเอกสารได้"""
    from fastapi.testclient import TestClient

    from app.accounts import Tenant, acc_session
    from app.main import app
    from app.models import AssetDisposal, Procurement
    from app.tenancy import session_for
    mod, _real_id, _tmp = demo
    _run(mod, "--password", "Demo!2569")

    c = TestClient(app)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"},
               follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    # ต้องเข้าเป็นโรงเรียนสาธิตจริง ๆ ไม่ใช่ tenant ที่เทสไฟล์อื่นค้างไว้
    assert c.get("/assets").status_code == 200

    for url in ["/assets", "/assets/audit", "/assets/disposal", "/materials",
                "/requisitions", "/procurement", "/procurement/plan"]:
        assert c.get(url).status_code == 200, url

    db = session_for(tid)
    did = db.query(AssetDisposal).one().id
    pid = db.query(Procurement).order_by(Procurement.id).first().id
    db.close()
    for url in [f"/assets/disposal/{did}", f"/assets/disposal/{did}/bundle/all.docx",
                f"/procurement/{pid}", f"/procurement/{pid}/bundle"]:
        rr = c.get(url)
        assert rr.status_code == 200 and len(rr.content) > 10000, url
