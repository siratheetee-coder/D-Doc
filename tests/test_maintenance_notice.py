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


def _notice(ac, *, hours_ahead=24, length=2, active=True, kind="maint",
            title="แจ้งปิดปรับปรุงระบบชั่วคราว"):
    db = ac.acc_session()
    try:
        n = ac.MaintenanceNotice(
            kind=kind, title=title,
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
    assert f'data-mt="{nid}_' in html
    assert "ddoc_maint_" in html


def test_card_is_visible_without_javascript(env):
    """การ์ดต้องไม่มี hidden ติดมา ถ้า JS พังประกาศก็ยังต้องถึงผู้ใช้"""
    c, ac = env
    _notice(ac)
    tag = c.get("/").text.split('id="maintCard"')[1][:80]
    assert "hidden" not in tag, tag


def test_dismiss_key_differs_after_a_deleted_notice_reuses_the_id(env):
    """SQLite เอา id เดิมกลับมาใช้ซ้ำหลังลบแถว ประกาศใหม่ต้องไม่ถูกซ่อนตามของเก่า"""
    import re
    c, ac = env
    nid = _notice(ac)
    first = re.search(r'data-mt="([^"]+)"', c.get("/").text).group(1)
    db = ac.acc_session()
    db.delete(db.get(ac.MaintenanceNotice, nid))
    db.commit()
    db.close()
    nid2 = _notice(ac, title="ประกาศฉบับใหม่")
    second = re.search(r'data-mt="([^"]+)"', c.get("/").text).group(1)
    assert nid2 == nid, "ทดสอบนี้ต้องให้ id ถูกใช้ซ้ำจริง"
    assert first != second


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


def _fake_smtp(monkeypatch, fail_for=(), delay=0.0):
    """SMTP จำลอง · นับจำนวนครั้งที่เปิดการเชื่อมต่อ และเก็บฉบับที่ส่ง"""
    import smtplib
    import time

    import app.seller_config as sc
    from app.services import mailer
    monkeypatch.setitem(sc.SELLER, "smtp_host", "smtp.test")
    monkeypatch.setitem(sc.SELLER, "smtp_user", "sender@test.th")
    monkeypatch.setitem(sc.SELLER, "smtp_pass", "x")
    monkeypatch.setitem(sc.SELLER, "smtp_from", "sender@test.th")
    box = {"opened": 0, "msgs": []}

    class Fake:
        def __init__(self, host, port, timeout=0):
            box["opened"] += 1
            time.sleep(delay)

        def starttls(self, context=None):
            pass

        def login(self, user, pw):
            pass

        def send_message(self, msg):
            if msg["To"] in fail_for:
                raise OSError("ปลายทางปฏิเสธ")
            box["msgs"].append((msg["To"], msg.get_payload()[-1].get_content()))

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", Fake)
    monkeypatch.setattr(mailer, "smtp_configured", lambda: True)
    return box


def test_email_is_sent_one_by_one(env, monkeypatch):
    """ส่งทีละฉบับ ไม่เอาอีเมลโรงเรียนอื่นใส่รวมกัน (ข้อมูลลูกค้าไม่รั่วถึงกัน)"""
    c, ac = env
    from app.services import notice_mail
    box = _fake_smtp(monkeypatch)
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac))
    targets = [{"email": "a@school.ac.th", "school": "โรงเรียน ก"},
               {"email": "b@school.ac.th", "school": "โรงเรียน ข"}]
    sent, failed = notice_mail.send_maintenance_mail(n, targets)
    db.close()
    assert (sent, failed) == (2, 0)
    assert [to for to, _ in box["msgs"]] == ["a@school.ac.th", "b@school.ac.th"]
    assert "b@school.ac.th" not in box["msgs"][0][1]   # ไม่มีอีเมลโรงเรียนอื่นในฉบับแรก
    assert "โรงเรียน ก" in box["msgs"][0][1] and "แก้ปัญหาออกเอกสาร ปพ.5" in box["msgs"][0][1]


