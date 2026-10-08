# -*- coding: utf-8 -*-
"""หน้าขอใบเสนอราคา: เลือกแพ็กเกจในหน้านี้ได้เลย และบอกราคาทันที

เดิมเป็นช่องพิมพ์ชื่อแพ็กเกจเอง ยอดเงินอ่านอย่างเดียว และมีช่อง "จำนวนโรงเรียน"
ที่ไม่ได้ใช้คิดราคา (ขายรายโรงเรียน) ผู้ใช้ที่เข้ามาตรง ๆ จึงไม่รู้ว่าต้องพิมพ์อะไรและราคาเท่าไร
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_quote_page.py
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules import MODULE_KEYS
from app.seller_config import price_for

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    return TestClient(app)


def _amount(html) -> str:
    m = re.search(r'id="coAmount">([^<]*)<', html)
    return (m.group(1) if m else "").replace(",", "")


def _label(html) -> str:
    m = re.search(r'id="coPackages" value="([^"]*)"', html)
    return m.group(1) if m else ""


def test_every_module_is_a_choice_with_its_own_price(client):
    r = client.get("/quote")
    assert r.status_code == 200
    for k in MODULE_KEYS:
        assert f'value="{k}"' in r.text, f"ไม่มีตัวเลือก {k}"
    assert 'name="mod"' in r.text, "ยังไม่ได้ให้เลือกแพ็กเกจในหน้านี้"


def test_price_shown_matches_the_server_formula(client):
    for mods in (["procurement"], ["procurement", "finance"],
                 ["procurement", "finance", "admin"], MODULE_KEYS):
        q = "&".join(f"mod={m}" for m in mods)
        html = client.get(f"/quote?{q}").text
        want = price_for(set(mods))
        assert _amount(html) == str(want["total"]), (mods, _amount(html), want["total"])
        assert _label(html) == want["label"], (mods, _label(html))


def test_bundle_price_is_used_when_everything_is_selected(client):
    html = client.get("/quote?" + "&".join(f"mod={m}" for m in MODULE_KEYS)).text
    assert _label(html) == "ครบทุกงาน"
    assert _amount(html) == str(price_for(set(MODULE_KEYS))["total"])


def test_the_school_count_field_is_gone(client):
    """ขายรายโรงเรียน ช่องนี้ไม่ได้ใช้คิดราคา และทำให้ผู้ใช้สับสน"""
    assert "จำนวนโรงเรียน" not in client.get("/quote").text
    assert "qty_school" not in (ROOT / "app/routers/sales.py").read_text(encoding="utf-8")
    assert "qty_school" not in (ROOT / "app/templates/quote.html").read_text(encoding="utf-8")


def test_links_from_the_order_page_still_preselect_the_right_packages(client):
    """หน้าสั่งซื้อส่งมาเป็นข้อความ packages ไม่ใช่ mod ต้องยังติ๊กให้ถูก"""
    html = client.get("/quote?packages=" + "งานพัสดุ + งานการเงิน").text
    assert _label(html) == "งานพัสดุ + งานการเงิน"
    assert _amount(html) == str(price_for({"procurement", "finance"})["total"])


def test_submitting_without_a_package_is_rejected(client):
    r = client.post("/quote", data={"school_name": "โรงเรียนทดสอบ", "contact_name": "ผู้ทดสอบ",
                                    "email": "a@b.co"}, follow_redirects=False)
    assert r.status_code == 400
    assert "กรุณาเลือกงานที่ต้องการ" in r.text
    # หน้าที่ตีกลับต้องยังมีตัวเลือกให้เลือกต่อ และคงข้อมูลที่กรอกไว้
    assert 'name="mod"' in r.text and "โรงเรียนทดสอบ" in r.text


def test_server_ignores_the_amount_sent_from_the_browser(monkeypatch, client):
    """ราคาต้องมาจาก price_for เสมอ ห้ามเชื่อยอดที่ส่งมาจากหน้าเว็บ"""
    seen = {}

    import app.routers.sales as sales

    def _fake_add_lead(**kw):
        seen.update(kw)
        return 999

    monkeypatch.setattr(sales, "add_lead", _fake_add_lead)
    monkeypatch.setattr(sales, "send_order_notice", lambda *a, **k: None, raising=False)
    r = client.post("/quote", data={"school_name": "โรงเรียนทดสอบ", "contact_name": "ผู้ทดสอบ",
                                    "email": "a@b.co", "mod": ["procurement"],
                                    "amount": "1"}, follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    assert seen["amount"] == float(price_for({"procurement"})["total"]), seen["amount"]
    assert seen["packages"] == "งานพัสดุ"
