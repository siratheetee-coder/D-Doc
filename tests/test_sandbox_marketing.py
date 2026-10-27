# -*- coding: utf-8 -*-
"""ทดลองใช้ระบบตัวอย่าง (ไม่ต้องสมัคร) + รู้จักเราจากไหน / ลิงก์ที่มา / หน้าสรุปในคอนโซล

ระบบตัวอย่าง: ได้โรงเรียนสมมติของตัวเอง แยกฐานข้อมูล ลบเองใน 24 ชม.
ปิดบัญชีผู้ใช้/รหัสผ่าน/อีเมล/AI · ไปหน้าสมัครแล้วออกจากระบบตัวอย่างเอง
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_sandbox_marketing.py
"""
from datetime import datetime, timedelta

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _no_signup_guard(monkeypatch):
    """ด่านกันสแปมตอนสมัคร (อีเมลตัวอย่าง/สมัครถี่) มีเทสต์ของตัวเองใน test_signup_guard.py
    ที่นี่ทดสอบเรื่องอื่น จึงปิดด่านไว้ (และไม่ให้ไปถามโดเมนอีเมลจริงทางเน็ต)"""
    import app.services.signup_guard as g
    monkeypatch.setattr(g, "email_problem", lambda email: None)
    monkeypatch.setattr(g, "throttle", lambda request, email: 0)


@pytest.fixture()
def anon(env, monkeypatch):
    """ผู้เยี่ยมชมที่ยังไม่ล็อกอิน (ใช้ฐานข้อมูลชั่วคราวชุดเดียวกับ env)"""
    import app.services.sandbox as sb
    monkeypatch.setattr(sb, "_ip_hits", {})
    monkeypatch.setattr(sb, "_cache", {})
    from fastapi.testclient import TestClient
    from app.main import app

    def make():
        return TestClient(app, raise_server_exceptions=False)
    return make


def _tenant(tid):
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.get(Tenant, tid)
    finally:
        db.close()


def _start(c):
    r = c.post("/sandbox/start", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/", r.headers.get("location")
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return max(t.id for t in db.query(Tenant).filter(Tenant.plan == "sandbox"))
    finally:
        db.close()


def test_landing_has_the_button(anon):
    html = anon().get("/landing").text
    assert 'action="/sandbox/start"' in html and "ทดลองใช้ระบบตัวอย่าง" in html


def test_each_visitor_gets_own_school_with_sample_data(anon):
    from app.models import Person
    from app.tenancy import session_for, school_db_path
    a, b = anon(), anon()
    ta = _start(a)
    tb = _start(b)
    assert ta != tb and school_db_path(ta) != school_db_path(tb)
    home = a.get("/")
    assert home.status_code == 200 and "นี่คือระบบตัวอย่าง" in home.text
    db = session_for(ta)
    try:
        assert db.query(Person).count() > 5, "ข้อมูลโรงเรียนสมมติครบทุกงาน"
        db.add(Person(name="ครูของผู้เยี่ยมชม A")); db.commit()
    finally:
        db.close()
    db = session_for(tb)
    try:
        assert db.query(Person).filter_by(name="ครูของผู้เยี่ยมชม A").count() == 0, "คนละฐานข้อมูล"
    finally:
        db.close()
    from app.accounts import acc_session, SandboxVisit
    db = acc_session()
    try:
        assert db.query(SandboxVisit).count() == 2
    finally:
        db.close()


def test_sandbox_blocks_accounts_mail_and_ai(anon, monkeypatch):
    c = anon()
    tid = _start(c)
    r = c.post("/account/password", data={"current": "x", "new": "Abcdef123", "confirm": "Abcdef123"})
    assert r.status_code == 403 and "ส่วนนี้ปิดไว้ในระบบตัวอย่าง" in r.text
    assert c.post("/users/add", data={"username": "x", "password": "Abcdef123"}).status_code == 403
    assert c.post("/support", data={"message": "hi"}).status_code == 403

    from app.seller_config import SELLER
    monkeypatch.setitem(SELLER, "smtp_host", "smtp.example.com")
    monkeypatch.setitem(SELLER, "smtp_user", "u")
    monkeypatch.setitem(SELLER, "ai_api_key", "sk-test")
    import smtplib

    calls = []

    def fake_smtp(*a, **k):          # send_email กลืน exception จึงต้องจดว่าถูกเรียกไหมแทน
        calls.append(a)
        raise OSError("ไม่ได้ต่อจริง")
    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)
    from app.services.mailer import send_email, send_bulk
    from app.tenancy import current_school_id
    tok = current_school_id.set(tid)
    try:
        assert send_email("someone@example.com", "s", "<p>x</p>") is False
        assert send_bulk([("someone@example.com", "s", "x")]) == (0, 1)
    finally:
        current_school_id.reset(tok)
    assert calls == [], "ระบบตัวอย่างต้องไม่เปิดการเชื่อมต่อส่งอีเมลเลย"
    send_email("someone@example.com", "s", "<p>x</p>")
    assert len(calls) == 1, "โรงเรียนจริง (ไม่อยู่ในระบบตัวอย่าง) ยังส่งอีเมลได้ตามปกติ"
    from app.accounts import ai_key_for
    assert ai_key_for(tid) == ""


def test_going_to_register_leaves_the_sandbox(anon):
    c = anon()
    _start(c)
    r = c.get("/register?from=sandbox", follow_redirects=False)
    assert r.status_code == 200 and "รู้จักเราจากไหน" in r.text
    assert c.get("/", follow_redirects=False).headers["location"].startswith("/landing")