def test_one_smtp_connection_for_every_school(env, monkeypatch):
    """เปิดการเชื่อมต่อครั้งเดียว ไม่งั้นส่งหลายสิบโรงเรียนจะช้าจนโดนตัด 504"""
    c, ac = env
    from app.services import notice_mail
    box = _fake_smtp(monkeypatch)
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac))
    sent, failed = notice_mail.send_maintenance_mail(
        n, [{"email": f"owner{i}@school.ac.th"} for i in range(56)])
    db.close()
    assert (sent, failed) == (56, 0)
    assert box["opened"] == 1


def test_email_counts_failures(env, monkeypatch):
    c, ac = env
    from app.services import notice_mail
    _fake_smtp(monkeypatch, fail_for={"bad@b.th"})
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac))
    sent, failed = notice_mail.send_maintenance_mail(
        n, [{"email": "ok@a.th"}, {"email": "bad@b.th"}])
    db.close()
    assert (sent, failed) == (1, 1)


def test_sending_does_not_block_the_page(env, monkeypatch):
    """กดส่งแล้วหน้าเว็บต้องตอบกลับทันที ส่วนอีเมลทยอยส่งเบื้องหลัง (กัน 504)"""
    import time
    c, ac = env
    box = _fake_smtp(monkeypatch, delay=0.8)
    db = ac.acc_session()
    db.add(ac.Account(tenant_id=None, username="root@test.th", display_name="แอดมิน",
                      password_hash=ac.hash_password("Root!2569"), role="superadmin", active=True))
    for i in range(5):
        t = ac.Tenant(name=f"โรงเรียน {i}", slug=f"sch{i}", active=True)
        db.add(t)
        db.flush()
        db.add(ac.Account(tenant_id=t.id, username=f"owner{i}@school.ac.th", display_name="ผอ.",
                          password_hash=ac.hash_password("x"), role="user",
                          is_owner=True, active=True))
    db.commit()
    db.close()
    nid = _notice(ac)

    from fastapi.testclient import TestClient

    from app.main import app
    admin = TestClient(app, raise_server_exceptions=False)
    admin.post("/login", data={"username": "root@test.th", "password": "Root!2569"},
               follow_redirects=False)
    started = time.time()
    r = admin.post(f"/admin-console/notice/{nid}/email", follow_redirects=False)
    took = time.time() - started
    assert r.status_code == 303
    assert took < 0.5, f"หน้าเว็บรอส่งอีเมลจบ ({took:.2f} วินาที) จะโดนตัด 504 เมื่อมีหลายสิบโรงเรียน"

    for _ in range(100):           # รอให้เธรดเบื้องหลังส่งจบ
        db = ac.acc_session()
        done = db.get(ac.MaintenanceNotice, nid).emailed_at
        db.close()
        if done:
            break
        time.sleep(0.1)
    assert done, "เธรดเบื้องหลังต้องส่งจนจบและบันทึกเวลาที่ส่งเสร็จ"
    assert len(box["msgs"]) == 5 and box["opened"] == 1


def test_when_text_handles_overnight(env):
    from app.services.notice_mail import when_text
    c, ac = env
    db = ac.acc_session()
    n = db.query(ac.MaintenanceNotice).get(_notice(ac, hours_ahead=20, length=10))
    txt = when_text(n)
    db.close()
    assert "ถึง" in txt if n.end_at.date() != n.start_at.date() else "-" in txt


# ---------- ประเภทประกาศ: ใช้ได้มากกว่าแค่แจ้งปิดปรับปรุง ----------
def test_update_notice_does_not_apologise(env):
    """ประกาศของใหม่ต้องไม่ขึ้นว่าขออภัยในความไม่สะดวก และไม่พูดเหมือนระบบจะปิด"""
    c, ac = env
    _notice(ac, kind="update", title="อัปเดตใหม่ในระบบ")
    html = c.get("/").text
    assert "มีอะไรใหม่ในระบบ" in html
    assert "ขออภัยในความไม่สะดวก" not in html
    assert "สิ่งที่เพิ่มและปรับปรุง" in html
    assert 'class="maint news"' in html          # สีคนละชุดกับการ์ดปิดระบบ


