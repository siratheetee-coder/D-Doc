# -*- coding: utf-8 -*-
"""ช่องเลือกปีงบต้องย้อนหลังและล่วงหน้าได้ แม้ปีนั้นยังไม่มีข้อมูล

ของเดิมคืนเฉพาะปีที่มีข้อมูลอยู่แล้ว โรงเรียนที่เพิ่งเริ่มใช้จึงเห็นปีเดียว
กลายเป็นไก่กับไข่: ไม่มีข้อมูลจึงไม่มีปีให้เลือก พอเลือกปีไม่ได้ก็ลงข้อมูลย้อนหลังไม่ได้
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_finance_years.py
"""
import importlib.util
import pathlib
import re
import sys
import tempfile
from datetime import date

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
    for key in ("tenant_state", "can_use_module", "get_account_access"):
        monkeypatch.setattr(main_mod, key, getattr(ac, key))

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    return c


def test_years_cover_past_and_next_even_with_no_data():
    from app.routers.finance import _finance_years
    from app.tenancy import session_for

    class Empty:
        def query(self, *a, **k):
            return self

        def distinct(self):
            return []

    years = _finance_years(Empty(), 2570)
    assert 2568 in years and 2569 in years, years     # ย้อนหลังลงข้อมูลเก่าได้
    assert 2571 in years, years                        # ตั้งงบปีหน้าล่วงหน้าได้
    assert years == sorted(years, reverse=True)


def test_year_with_data_outside_the_window_is_kept(env):
    """ปีเก่ามาก ๆ ที่มีข้อมูลอยู่ ต้องไม่หายไปจากช่องเลือก"""
    from app.models import FinanceAccount, FinanceTxn
    from app.routers.finance import _finance_years
    from app.tenancy import session_for
    db = session_for(1)
    acct = db.query(FinanceAccount).first()
    if acct is None:
        acct = FinanceAccount(name="เงินอุดหนุน", fund_type="เงินงบประมาณ")
        db.add(acct)
        db.flush()
    db.add(FinanceTxn(account_id=acct.id, fiscal_year=2560, kind="in", amount=10,
                      date=date(2017, 10, 1), note="ของเก่ามาก"))
    db.commit()
    years = _finance_years(db, 2570)
    db.close()
    assert 2560 in years, years


def test_the_picker_on_screen_offers_more_than_one_year(env):
    c = env
    html = c.get("/finance/accounts").text
    block = html.split('name="year"', 1)[1].split("</select>", 1)[0]
    options = re.findall(r'value="(\d{4})"', block)
    assert len(set(options)) >= 3, options
