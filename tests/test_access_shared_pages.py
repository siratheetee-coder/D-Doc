# -*- coding: utf-8 -*-
"""ไอดีครูเข้าได้เฉพาะงานที่ได้รับสิทธิ์และหน้าส่วนตัว

เจ้าของเจอ: ไอดีครูเปิดหน้าผู้ขาย/ผู้รับจ้าง ทะเบียนเลขหนังสือ โครงการ ข้อมูลนักเรียน
ตั้งค่าโรงเรียน และสำรองข้อมูลได้ (หน้าส่วนกลางไม่อยู่ในงานไหน ด่านงานจึงไม่ครอบ)
เทสต์นี้เปิดทุกหน้า GET ในระบบด้วยไอดีครู หน้าที่เปิดได้ต้องอยู่ในรายการที่อนุญาตเท่านั้น
"""
from tests.test_subsidy import env  # noqa: F401

# หน้าที่ไอดีครูเปิดได้ (นอกเหนืองานวิชาการ): หน้าส่วนตัว + หน้าสาธารณะ
ALLOWED = {
    "/", "/account/password", "/account/profile", "/ai/status", "/checkout", "/email/stop", "/forgot",
    "/guide", "/healthz", "/home/approvals", "/knowledge", "/landing", "/me/leave", "/me/leave/blank.docx",
    "/me/letters", "/me/travel", "/me/travel/blank.docx", "/privacy", "/quote", "/reset", "/robots.txt",
    "/sale-thanks", "/search", "/search/suggest", "/sitemap.xml", "/support", "/support/chat/messages",
    "/system-updates", "/verify", "/settings/calendar",   # ดูปฏิทินโรงเรียนได้ บันทึกไม่ได้
}


def _account(username, modules, person=True):
    from app.accounts import Account, Tenant, acc_session, hash_password
    from app.tenancy import session_for
    from app.models import Person
    with acc_session() as s:
        tid = s.query(Tenant).first().id
    db = session_for(tid)
    pid = db.query(Person).first().id if person else None
    db.close()
    with acc_session() as s:
        s.add(Account(tenant_id=tid, username=username, role="user", is_owner=False, person_id=pid, active=True,
                      welcomed=True, verified=True, must_change_password=False, modules=modules,
                      password_hash=hash_password("Demo!2569x")))
        s.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": username, "password": "Demo!2569x"}, follow_redirects=False)
    return c


def test_teacher_can_only_open_personal_pages_and_granted_modules(env):
    from starlette.routing import Route
    from app.main import app
    from app.modules import module_for_path
    c = _account("ครูทดสอบสิทธิ์", "academic")
    opened = set()
    for r in app.routes:
        if not isinstance(r, Route) or "GET" not in (r.methods or set()) or "{" in r.path:
            continue
        p = r.path
        if p.startswith(("/static", "/logout")) or module_for_path(p) == "academic":
            continue
        if c.get(p, follow_redirects=False).status_code == 200:
            opened.add(p)
    assert opened <= ALLOWED, sorted(opened - ALLOWED)
    for p in ("/vendors", "/docnos", "/projects", "/students", "/settings", "/backup", "/masters", "/general"):
        assert c.get(p, follow_redirects=False).status_code == 403, p
    # บันทึก (POST) ก็ต้องโดนกันด้วย ไม่ใช่แค่ซ่อนหน้า
    assert c.post("/vendors", data={"name": "ร้านแอบเพิ่ม"}, follow_redirects=False).status_code == 403


def test_staff_with_procurement_still_opens_vendor_pages(env):
    c = _account("เจ้าหน้าที่พัสดุทดสอบ", "procurement", person=False)
    assert c.get("/vendors", follow_redirects=False).status_code == 200
    assert c.get("/docnos", follow_redirects=False).status_code == 200
    assert c.get("/settings", follow_redirects=False).status_code == 403, "ตั้งค่าโรงเรียนเป็นของไอดีหลัก"
    assert c.get("/backup", follow_redirects=False).status_code == 403


def test_api_docs_are_closed(env):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert env.get(p, follow_redirects=False).status_code == 404, p