def test_expired_sandbox_is_removed(anon):
    from app.accounts import acc_session, Tenant
    from app.services import sandbox as sb
    from app.tenancy import school_db_path
    c = anon()
    tid = _start(c)
    folder = school_db_path(tid).parent
    db = acc_session()
    try:
        db.get(Tenant, tid).created_at = datetime.now() - timedelta(hours=25)
        db.commit()
    finally:
        db.close()
    assert sb.cleanup() == 1
    assert _tenant(tid) is None and not folder.exists()
    r = c.get("/", follow_redirects=False)
    assert r.headers["location"] == "/landing?sandbox=ended#try"
    assert "ถูกลบแล้ว" in c.get("/landing?sandbox=ended").text


def test_full_or_too_fast_shows_a_message(anon, monkeypatch):
    from app.services import sandbox as sb
    monkeypatch.setattr(sb, "MAX_ACTIVE", 1)
    _start(anon())
    c = anon()
    r = c.post("/sandbox/start", follow_redirects=False)
    assert r.headers["location"] == "/landing#try"
    assert "เต็มแล้ว" in c.get("/landing").text
    monkeypatch.setattr(sb, "MAX_ACTIVE", 100)
    monkeypatch.setattr(sb, "PER_IP_PER_HOUR", 0)
    assert "error" in sb.create(ip="1.2.3.4")


def test_register_records_source_link_and_sandbox(anon):
    from app.accounts import acc_session, Tenant
    c = anon()
    r = c.get("/landing?ref=fb-กลุ่มครูพัสดุ")
    assert r.status_code == 200
    _start(c)
    page = c.get("/register").text
    from app.services.marketing import SOURCES
    for s in SOURCES:
        assert f'data-v="{s}"' in page
    c.post("/register", data={"email": "kru@example.com", "password": "Tesla8812x", "school_name": "โรงเรียนทดสอบ",
                              "accept_policy": "1", "heard_from": "อื่น ๆ", "heard_other": "  งานอบรม  เขต 1 "})
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(name="โรงเรียนทดสอบ").one()
        assert t.signup_source == "อื่น ๆ: งานอบรม เขต 1"
        assert t.signup_ref == "fb-กลุ่มครูพัสดุ" and t.from_sandbox is True
    finally:
        db.close()
    anon().post("/register", data={"email": "kru2@example.com", "password": "Tesla8812x", "school_name": "โรงเรียนสอง",
                                   "accept_policy": "1", "heard_from": "แฮก"})
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(name="โรงเรียนสอง").one()
        assert t.signup_source == "" and t.signup_ref == "" and not t.from_sandbox
    finally:
        db.close()


def test_marketing_summary_and_console(anon):
    from app.accounts import acc_session, Tenant, Account, UsageDay, SandboxVisit, hash_password
    from app.services import marketing as mk
    db = acc_session()
    try:
        def school(name, src="", ref="", plan="trial", docs=0, sbx=False):
            t = Tenant(name=name, slug=name, plan=plan, signup_source=src, signup_ref=ref, from_sandbox=sbx)
            db.add(t); db.flush()
            db.add(Account(tenant_id=t.id, username=name + "@x.com", password_hash="x", is_owner=True, verified=True))
            if docs:
                db.add(UsageDay(tenant_id=t.id, uid=1, day="2026-10-01", docs=docs))
        school("a", "Facebook", "fb-1", plan="member", docs=3, sbx=True)
        school("b", "Facebook", "fb-1")
        school("c", "LINE", docs=1)
        school("d", "อื่น ๆ: งานอบรม")
        db.add(Tenant(name="ตัวอย่าง", slug="sandbox-x", plan="sandbox"))
        db.add(SandboxVisit(ref="fb-1")); db.add(SandboxVisit(ref=""))
        db.add(Account(username="boss", password_hash=hash_password("Boss2569xyz"), role="superadmin"))
        db.commit()
    finally:
        db.close()
    s = mk.summary(days=0)
    fb = next(r for r in s["sources"] if r["label"] == "Facebook")
    assert (fb["signup"], fb["used"], fb["paid"], fb["rate"], fb["sandbox"]) == (2, 1, 1, 50, 1)
    assert next(r for r in s["sources"] if r["label"] == "อื่น ๆ")["signup"] == 1 and s["others"] == ["งานอบรม"]
    ref = next(r for r in s["refs"] if r["label"] == "fb-1")
    assert (ref["visits"], ref["signup"], ref["paid"]) == (1, 2, 1)
    assert s["visits"] == 2 and s["after_sandbox"] == 1
    assert all(r["label"] != "ตัวอย่าง" for r in s["sources"])
    c = anon()
    c.post("/login", data={"username": "boss", "password": "Boss2569xyz"})
    html = c.get("/admin-console/marketing?days=0").text
    assert "รู้จักเราจากไหน" in html and "fb-1" in html and "งานอบรม" in html
    assert "sandbox-x" not in c.get("/admin-console").text


def test_sandbox_can_chat_with_staff_and_purge_clears_it(anon):
    """ผู้ทดลองใช้ทักแชทถามเจ้าหน้าที่ได้ และแชทถูกลบพร้อมระบบตัวอย่าง"""
    from app.accounts import acc_session, purge_tenant, SupportMessage
    from app.services.sandbox import blocked
    c = anon()
    tid = _start(c)
    assert not blocked("/support/chat/send", "POST") and blocked("/support", "POST")
    assert c.post("/support/chat/send", data={"body": "สนใจสมัครครับ", "nonce": "sbx"}).status_code == 200
    db = acc_session()
    try:
        assert db.query(SupportMessage).filter_by(tenant_id=tid).count() == 1
    finally:
        db.close()
    purge_tenant(tid)
    db = acc_session()
    try:
        assert db.query(SupportMessage).filter_by(tenant_id=tid).count() == 0
    finally:
        db.close()
