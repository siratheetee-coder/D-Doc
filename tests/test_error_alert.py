# -*- coding: utf-8 -*-
"""แจ้งเตือน error 500 ทางอีเมลถึงเจ้าของระบบ (จำกัดความถี่ ไม่แนบข้อมูลที่ผู้ใช้กรอก)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_error_alert.py
"""
import json

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)


@pytest.fixture()
def alert(monkeypatch):
    import app.services.error_alert as ea
    sent = []
    monkeypatch.setattr(ea, "_last_sent", {})
    monkeypatch.setattr(ea, "_suppressed", {})
    monkeypatch.setattr(ea, "_sent_times", [])
    monkeypatch.setenv("DDOC_ERROR_ALERT", "1")

    class SyncThread:                       # ส่งทันทีในเทส (ของจริงส่งในเธรดแยก)
        def __init__(self, target, args, daemon):
            self.t, self.a = target, args

        def start(self):
            self.t(*self.a)

    monkeypatch.setattr(ea.threading, "Thread", SyncThread)
    monkeypatch.setattr("app.services.notifications.notification_email", lambda: "owner@example.com")
    monkeypatch.setattr("app.services.mailer.send_email", lambda to, s, h, attachments=None: sent.append((to, s, h)) or True)
    return ea, sent


@pytest.fixture()
def boom():
    """หน้าที่ error เสมอ เพิ่มเข้าแอปเฉพาะเทสนี้ แล้วเอาออก (กันเทสอื่นที่ไล่ดูทุก route)"""
    import app.main
    routes = app.main.app.router.routes
    before = list(routes)

    @app.main.app.get("/__boom/{n}")
    def _boom(n: int, secret: str = ""):
        raise ValueError("พังตอนทดสอบ")
    yield
    routes[:] = before


def test_500_sends_one_email_per_hour_per_error(env, alert, boom):
    ea, sent = alert
    from fastapi.testclient import TestClient
    import app.main
    c = TestClient(app.main.app, raise_server_exceptions=False, cookies=env.cookies)
    r = c.get("/__boom/1?secret=เลขบัตร1234", headers={"accept": "text/html"})
    assert r.status_code == 500 and "ระบบขัดข้องชั่วคราว" in r.text, "ผู้ใช้ยังเห็นหน้า error ปกติ"
    assert len(sent) == 1
    to, subject, html = sent[0]
    assert to == "owner@example.com" and "/__boom/1" in subject and "ValueError" in subject
    assert "พังตอนทดสอบ" in html and "test_error_alert.py" in html
    assert "เลขบัตร1234" not in html, "ไม่ส่งค่าที่ผู้ใช้กรอก"
    for n in (2, 3, 4):                      # error เดียวกัน (id ต่างกัน) ไม่ส่งซ้ำในชั่วโมงเดียว
        c.get(f"/__boom/{n}")
    assert len(sent) == 1
    log = [json.loads(x) for x in (ea_data_dir() / "error-log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["emailed"] for e in log[-4:]] == [True, False, False, False]
    assert log[-1]["query_keys"] == [] and log[-4]["query_keys"] == ["secret"] and "เลขบัตร" not in json.dumps(log, ensure_ascii=False)


def ea_data_dir():
    from app.database import get_data_dir
    return get_data_dir()


def test_throttle_counts_repeats_and_global_cap(alert):
    ea, _ = alert
    t0 = 1_000_000.0
    assert ea.should_send("A", t0) == (True, 0)
    assert ea.should_send("A", t0 + 10) == (False, 0)
    assert ea.should_send("A", t0 + 20) == (False, 0)
    assert ea.should_send("A", t0 + 3601) == (True, 2), "ครบชั่วโมงส่งใหม่ พร้อมบอกว่าเกิดซ้ำ 2 ครั้ง"
    for i in range(ea.MAX_PER_HOUR - 1):
        assert ea.should_send(f"B{i}", t0 + 3602)[0]
    assert ea.should_send("C", t0 + 3603) == (False, 0), "รวมทุก error ไม่เกิน 20 ฉบับ/ชั่วโมง"
    assert ea.should_send("C", t0 + 7300)[0]


def test_signature_ignores_ids():
    from app.services.error_alert import signature
    try:
        raise KeyError("x")
    except KeyError as e:
        a, b = signature("/finance/accounts/12", e), signature("/finance/accounts/99", e)
    assert a == b and a.startswith("KeyError|/finance/accounts/N|")


def test_disabled_and_failures_never_break_the_page(env, alert, boom, monkeypatch):
    ea, sent = alert
    from fastapi.testclient import TestClient
    import app.main
    c = TestClient(app.main.app, raise_server_exceptions=False, cookies=env.cookies)
    monkeypatch.setenv("DDOC_ERROR_ALERT", "0")
    assert c.get("/__boom/5").status_code == 500 and sent == []
    monkeypatch.setenv("DDOC_ERROR_ALERT", "1")
    monkeypatch.setattr("app.services.mailer.send_email", lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")))
    assert c.get("/__boom/6").status_code == 500, "ส่งอีเมลไม่ได้ หน้าเว็บยังตอบปกติ"
