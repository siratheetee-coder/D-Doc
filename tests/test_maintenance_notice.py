# -*- coding: utf-8 -*-
"""ประกาศแจ้งปิดปรับปรุงระบบ: การ์ดบนเว็บ + อีเมลถึงไอดีหลักของแต่ละโรงเรียน

กติกาที่ต้องถูก
  - การ์ดขึ้นทุกหน้าของทุกโรงเรียน ตั้งแต่ประกาศจนถึงเวลาสิ้นสุด
  - พ้นเวลาสิ้นสุดแล้วต้องหายเอง (ไม่ต้องให้แอดมินตามปิด)
  - ปิดการ์ดเองได้ก็ไม่ขึ้นอีก แต่ประกาศฉบับใหม่ต้องขึ้นใหม่ (ผูกกับ id)
  - อีเมลส่งทีละฉบับ ไม่เอาอีเมลโรงเรียนอื่นใส่ To ร่วมกัน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_maintenance_notice.py
"""
import importlib.util
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def env(monkeypatch):
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

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"},
               follow_redirects=False)
    assert r.status_code in (302, 303)
    return c, ac


def _notice(ac, *, hours_ahead=24, length=2, active=True, title="แจ้งปิดปรับปรุงระบบชั่วคราว"):
    db = ac.acc_session()
    try:
        n = ac.MaintenanceNotice(
            title=title,
            start_at=datetime.now() + timedelta(hours=hours_ahead),
            end_at=datetime.now() + timedelta(hours=hours_ahead + length),
            items="แก้ปัญหาออกเอกสาร ปพ.5\nเพิ่มทะเบียนคุมโครงการ",
            note="ข้อมูลของท่านยังอยู่ครบ", active=active)
        db.add(n)
        db.commit()
        return n.id
    finally:
        db.close()


def test_card_shows_on_every_page(env):
    c, ac = env
    _notice(ac)
    for url in ("/", "/procurement", "/finance/accounts", "/assets"):
        html = c.get(url).text
        assert "แจ้งปิดปรับปรุงระบบชั่วคราว" in html, url
        assert "ขออภัยในความไม่สะดวก" in html, url
        assert "แก้ปัญหาออกเอกสาร ปพ.5" in html, url


def test_card_disappears_after_the_window(env):
    """พ้นเวลาสิ้นสุดแล้วการ์ดต้องหายเอง ไม่ต้องให้แอดมินตามปิด"""
    c, ac = env
    _notice(ac, hours_ahead=-10, length=2)      # จบไปแล้ว 8 ชม.
    assert "แจ้งปิดปรับปรุงระบบชั่วคราว" not in c.get("/").text


def test_card_hidden_when_switched_off(env):
    c, ac = env
    _notice(ac, active=False)
    assert "แจ้งปิดปรับปรุงระบบชั่วคราว" not in c.get("/").text


def test_card_is_tied_to_the_notice_id(env):
    """ปุ่มรับทราบจำเป็นรายประกาศ ประกาศใหม่ต้องขึ้นใหม่"""
    c, ac = env
    nid = _notice(ac)
    html = c.get("/").text
    assert f'data-mt="{nid}"' in html
    assert "ddoc_maint_" in html


def test_only_the_newest_pending_notice_shows(env):
    c, ac = env
    _notice(ac, hours_ahead=48, title="ประกาศอันหลัง")
    _notice(ac, hours_ahead=12, title="ประกาศอันแรก")
    html = c.get("/").text
    assert "ประกาศอันแรก" in html and "ประกาศอันหลัง" not in html


def test_owner_emails_lists_one_per_school(env):
    """ส่งถึงไอดีหลัก 1 รายต่อโรงเรียน · ไอดีที่ไม่ใช่อีเมลส่งไม่ได้ ต้องถูกแยกออกมาบอก"""
    c, ac = env
    db = ac.acc_session()
    tid = db.query(ac.Tenant).filter_by(slug="demo").one().id
    db.add(ac.Account(tenant_id=tid, username="owner@school.ac.th", display_name="ผอ.",
                      password_hash=ac.hash_password("x"), role="user",
                      is_owner=True, active=True))
    db.commit()
    db.close()
    rows, skipped = ac.owner_emails(with_skipped=True)
    assert [r["email"] for r in rows] == ["owner@school.ac.th"]
    assert skipped, "ไอดี demo ที่ไม่ใช่อีเมล ต้องถูกนับว่าส่งไม่ได้"
    assert len({r["email"].lower() for r in rows}) == len(rows)   # ไม่ซ้ำ


def test_email_is_sent_one_by_one(env, monkeypatch):
    """ส่งทีละฉบับ ไม่เอาอีเมลโรงเรียนอื่นใส่รวมกัน (ข้อมูลลูกค้าไม่รั่วถึงกัน)"""
    c, ac = env
    from app.services import notice_mail
    calls = []
    monkeypatch.setattr(notice_mail, "send_email",
                        lambda to, subject, html, attachments=None: calls.append((to, html)) or True)
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac))
    targets = [{"email": "a@school.ac.th", "school": "โรงเรียน ก"},
               {"email": "b@school.ac.th", "school": "โรงเรียน ข"}]
    sent, failed = notice_mail.send_maintenance_mail(n, targets)
    db.close()
    assert (sent, failed) == (2, 0)
    assert [x[0] for x in calls] == ["a@school.ac.th", "b@school.ac.th"]
    assert "b@school.ac.th" not in calls[0][1]        # ไม่มีอีเมลโรงเรียนอื่นในฉบับแรก
    assert "โรงเรียน ก" in calls[0][1] and "แก้ปัญหาออกเอกสาร ปพ.5" in calls[0][1]


def test_email_counts_failures(env, monkeypatch):
    c, ac = env
    from app.services import notice_mail
    monkeypatch.setattr(notice_mail, "send_email",
                        lambda to, subject, html, attachments=None: to.startswith("ok"))
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac))
    sent, failed = notice_mail.send_maintenance_mail(
        n, [{"email": "ok@a.th"}, {"email": "bad@b.th"}])
    db.close()
    assert (sent, failed) == (1, 1)


def test_when_text_handles_overnight(env):
    from app.services.notice_mail import when_text
    c, ac = env
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac, hours_ahead=20, length=10))
    txt = when_text(n)
    db.close()
    assert "ถึง" in txt if n.end_at.date() != n.start_at.date() else "-" in txt
