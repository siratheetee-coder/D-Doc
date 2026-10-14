# -*- coding: utf-8 -*-
"""กันสแปมสมัคร + ล้างการสมัครที่ไม่ยืนยันอีเมล + อีเมลตามผู้ทดลองใช้

บอท (ไม่มีโทเคน / ส่งเร็วเกิน / กรอกช่องล่อ): ตอบเหมือนสำเร็จ แต่ไม่บันทึก ไม่ส่งอีเมล ไม่แจ้งเจ้าของ
สมัครแล้วไม่ยืนยันอีเมลเกิน 3 วัน: ลบโรงเรียน + คำขอทดลองใช้ (เฉพาะ trial ที่ไม่มีใครยืนยันเลย)
อีเมลแนะนำ: ตามความคืบหน้าจริง ไม่ส่งซ้ำ ไม่ส่งย้อนหลัง เลิกรับได้
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_spam_and_nurture.py
"""
import re
import time
from datetime import date, datetime, timedelta

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)


@pytest.fixture()
def guard(env, monkeypatch):
    import app.services.form_guard as fg
    import app.services.signup_guard as sg
    monkeypatch.setattr(fg, "ENABLED", True)
    monkeypatch.setattr(sg, "email_problem", lambda email: None)
    monkeypatch.setattr(sg, "throttle", lambda request, email: 0)
    import app.services.mailer as mailer
    sent = []
    monkeypatch.setattr(mailer, "send_verify_email", lambda to, link: sent.append(("verify", to)) or True)
    monkeypatch.setattr(mailer, "send_order_notice", lambda *a, **k: sent.append(("owner", a)) or True)
    from fastapi.testclient import TestClient
    from app.main import app
    return fg, TestClient(app), sent


def _tenant_named(name):
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.query(Tenant).filter_by(name=name).first()
    finally:
        db.close()


def _signup(c, fg, school, ft, website=""):
    return c.post("/register", data={"email": f"{abs(hash(school)) % 10**8}@school.ac.th", "password": "Tesla8812x",
                                     "school_name": school, "accept_policy": "1", "heard_from": "LINE",
                                     "ft": ft, "website": website})


def test_forms_carry_token_and_hidden_trap(guard):
    fg, c, _ = guard
    for url in ("/register", "/quote"):
        html = c.get(url).text
        assert 'name="ft" value="' in html and 'name="website"' in html and 'aria-hidden="true"' in html, url


def test_bots_get_fake_success_and_nothing_happens(guard):
    fg, c, sent = guard
    old = fg.token(time.time() - 30)
    cases = {"ไม่มีโทเคน": "", "ส่งเร็วเกิน": fg.token(), "ปลอมลายเซ็น": old[:-4] + "abcd",
             "โทเคนเก่าเกิน": fg.token(time.time() - fg.MAX_AGE - 60)}
    for school, ft in cases.items():
        r = _signup(c, fg, school, ft)
        assert r.status_code == 200 and "ยืนยัน" in r.text, school
        assert _tenant_named(school) is None, school
    r = _signup(c, fg, "กรอกช่องล่อ", old, website="http://spam.example")
    assert _tenant_named("กรอกช่องล่อ") is None
    assert sent == [], "บอทไม่ทำให้ส่งอีเมลใด ๆ"
    from app.accounts import acc_session, AuditLog
    db = acc_session()
    try:
        assert db.query(AuditLog).filter_by(action="bot.blocked").count() == 5
    finally:
        db.close()
    _signup(c, fg, "คนจริง", old)
    assert _tenant_named("คนจริง") is not None and sent and sent[0][0] == "verify"


def test_quote_and_resend_bots_do_not_notify(guard):
    fg, c, sent = guard
    from app.accounts import acc_session, Lead
    r = c.post("/quote", data={"school_name": "สแปม", "contact_name": "x", "email": "x@school.ac.th",
                               "mod": ["procurement"], "ft": ""}, follow_redirects=False)
    assert r.headers["location"].startswith("/sale-thanks")
    db = acc_session()
    try:
        assert db.query(Lead).filter_by(kind="quote").count() == 0
    finally:
        db.close()
    c.post("/register/resend", data={"email": "x@school.ac.th", "ft": "", "website": ""})
    assert sent == [], "ไม่แจ้งเจ้าของ ไม่ส่งอีเมลยืนยันซ้ำ"
    c.post("/quote", data={"school_name": "จริง", "contact_name": "ครู", "email": "kru@school.ac.th",
                           "mod": ["procurement"], "ft": fg.token(time.time() - 20)})
    assert [k for k, _ in sent] == ["owner"]


