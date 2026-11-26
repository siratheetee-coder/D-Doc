# -*- coding: utf-8 -*-
"""
test_launch_smoke.py - ชุดทดสอบ "พร้อม launch" (สถาปัตยกรรมปัจจุบัน: DB-per-school)

ครอบคลุม: แอปบูตได้, หน้าหลักทุกโมดูลตอบ 200, และคุณสมบัติความปลอดภัยหลัก
(รหัสผ่าน hash, กัน SSRF, secret key สุ่ม, จำกัดจำนวนครั้ง login)

รัน:  python -m pytest tests/test_launch_smoke.py -q
หมายเหตุ: ไฟล์ test_*.py เก่าอ้าง SessionLocal (ก่อนเปลี่ยนเป็น multi-tenant) จึงรันไม่ได้แล้ว
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # monkeypatch คืนค่าเดิมหลังจบเทสต์ (ของเดิมแทนที่ถาวร ทำให้เทสต์ไฟล์อื่นที่รันต่อพัง)
    import app.main as m
    import app.routers.auth as auth
    monkeypatch.setattr(auth, "authenticate", lambda u, p: {
        "uid": 2, "username": "tester", "role": "user", "tenant_id": 1,
        "display_name": "ผู้ทดสอบ", "must_change": False, "is_owner": True,
        "modules": "", "welcomed": True, "verified": True,
    })
    monkeypatch.setattr(m, "can_use_module", lambda t, mod: True)
    c = TestClient(m.app)
    c.post("/login", data={"username": "a", "password": "b"})
    return c


def test_app_boots():
    import app.main as m
    assert len(m.app.routes) > 300


def test_public_pages_no_auth():
    import app.main as m
    c = TestClient(m.app)
    assert c.get("/login").status_code == 200
    assert c.get("/landing").status_code == 200
    # หน้าแรกของผู้ไม่ล็อกอิน = หน้า landing เลย (ไม่ redirect ให้ Google เก็บหน้าแรกได้)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 200 and "ลดงานเอกสาร" in r.text


KEY_PAGES = [
    "/", "/procurement", "/procurement/contracts", "/procurement/new", "/materials",
    "/vendors", "/students", "/masters", "/finance", "/finance/report", "/admin/memos",
    "/admin/letters", "/admin/incoming", "/admin/outgoing", "/lunch", "/projects",
    "/settings", "/users", "/guide", "/hr", "/academic", "/assets", "/requisitions",
]


@pytest.mark.parametrize("url", KEY_PAGES)
def test_key_pages_ok(client, url):
    assert client.get(url, follow_redirects=True).status_code == 200


def test_password_hashing_roundtrip():
    from app.accounts import hash_password, verify_password
    h = hash_password("s3cret!")
    assert h != "s3cret!" and "$" in h          # ไม่เก็บ plaintext
    assert verify_password("s3cret!", h) is True
    assert verify_password("wrong", h) is False


def test_secret_key_is_random_hex():
    from app.accounts import get_secret_key
    k = get_secret_key()
    assert len(k) >= 32 and all(ch in "0123456789abcdef" for ch in k)


def test_ssrf_blocked_for_internal_hosts():
    from app.services.file_upload import _is_public_host, fetch_file
    for h in ("127.0.0.1", "localhost", "169.254.169.254", "10.0.0.1", "192.168.0.1"):
        assert _is_public_host(h) is False
    # fetch_file ต้องปฏิเสธ URL วงในทันที (ไม่ยิงออก)
    assert fetch_file("http://169.254.169.254/latest/meta-data")[2] == "url"


def test_login_rate_limit(monkeypatch):
    import uuid
    import app.routers.auth as auth
    import app.main as m
    # monkeypatch คืนค่าเดิมหลังจบ (ของเดิม reload + แทนที่ถาวร ทำให้ล็อกอินในเทสต์ไฟล์ถัดไปล้มทุกครั้ง)
    monkeypatch.setattr(auth, "authenticate", lambda u, p: None)   # ให้ล็อกอินล้มเหลวเสมอ
    user = "ratelimit-" + uuid.uuid4().hex[:8]                      # ชื่อใหม่ทุกครั้ง = ตัวนับเริ่มสด
    c = TestClient(m.app)
    codes = [c.post("/login", data={"username": user, "password": "y"}).status_code
             for _ in range(10)]
    assert 429 in codes            # ต้องโดนล็อกหลังพยายามหลายครั้ง
