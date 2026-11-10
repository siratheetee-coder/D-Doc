# -*- coding: utf-8 -*-
"""ไล่กดลิงก์ทุกหน้าที่ครูและไอดีหลักเข้าถึงได้ ต้องไม่มีหน้า 404 หรือ error 500

เจ้าของเจอ: ไอดีครูกดหนังสือถึงฉันแล้วกดย้อนกลับ ขึ้น 404 (ปุ่มตัด URL เป็น /me ซึ่งไม่มีหน้า)
เทสต์นี้ตามปลายทางปุ่มย้อนกลับ (window.UP_URL) ด้วย
"""
import re
from collections import deque
from tests.test_subsidy import env  # noqa


def test_crawl(env):
    from app.accounts import Account, Tenant, acc_session, hash_password
    from app.tenancy import session_for
    from app.models import Person
    with acc_session() as s:
        tid = s.query(Tenant).first().id
    db = session_for(tid)
    p = db.query(Person).first(); pid = p.id; db.close()
    with acc_session() as s:
        s.add(Account(tenant_id=tid, username="crawlteacher", display_name="ครู", role="user", is_owner=False,
                      person_id=pid, active=True, welcomed=True, verified=True, must_change_password=False,
                      modules="academic", password_hash=hash_password("Demo!2569x")))
        s.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    for who, pw in (("crawlteacher", "Demo!2569x"), ("demo", "Demo!2569")):
        c = TestClient(app, raise_server_exceptions=False)
        c.post("/login", data={"username": who, "password": pw}, follow_redirects=False)
        seen, q, bad = set(), deque(["/"]), []
        skip = re.compile(r"logout|delete|remove|/export|\.docx|\.xlsx|\.pdf|\.png|/file|/download|/print|mailto:|tel:|javascript:|^#|/sandbox|/admin-console|advance")
        while q and len(seen) < 1500:
            u = q.popleft()
            if u in seen: continue
            seen.add(u)
            r = c.get(u, follow_redirects=True)
            if r.status_code >= 400:
                bad.append((r.status_code, u, ref.get(u)))
                continue
            if "text/html" not in r.headers.get("content-type", ""): continue
            for h in re.findall(r'href="([^"]+)"', r.text):
                h = h.replace("&amp;", "&")
                if not h.startswith("/") or h.startswith("//") or h.startswith("/static") or skip.search(h): continue
                h = h.split("#")[0]
                if h and h not in seen:
                    ref.setdefault(h, u); q.append(h)
            # ปลายทางปุ่มย้อนกลับ
            m = re.search(r'window\.UP_URL = "([^"]*)"', r.text)
            if m and m.group(1) and m.group(1) not in seen:
                ref.setdefault(m.group(1), u + " [UP]"); q.append(m.group(1))
        print("\n##", who, "pages", len(seen))
        broken = [b for b in bad if b[0] == 404 or b[0] >= 500]
        assert not broken, (who, broken)
ref = {}
