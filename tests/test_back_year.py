# -*- coding: utf-8 -*-
"""โรงเรียนที่เพิ่งเริ่มใช้ ต้องย้อนไปลงข้อมูลปีก่อนหน้าได้ทุกงาน

ไก่กับไข่: ถ้าช่องเลือกปีคืนเฉพาะ "ปีที่มีข้อมูลอยู่แล้ว" โรงเรียนใหม่จะเห็นปีเดียว
เลือกปีก่อนไม่ได้ จึงลงข้อมูลย้อนหลังไม่ได้เลย
รัน: .venv/Scripts/python.exe -m pytest tests/test_back_year.py
"""
import pathlib
import re
import tempfile

import pytest

from app.thai_utils import fiscal_year_options

CUR = 2570
PAGES = [
    ("ทะเบียนจัดซื้อจัดจ้าง", "/procurement"),
    ("ทะเบียนเลขที่หนังสือ", "/docnos"),
    ("แผนจัดซื้อจัดจ้าง", "/procurement/plan"),
    ("ทะเบียนสัญญา", "/procurement/contracts"),
    ("หนังสือรับ", "/admin/incoming"),
    ("หนังสือส่ง", "/admin/outgoing"),
    ("ทะเบียนคุมเงิน", "/finance/accounts"),
    ("หน้าหลักการเงิน", "/finance"),
    ("ทะเบียนคุมการจ่ายเงิน", "/finance/checks"),
    ("งบกระทบยอด", "/finance/bank-recon"),
    ("สมุดเงินสด", "/finance/cashbook"),
    ("รายงานไตรมาส", "/finance/quarter"),
    ("ทะเบียนใบเสร็จ", "/finance/receipts"),
    ("เงินยืม", "/finance/loans"),
    ("ทะเบียนคุมโครงการ", "/finance/projects"),
    ("โครงการ/กิจกรรม", "/projects"),
]


# ------------------------------------------------------------ ตัวกลาง
def test_options_always_open_a_window_even_with_no_data():
    assert fiscal_year_options([], CUR) == [2571, 2570, 2569, 2568]


def test_options_keep_years_that_already_have_data():
    assert 2565 in fiscal_year_options([2565], CUR)


def test_options_ignore_empty_years():
    assert fiscal_year_options([None, 0, 2569], CUR) == [2571, 2570, 2569, 2568]


# ------------------------------------------------------------ ของจริงทั้งระบบ
@pytest.fixture(scope="module")
def fresh_school():
    """โรงเรียนเปล่า ไม่มีข้อมูลสักรายการ เหมือนเพิ่งสมัครใช้"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        m.get_data_dir = lambda t=tmp: t
    tn._engines.clear()
    ac._engine = ac._Session = None

    import app.main as main_mod
    import app.routers.auth as auth_mod
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
        "display_name": "x", "must_change": False}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {
        "is_owner": True, "modules": "", "active": True, "welcomed": True}
    main_mod.tenant_state = lambda tid: {"name": "ใหม่", "active": True,
                                         "expired": False, "expiry_date": None}

    from app.models import School
    from app.tenancy import session_for
    db = session_for(1)
    if not db.query(School).first():
        db.add(School(name="โรงเรียนเปิดใหม่"))
        db.commit()
    db.close()

    import app.thai_utils as tu
    tu.current_fiscal_year = lambda *a, **k: CUR
    for mod in ("app.routers.pages", "app.routers.finance", "app.routers.admin",
                "app.routers.general", "app.routers.hr", "app.routers.project_report"):
        try:
            m = __import__(mod, fromlist=["x"])
        except Exception:
            continue
        if hasattr(m, "current_fiscal_year"):
            m.current_fiscal_year = lambda *a, **k: CUR

    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "t", "password": "x"}, follow_redirects=False)
    return c


def _year_options(html):
    i = html.find('name="year"')
    if i < 0:
        return None
    start, end = html.rfind("<select", 0, i), html.find("</select>", i)
    if start < 0 or end < 0:
        return None
    return sorted({int(y) for y in re.findall(r'<option[^>]*value="(\d{4})"', html[start:end])},
                  reverse=True)


@pytest.mark.parametrize("label,url", PAGES, ids=[u for _, u in PAGES])
def test_every_register_lets_a_new_school_pick_last_year(fresh_school, label, url):
    r = fresh_school.get(url)
    assert r.status_code == 200, f"{label}: เปิดไม่ได้ ({r.status_code})"
    years = _year_options(r.text)
    assert years, f"{label}: ไม่มีช่องเลือกปี"
    assert any(y < CUR for y in years), f"{label}: เลือกย้อนปีไม่ได้ มีแต่ {years}"
