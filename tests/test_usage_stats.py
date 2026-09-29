# -*- coding: utf-8 -*-
"""สถิติการใช้งานในคอนโซลเจ้าของระบบต้องบันทึกจริง

บั๊กที่เคยเจอจริง
  get_account_access() ไม่ได้คืนคีย์ uid/username กลับมา แต่ usage.record()
  อ่าน acc["uid"] เป็นเงื่อนไขแรก พอไม่มีก็ return ทิ้งทุก request
  -> ตาราง usage_day ว่างเปล่าทั้งระบบ คอนโซลจึงไม่เห็นการใช้งานของใครเลย
  (เงียบสนิท เพราะ middleware ห่อ record() ไว้ใน try/except)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_usage_stats.py
"""
import importlib.util
import pathlib
import sys
import tempfile
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    import app.main as main_mod
    import app.routers.auth as auth_mod
    monkeypatch.setattr(auth_mod, "authenticate", ac.authenticate)
    monkeypatch.setattr(main_mod, "tenant_state", ac.tenant_state)
    monkeypatch.setattr(main_mod, "can_use_module", ac.can_use_module)
    monkeypatch.setattr(main_mod, "get_account_access", ac.get_account_access)

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    import app.usage as usage
    monkeypatch.setattr(usage, "_buf", {})

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"},
               follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    return c


def test_account_access_carries_identity():
    """คีย์ที่ usage.record() ต้องใช้ ต้องมีครบ ไม่งั้นสถิติจะว่างทั้งระบบ"""
    import inspect

    from app.accounts import get_account_access
    src = inspect.getsource(get_account_access)
    for key in ("uid", "username", "display_name"):
        assert f'"{key}"' in src, f"get_account_access ไม่ได้คืน {key}"


def test_browsing_records_usage_for_the_tenant(client):
    """เปิดหน้าใช้งานจริง -> มีแถวสรุปของโรงเรียน+ไอดีนั้นในตาราง usage_day"""
    from app.accounts import UsageDay, acc_session
    from app.usage import flush

    client.get("/procurement")
    client.get("/finance/accounts")
    assert flush() > 0, "ไม่มีอะไรถูกบันทึกเลย - record() ถูกข้ามทุก request"

    db = acc_session()
    try:
        rows = db.query(UsageDay).filter_by(day=date.today().isoformat()).all()
        assert rows, "ตาราง usage_day ว่าง"
        r = rows[0]
        assert r.tenant_id and r.uid, (r.tenant_id, r.uid)
        assert r.username == "demo", r.username
        assert r.hits >= 2, r.hits
        assert "พัสดุ" in (r.modules or "") or "procurement" in (r.modules or ""), r.modules
    finally:
        db.close()


def test_console_summary_sees_that_tenant(client):
    """สรุปที่คอนโซลใช้ ต้องเห็นโรงเรียนนั้น (ไม่ใช่เห็นแต่ของตัวเอง)"""
    from app.accounts import acc_session
    from app.usage import flush, range_bounds, summary_for_range

    client.get("/assets")
    flush()
    db = acc_session()
    try:
        start, end = range_bounds(1)
        out = summary_for_range(db, start, end)
        assert out["totals"]["schools"] >= 1, out["totals"]
        assert out["schools"], "คอนโซลไม่เห็นโรงเรียนที่เพิ่งใช้งาน"
        sc = out["schools"][0]
        assert sc["n_users"] >= 1 and sc["hits"] >= 1
        assert any(u["username"] == "demo" for u in sc["users"]), sc["users"]
    finally:
        db.close()


def test_write_and_doc_counts_are_separated(client):
    """แยกได้ว่าเป็นการบันทึกข้อมูล (POST) กี่ครั้ง และออกเอกสารกี่ฉบับ"""
    from app.accounts import UsageDay, acc_session
    from app.usage import flush

    client.post("/finance/accounts", data={"name": "ทดสอบสถิติ", "opening_balance": "0"},
                follow_redirects=False)
    client.get("/register.xlsx")
    flush()
    db = acc_session()
    try:
        r = db.query(UsageDay).filter_by(day=date.today().isoformat()).first()
        assert r.writes >= 1, f"ไม่ได้นับการบันทึกข้อมูล: {r.writes}"
        assert r.docs >= 1, f"ไม่ได้นับเอกสารที่ออก: {r.docs}"
    finally:
        db.close()
