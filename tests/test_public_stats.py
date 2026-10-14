# -*- coding: utf-8 -*-
"""ตัวเลขจริงบนหน้า landing: "ใช้งานไปแล้ว ... ครั้ง จากทั้งหมด ... โรงเรียน"

นับเฉพาะโรงเรียนจริง (ไม่รวมระบบตัวอย่าง/โรงเรียนสาธิต/ที่ถูกระงับ) · คิดวันละครั้ง
ยอดไม่ลดเมื่อข้อมูลรายวันเกิน 90 วันถูกลบ · โรงเรียนน้อยกว่าเกณฑ์ = ไม่แสดง
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_public_stats.py
"""
from datetime import date, timedelta

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)


@pytest.fixture()
def data(env, monkeypatch):
    import app.services.public_stats as ps
    monkeypatch.setattr(ps, "_cache", {})
    from app.accounts import acc_session, Tenant, UsageDay
    db = acc_session()
    try:
        demo = db.query(Tenant).filter_by(slug="demo").one()
        db.add(UsageDay(tenant_id=demo.id, uid=1, day=date.today().isoformat(), hits=999, docs=99))
        for i in range(3):
            t = Tenant(name=f"จริง{i}", slug=f"real{i}", plan="member", active=True)
            db.add(t); db.flush()
            db.add(UsageDay(tenant_id=t.id, uid=1, day=date.today().isoformat(), hits=100, docs=10))
        off = Tenant(name="ระงับ", slug="off", plan="member", active=False)
        sbx = Tenant(name="ตัวอย่าง", slug="sandbox-1", plan="sandbox", active=True)
        db.add_all([off, sbx]); db.flush()
        db.add(UsageDay(tenant_id=sbx.id, uid=1, day=date.today().isoformat(), hits=5000, docs=500))
        db.commit()
    finally:
        db.close()
    return ps


def test_counts_only_real_schools(data):
    s = data.compute()
    assert (s["schools"], s["hits"], s["docs"]) == (3, 300, 30)


def test_landing_shows_numbers_once_threshold_met(data, env, monkeypatch):
    from app.seller_config import SELLER
    monkeypatch.setitem(SELLER, "landing_stats_min_schools", 3)
    html = env.get("/landing").text
    assert "ข้อมูลจริงจากระบบ" in html and "ใช้งานไปแล้ว <b>300</b> ครั้ง" in html
    assert "จากทั้งหมด <b>3</b> โรงเรียน" in html and "ออกเอกสารแล้ว <b>30</b> ฉบับ" in html


def test_hidden_below_threshold_and_cached_per_day(data, env, monkeypatch):
    from app.seller_config import SELLER
    monkeypatch.setitem(SELLER, "landing_stats_min_schools", 4)
    assert data.landing_stats() is None
    assert "ข้อมูลจริงจากระบบ" not in env.get("/landing").text
    monkeypatch.setitem(SELLER, "landing_stats_min_schools", 3)
    assert data.landing_stats() is None, "วันเดียวกันใช้ค่าที่คิดไว้แล้ว ไม่คิดใหม่ทุกครั้งที่เปิดหน้า"
    assert data.landing_stats(date.today() + timedelta(days=1))["hits"] == 300, "ขึ้นวันใหม่คิดใหม่"


def test_totals_survive_daily_purge(data):
    import app.usage as usage
    from app.accounts import acc_session, Tenant, UsageDay
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(slug="real0").one()
        old = (date.today() - timedelta(days=usage.RETENTION_DAYS + 5)).isoformat()
        db.add(UsageDay(tenant_id=t.id, uid=1, day=old, hits=40, docs=4))
        db.commit()
        uid_key = (t.id, 1, date.today().isoformat())
    finally:
        db.close()
    assert data.compute()["hits"] == 340
    usage._last_purge = ""
    usage.record(uid_key[0], {"uid": 1, "username": "x"}, None, "GET")
    usage.flush()
    db = acc_session()
    try:
        assert db.query(UsageDay).filter(UsageDay.day < date.today().isoformat()).count() == 0, "แถวเก่าถูกลบ"
    finally:
        db.close()
    s = data.compute()
    assert (s["hits"], s["docs"]) == (341, 34), "ยอดเก่ารวมเข้ายอดสะสมแล้ว ไม่หายไปพร้อมการลบ"
    usage._last_purge = ""
    usage.record(uid_key[0], {"uid": 1, "username": "x"}, None, "GET")
    usage.flush()
    assert data.compute()["hits"] == 342, "ล้างรอบสองไม่นับซ้ำ"


def test_console_preview(data, env):
    from app.accounts import acc_session, Account, hash_password
    db = acc_session()
    try:
        db.add(Account(username="boss2", password_hash=hash_password("Boss2569xyz"), role="superadmin"))
        db.commit()
    finally:
        db.close()
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    c.post("/login", data={"username": "boss2", "password": "Boss2569xyz"})
    html = c.get("/admin-console/marketing").text
    assert "ตัวเลขบนหน้า landing" in html and "ยังไม่แสดง" in html and "<b>300</b>" in html