def _school(db, name, *, plan="trial", verified=False, age_days=5, email=None):
    from app.accounts import Account, Lead, Tenant
    created = datetime.now() - timedelta(days=age_days)
    t = Tenant(name=name, slug=name, plan=plan, active=True, created_at=created, last_active_at=created,
               expiry_date=created.date() + timedelta(days=30))
    db.add(t); db.flush()
    email = email or f"{name}@school.ac.th"
    db.add(Account(tenant_id=t.id, username=email, password_hash="x", is_owner=True, verified=verified, active=True))
    db.add(Lead(kind="trial", email=email, tenant_id=t.id, school_name=name))
    db.commit()
    return t.id


def test_unverified_signups_are_removed_after_3_days(env):
    from app.accounts import acc_session, Lead, Tenant
    from app.services import signup_cleanup as sc, public_stats as ps
    db = acc_session()
    try:
        spam = _school(db, "spam1", age_days=4)
        fresh = _school(db, "fresh", age_days=1)
        real = _school(db, "real", verified=True, age_days=10)
        paid = _school(db, "paid", plan="member", age_days=10)
    finally:
        db.close()
    db = acc_session()
    try:
        before = ps.ever_registered(db)
    finally:
        db.close()
    assert sc.spam_status()["pending"] == 2
    assert sc.purge_unverified(dry_run=True) == 1 and _tenant_named("spam1")
    assert sc.purge_unverified() == 1
    db = acc_session()
    try:
        assert db.get(Tenant, spam) is None and db.query(Lead).filter_by(tenant_id=spam).count() == 0
        for keep in (fresh, real, paid):
            assert db.get(Tenant, keep) is not None
        assert ps.ever_registered(db) == before, "รอยืนยันอีเมลอยู่ไม่ถูกนับตั้งแต่แรก"
    finally:
        db.close()


def test_decide_follows_progress():
    from app.services.trial_nurture import decide
    none, used = {"docs": 0, "modules": set()}, {"docs": 4, "modules": {"procurement"}}
    assert decide(0, 0, none, 0) == (0, None)
    assert decide(0, 2, none, 0) == (1, "first_doc")
    assert decide(0, 2, used, 0) == (1, None)
    assert decide(1, 6, none, 0) == (2, "need_help")
    assert decide(1, 6, used, 0) == (2, "try_more")
    assert decide(0, 10, none, 0) == (2, None), "พ้นช่วงขั้น 2 แล้ว ไม่ส่งย้อนหลัง"
    assert decide(2, 14, used, 7) == (3, "come_back")
    assert decide(2, 14, used, 1) == (3, None)
    assert decide(3, 15, none, 9) == (0, None)


