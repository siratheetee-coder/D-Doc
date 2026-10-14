# -*- coding: utf-8 -*-
"""แนะนำเพื่อน: ลิงก์ /r/<รหัส> หรือกรอกรหัสตอนสมัคร
เพื่อนจ่ายเงินครั้งแรก -> ได้ใช้ฟรีเพิ่มทั้งคู่ (ผู้แนะนำยังไม่จ่าย = เก็บไว้ ได้ตอนจ่ายเอง)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_referral.py
"""
from datetime import date, timedelta

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
def anon(env):
    from fastapi.testclient import TestClient
    from app.main import app
    return lambda: TestClient(app, raise_server_exceptions=False)


def _demo_tid():
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.query(Tenant).filter_by(slug="demo").one().id
    finally:
        db.close()


def _set(tid, **kw):
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        t = db.get(Tenant, tid)
        for k, v in kw.items():
            setattr(t, k, v)
        db.commit()
    finally:
        db.close()


def _get(tid):
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.get(Tenant, tid)
    finally:
        db.close()


def _register(c, email, school, **extra):
    data = {"email": email, "password": "Tesla8812x", "school_name": school, "accept_policy": "1",
            "heard_from": "เพื่อนครูแนะนำ"}
    data.update(extra)
    c.post("/register", data=data)
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.query(Tenant).filter_by(name=school).one().id
    finally:
        db.close()


def test_owner_page_link_code_and_qr(env, anon):
    html = env.get("/referral").text
    from app.services import referral as rf
    code = rf.code_for(_demo_tid())
    assert len(code) == 6 and code == rf.code_for(_demo_tid()), "รหัสเดิมตลอด"
    assert f"/r/{code}" in html and code in html and "ส่งทาง LINE" in html
    r = env.get("/referral/qr.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert anon().get("/referral", follow_redirects=False).status_code in (302, 303)


def test_invite_link_shows_on_landing_and_register(env, anon):
    from app.services import referral as rf
    code = rf.code_for(_demo_tid())
    c = anon()
    r = c.get(f"/r/{code}", follow_redirects=False)
    assert r.headers["location"] == "/landing" and rf.COOKIE in r.headers.get("set-cookie", "")
    assert "ชวนท่านมาใช้ Easy Ekkasan" in c.get("/landing").text
    page = c.get("/register").text
    assert f'value="{code}"' in page and "ได้รับคำแนะนำจาก" in page
    assert 'class="src-chip on" role="radio"\n            aria-checked="true" data-v="เพื่อนครูแนะนำ"' in page
    bad = anon()
    assert rf.COOKIE not in bad.get("/r/ZZZZZZ", follow_redirects=False).headers.get("set-cookie", "")


def test_friend_pays_both_get_bonus_once(env, anon):
    from app.accounts import acc_session, Lead, Referral, renew_lead
    from app.services import referral as rf
    boss = _demo_tid()
    _set(boss, plan="member", expiry_date=date.today() + timedelta(days=100))
    c = anon()
    c.get(f"/r/{rf.code_for(boss)}")
    friend = _register(c, "friend@example.com", "โรงเรียนเพื่อน")
    assert _get(friend).referred_by == boss
    db = acc_session()
    try:
        lead = Lead(kind="order", email="friend@example.com", tenant_id=friend, modules="", packages="ครบทุกงาน")
        db.add(lead); db.commit(); lid = lead.id
    finally:
        db.close()
    trial_end = _get(friend).expiry_date            # ต่ออายุนับต่อจากวันทดลองที่เหลือ (กติกาเดิม)
    renew_lead(lid)
    days = rf.bonus_days()
    assert _get(friend).expiry_date == trial_end + timedelta(days=365 + days)
    assert _get(boss).expiry_date == date.today() + timedelta(days=100 + days)
    renew_lead(lid)                       # ต่ออายุรอบสอง ไม่ได้รางวัลซ้ำ
    assert _get(boss).expiry_date == date.today() + timedelta(days=100 + days)
    db = acc_session()
    try:
        r = db.query(Referral).one()
        assert r.paid_at and r.referred_bonus_at and r.referrer_bonus_at and r.bonus_days == days
    finally:
        db.close()
    html = env.get("/referral").text
    assert "โรงเรียนเพื่อน" in html and f"ได้รับ {days} วันแล้ว" in html


def test_trial_referrer_gets_bonus_when_they_pay(env, anon):
    from app.services import referral as rf
    boss = _demo_tid()
    _set(boss, plan="trial", expiry_date=date.today() + timedelta(days=10))
    friend = _register(anon(), "f2@example.com", "โรงเรียนสอง", invite_code=rf.code_for(boss).lower())
    _set(friend, plan="member", expiry_date=date.today() + timedelta(days=365))
    out = rf.on_paid(friend)
    assert out["pending"] == rf.bonus_days() and _get(boss).expiry_date == date.today() + timedelta(days=10)
    assert "รอรับ" in env.get("/referral").text
    _set(boss, plan="member", expiry_date=date.today() + timedelta(days=365))
    assert rf.on_paid(boss)["referrer"] == rf.bonus_days()
    assert _get(boss).expiry_date == date.today() + timedelta(days=365 + rf.bonus_days())
    assert rf.on_paid(boss)["referrer"] == 0, "ให้ครั้งเดียว"


def test_no_self_or_sandbox_referral(env, anon):
    from app.services import referral as rf
    boss = _demo_tid()
    assert rf.link(boss, rf.code_for(boss)) is False
    c = anon()
    c.post("/sandbox/start")
    assert "ใช้ได้หลังสมัคร" in c.get("/referral").text
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        sbx = db.query(Tenant).filter(Tenant.plan == "sandbox").one()
        sbx.ref_code = "SBXSBX"; db.commit()
    finally:
        db.close()
    assert rf.referrer_by_code("SBXSBX") is None
    friend = _register(anon(), "f3@example.com", "โรงเรียนสาม", invite_code="NOPE99")
    assert _get(friend).referred_by is None
