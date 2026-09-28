# -*- coding: utf-8 -*-
"""กันหน้า 500 ในงานการเงิน (และทั่วทั้งระบบ)

บั๊กที่เคยเจอจริง
  1. /finance/loans/register.docx ใช้ตัวแปร request โดยไม่ได้ประกาศรับไว้
     -> NameError ทุกครั้งที่กดปุ่มดาวน์โหลดทะเบียนคุมลูกหนี้
  2. ZoneInfo('Asia/Bangkok') ต้องมีฐานข้อมูลโซนเวลาในเครื่อง บน Windows
     และในไฟล์ .exe ที่แพ็กแล้วไม่มี -> หน้า /finance พังทั้งหน้า
"""
import ast
import glob
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_route_uses_undeclared_request():
    """route ที่อ้างตัวแปร request ต้องประกาศรับไว้ใน signature เสมอ

    ถ้าไม่ประกาศ FastAPI จะไม่ส่งมาให้ -> NameError -> 500 ทุกครั้งที่เรียก
    และไม่มีทางรู้ตอน import เพราะ Python ผูกชื่อตอนรันเท่านั้น
    """
    bad = []
    for path in glob.glob(str(ROOT / "app" / "routers" / "*.py")) + \
            glob.glob(str(ROOT / "app" / "*.py")):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any("router" in ast.dump(d) for d in node.decorator_list):
                continue
            args = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            if "request" in args:
                continue
            assigned, used = set(), False
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    if isinstance(sub.ctx, ast.Store):
                        assigned.add(sub.id)
                    elif sub.id == "request" and "request" not in assigned:
                        used = True
            if used:
                bad.append(f"{pathlib.Path(path).name}:{node.lineno} {node.name}()")
    assert not bad, "route ใช้ request โดยไม่ได้ประกาศรับ: " + "; ".join(bad)


def test_no_zoneinfo_dependency():
    """ห้ามใช้ ZoneInfo กับเวลาไทย - เวลาไทยเป็น UTC+7 คงที่ เขียนตรง ๆ ได้
    และไม่ต้องพึ่ง tzdata ซึ่งไม่มีบน Windows/ไฟล์ .exe ที่แพ็กแล้ว"""
    hits = []
    for path in glob.glob(str(ROOT / "app" / "**" / "*.py"), recursive=True):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):     # ดูโค้ดจริง ไม่นับคำในคอมเมนต์
            hit = ((isinstance(node, ast.ImportFrom) and node.module == "zoneinfo")
                   or (isinstance(node, ast.Name) and node.id == "ZoneInfo"))
            if hit:
                hits.append(f"{pathlib.Path(path).name}:{node.lineno}")
    assert not hits, "ยังมีการใช้ ZoneInfo ที่: " + ", ".join(sorted(set(hits)))


def test_thai_today_matches_utc_plus_7():
    from datetime import datetime, timedelta, timezone

    from app.thai_utils import thai_now, thai_today
    want = datetime.now(timezone.utc) + timedelta(hours=7)
    assert thai_today() == want.date()
    assert thai_now().utcoffset() == timedelta(hours=7)


@pytest.fixture()
def client(monkeypatch):
    import importlib.util

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
    assert r.status_code in (302, 303), r.status_code
    return c


@pytest.mark.parametrize("url", [
    "/finance",
    "/finance/loans",
    "/finance/loans?attention=overdue",
    "/finance/loans?attention=soon",
    "/finance/loans?attention=undated",
    "/finance/loans/register.docx",
    "/finance/checks",
    "/finance/accounts",
])
def test_finance_pages_do_not_crash(client, url):
    r = client.get(url)
    assert r.status_code < 500, f"{url} -> {r.status_code}"


def test_every_plain_get_page_loads(client):
    """เปิดทุกหน้า GET ที่ไม่มีพารามิเตอร์ในเส้นทาง ต้องไม่มีหน้าไหน 500"""
    from app.main import app
    urls = sorted({
        r.path for r in app.routes
        if "GET" in (getattr(r, "methods", set()) or set())
        and "{" not in getattr(r, "path", "")
        and not getattr(r, "path", "").startswith(
            ("/static", "/openapi", "/docs", "/redoc", "/logout"))
    })
    assert len(urls) > 100, f"หาเส้นทางได้แค่ {len(urls)} - ตรวจตัวกรอง"
    bad = [(u, client.get(u, follow_redirects=False).status_code) for u in urls]
    bad = [x for x in bad if x[1] >= 500]
    assert not bad, "หน้าที่พัง: " + "; ".join(f"{u} -> {c}" for u, c in bad)