def test_nurture_run_sends_once_and_respects_stop(env, monkeypatch):
    import app.services.mailer as mailer
    from app.accounts import acc_session, Tenant, UsageDay
    from app.services import trial_nurture as tn
    mails = []
    monkeypatch.setattr(mailer, "smtp_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, html, **k: mails.append((to, subject, html)) or True)
    db = acc_session()
    try:
        new = _school(db, "new", verified=True, age_days=2)
        busy = _school(db, "busy", verified=True, age_days=6)
        db.add(UsageDay(tenant_id=busy, uid=1, day=date.today().isoformat(), docs=7,
                        modules='{"procurement": 12}'))
        _school(db, "noverify", verified=False, age_days=2)
        _school(db, "member", plan="member", verified=True, age_days=2)
        late = _school(db, "late", verified=True, age_days=14)     # อยู่ในช่วงขั้น 3 และไม่ได้เข้าระบบ...
        db.get(Tenant, late).expiry_date = date.today() + timedelta(days=3)   # ...แต่เหลือ 3 วัน = ช่วงของ trial_notice
        db.get(Tenant, late).nurture_stage = 2
        db.commit()
    finally:
        db.close()
    tn.run(verbose=False)
    got = {to.split("@")[0]: (subj, html) for to, subj, html in mails}
    assert set(got) == {"new", "busy"}
    assert "3 ขั้น" in got["new"][0]
    assert "7 ฉบับ" in got["busy"][0] and "งานการเงิน" in got["busy"][1] and "งานพัสดุ" not in got["busy"][1]
    link = re.search(r'href="[^"]*(/email/stop\?t=[^"]+)"', got["new"][1]).group(1)
    mails.clear()
    tn.run(verbose=False)
    assert mails == [], "ไม่ส่งซ้ำ"
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert "ยกเลิกรับอีเมลแนะนำการใช้งานแล้ว" in c.get(link).text
    assert "ลิงก์ไม่ถูกต้อง" in c.get("/email/stop?t=1.forged").text
    db = acc_session()
    try:
        assert db.get(Tenant, new).nurture_stage == tn.STOPPED
        t = db.get(Tenant, new)
        t.created_at = datetime.now() - timedelta(days=6)              # ถึงขั้น 2 แต่เลิกรับแล้ว
        db.commit()
    finally:
        db.close()
    tn.run(verbose=False)
    assert all(not to.startswith("new@") for to, _, _ in mails)


def test_signup_check_survives_missing_dnspython(monkeypatch):
    """เคยพังจริง: เซิร์ฟเวอร์ยังไม่ได้ติดตั้ง dnspython -> สมัครทุกครั้งขึ้น 500
    ต้องข้ามแค่การตรวจ MX ส่วนการตรวจอื่นยังทำงาน"""
    import sys
    monkeypatch.setitem(sys.modules, "dns", None)
    monkeypatch.setitem(sys.modules, "dns.resolver", None)
    monkeypatch.setitem(sys.modules, "dns.exception", None)
    from app.services.signup_guard import email_problem
    assert email_problem("kru@school.ac.th") is None
    assert email_problem("kru@example.com"), "ยังกันอีเมลตัวอย่างได้"
    assert email_problem("not-an-email"), "ยังตรวจรูปแบบอีเมลได้"


def test_unverified_signups_are_never_deleted_automatically():
    """เจ้าของสั่ง (2026-10-14): ส่วนใหญ่เป็นครูจริงที่ยังไม่ได้กดยืนยัน ห้ามลบเอง
    ลบได้เฉพาะสั่งด้วยมือพร้อม --confirm"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for f in ("main.py", "services/trial_notice.py"):
        assert "purge_unverified" not in (root / f).read_text(encoding="utf-8"), f
    src = (root / "services/signup_cleanup.py").read_text(encoding="utf-8")
    assert 'dry_run="--confirm" not in sys.argv' in src


def test_restore_deleted_schools_from_backup(env, tmp_path):
    """กู้เหตุการณ์จริง 2026-10-14: ระบบลบการสมัครที่ไม่ยืนยันอีเมล 20 แห่งตอนเปิดเซิร์ฟเวอร์
    กู้เฉพาะโรงเรียนที่ถูกลบจากไฟล์สำรอง โดยไม่ทับโรงเรียนอื่น · ชนอีเมลที่สมัครใหม่ = ข้าม"""
    import importlib.util
    import pathlib
    import shutil
    import sqlite3
    from app.accounts import acc_session, Account, Lead, Tenant
    from app.database import get_data_dir
    from app.services import signup_cleanup as sc
    from app.tenancy import ensure_school_db
    db = acc_session()
    try:
        a = _school(db, "ครูจริงก", age_days=5)
        b = _school(db, "ครูจริงข", age_days=5)
        keep = _school(db, "อยู่ต่อ", verified=True, age_days=5)
    finally:
        db.close()
    ensure_school_db(a)
    # ไฟล์สำรอง (snapshot ก่อนลบ) แบบเดียวกับ deploy/backup.sh
    bk = tmp_path / "old"
    (bk / "schools" / str(a)).mkdir(parents=True)
    src = sqlite3.connect(str(get_data_dir() / "accounts.db"))
    dst = sqlite3.connect(str(bk / "accounts.db"))
    src.backup(dst); dst.close(); src.close()
    shutil.copyfile(get_data_dir() / "schools" / str(a) / "school.db", bk / "schools" / str(a) / "school.db")

    assert sc.purge_unverified() == 2                       # เหตุการณ์ที่เกิดจริง
    db = acc_session()
    try:
        db.get(Tenant, keep).name = "อยู่ต่อ (แก้หลังสำรอง)"   # ข้อมูลใหม่หลังวันสำรองต้องไม่ถูกทับ
        t = Tenant(name="สมัครใหม่", slug="new-b", plan="trial"); db.add(t); db.flush()
        db.add(Account(tenant_id=t.id, username="ครูจริงข@school.ac.th", password_hash="x", is_owner=True))
        db.commit()
    finally:
        db.close()

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("restore_tenants", root / "tools" / "restore_tenants.py")
    rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
    p = rt.plan(bk)
    assert [i["tenant"]["id"] for i in p["restore"]] == [a]
    assert [s[0] for s in p["skipped"]] == [b], "อีเมลนี้สมัครใหม่ไปแล้ว ต้องข้าม"
    assert rt.apply(bk, p) == 1
    db = acc_session()
    try:
        assert db.get(Tenant, a).name == "ครูจริงก"
        assert db.query(Account).filter_by(tenant_id=a, username="ครูจริงก@school.ac.th").count() == 1
        assert db.query(Lead).filter_by(tenant_id=a, kind="trial").count() == 1
        assert db.get(Tenant, keep).name == "อยู่ต่อ (แก้หลังสำรอง)"
    finally:
        db.close()
    assert (get_data_dir() / "schools" / str(a) / "school.db").exists()
    assert rt.plan(bk)["restore"] == [], "กู้ซ้ำไม่ได้ (มีอยู่แล้ว)"
