# -*- coding: utf-8 -*-
"""หน้าแจ้งข้อผิดพลาดต้องเป็นภาษาไทยที่ผู้ใช้อ่านรู้เรื่อง ไม่ใช่ {"detail":"Not Found"}

กติกาที่ต้องถูก
  - เปิดหน้าที่ไม่มีจากเบราว์เซอร์ -> หน้าเว็บภาษาไทย + ปุ่มกลับหน้าแรก
  - ข้อความเฉพาะเรื่องที่ระบบเขียนไว้ (เช่น ไม่พบสำนวนจำหน่ายพัสดุนี้) ต้องยังขึ้นให้เห็น
  - fetch/JS ต้องได้ JSON เหมือนเดิม ไม่งั้นหน้าที่เรียกเบื้องหลังจะพังทั้งระบบ
รัน: .venv\Scripts\python.exe -m pytest tests/test_error_pages.py
"""
import importlib.util
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BROWSER = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


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
    for key in ("tenant_state", "can_use_module", "get_account_access"):
        monkeypatch.setattr(main_mod, key, getattr(ac, key))

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    return c


def test_missing_page_is_thai_html_for_a_browser(client):
    r = client.get("/ไม่มีหน้านี้แน่นอน", headers=BROWSER)
    assert r.status_code == 404
    assert r.text.lstrip().startswith("<!doctype")
    assert "ไม่พบหน้าที่เรียก" in r.text
    assert "กลับหน้าแรก" in r.text
    assert '"detail"' not in r.text


def test_specific_thai_message_is_kept(client):
    """ข้อความที่เราเขียนไว้เองต้องไม่ถูกกลืนด้วยข้อความกลาง"""
    r = client.get("/assets/disposal/999999", headers=BROWSER)
    assert r.status_code == 404
    assert "ไม่พบสำนวนจำหน่ายพัสดุนี้" in r.text


def test_no_permission_page_explains_in_thai(client):
    """กันสิทธิ์แล้วต้องได้หน้าเว็บภาษาไทยที่มีทางไปต่อ ไม่ใช่ JSON"""
    r = client.get("/admin-console", headers=BROWSER)
    assert r.status_code == 403
    assert r.text.lstrip().startswith("<!doctype")
    assert "ผู้ดูแล" in r.text and "</a>" in r.text
    assert chr(34) + "detail" + chr(34) not in r.text


def test_fetch_still_gets_json(client):
    """หน้าที่เรียกข้อมูลเบื้องหลังยังต้องได้ JSON ไม่ใช่หน้าเว็บ"""
    r = client.get("/ไม่มีหน้านี้แน่นอน")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not Found"