def test_info_notice_wording(env):
    c, ac = env
    _notice(ac, kind="info", title="แจ้งกำหนดส่ง ปพ.5")
    html = c.get("/").text
    assert "ประกาศจากทีมงาน" in html and "แจ้งกำหนดส่ง ปพ.5" in html
    assert 'class="maint info"' in html


def test_only_maintenance_shows_the_closing_hours(env):
    """ประกาศทั่วไป/ของใหม่ บอกแค่วัน ไม่ต้องบอกว่าระบบปิดกี่โมงถึงกี่โมง"""
    c, ac = env
    _notice(ac, kind="update")
    assert "เวลา 21:00" not in c.get("/").text
    db = ac.acc_session()
    for n in db.query(ac.MaintenanceNotice).all():
        db.delete(n)
    db.commit()
    db.close()
    _notice(ac, kind="maint")
    assert "ช่วงที่ปิดปรับปรุง" in c.get("/").text


def test_old_notices_without_a_kind_still_work(env):
    """ประกาศเก่าที่บันทึกไว้ก่อนมีประเภท ต้องถือเป็นแจ้งปิดปรับปรุงเหมือนเดิม"""
    c, ac = env
    nid = _notice(ac)
    db = ac.acc_session()
    db.get(ac.MaintenanceNotice, nid).kind = None
    db.commit()
    db.close()
    html = c.get("/").text
    assert "ขออภัยในความไม่สะดวก" in html and 'class="maint maint"' in html


def test_email_follows_the_kind(env, monkeypatch):
    """อีเมลต้องพูดชุดเดียวกับการ์ด ไม่ใช่ขึ้นหัวว่าปิดปรับปรุงทุกฉบับ"""
    c, ac = env
    box = _fake_smtp(monkeypatch)
    db = ac.acc_session()
    n = db.get(ac.MaintenanceNotice, _notice(ac, kind="update", title="ของใหม่เดือนนี้"))
    from app.services import notice_mail
    notice_mail.send_maintenance_mail(n, [{"email": "a@school.ac.th", "school": "โรงเรียน ก"}])
    db.close()
    body = box["msgs"][0][1]
    assert "อัปเดตของใหม่" in body and "ของใหม่เดือนนี้" in body
    assert "ขออภัย" not in body and "เข้าใช้งานไม่ได้ชั่วคราว" not in body


def test_console_lets_you_pick_a_kind(env):
    """คอนโซลต้องมีตัวเลือกประเภทให้เลือกจริง (ไม่งั้นเจ้าของระบบใช้ไม่ได้)"""
    c, ac = env
    db = ac.acc_session()
    db.add(ac.Account(tenant_id=None, username="root2@test.th", display_name="แอดมิน",
                      password_hash=ac.hash_password("Root!2569"), role="superadmin", active=True))
    db.commit()
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    admin = TestClient(app, raise_server_exceptions=False)
    admin.post("/login", data={"username": "root2@test.th", "password": "Root!2569"},
               follow_redirects=False)
    page = admin.get("/admin-console/notice").text
    for label in ("ปิดปรับปรุงระบบ", "อัปเดตของใหม่", "ประกาศทั่วไป"):
        assert label in page, label
    r = admin.post("/admin-console/notice", data={
        "kind": "update", "title": "ของใหม่", "start_day": "02/10/2569", "start_time": "21:00",
        "end_day": "", "end_time": "23:00", "items": "x", "note": ""}, follow_redirects=False)
    assert r.status_code == 303
    db = ac.acc_session()
    saved = db.query(ac.MaintenanceNotice).order_by(ac.MaintenanceNotice.id.desc()).first()
    kind = saved.kind
    db.close()
    assert kind == "update"
