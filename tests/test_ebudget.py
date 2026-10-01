# -*- coding: utf-8 -*-
"""ช่วยกรอก e-Budget (ระบบบัญชีการศึกษาขั้นพื้นฐาน สนผ. สพฐ.)

กติกาของ e-Budget ที่ต้องถูก
  - รายงานปีละ 2 ครั้ง · ครั้งที่ 1 = 1 ต.ค.–31 มี.ค. · ครั้งที่ 2 = 1 เม.ย.–30 ก.ย.
  - เว็บตรวจว่า (ยกมา + รายรับ) − รายจ่าย = คงเหลือ ถ้าไม่ตรงกรอกไม่ผ่าน
  - ประเภทเงินต้องลงให้ตรงช่อง (รายหัว/ค่าหนังสือเรียน/ทุนเสมอภาค ฯลฯ)
  - รายการที่จับคู่ไม่ได้ ต้องบอกครูตรง ๆ ไม่ใช่เงียบแล้วยัดลงอื่น ๆ
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_ebudget.py
"""
import importlib.util
import pathlib
import sys
import tempfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2569


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

    from app.accounts import Tenant, acc_session
    from app.models import AccountItem, FinanceAccount, FinanceTxn
    from app.tenancy import session_for
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    db = session_for(tid)
    a = FinanceAccount(name="เงินอุดหนุน", fund_type="เงินนอกงบประมาณ",
                       deposit_type="bank", opening_balance=0)
    inc = FinanceAccount(name="เงินรายได้สถานศึกษา", fund_type="เงินนอกงบประมาณ",
                         deposit_type="cash", opening_balance=5000)
    db.add_all([a, inc])
    db.flush()
    ids = {}
    for nm in ("ค่าจัดการเรียนการสอน", "ค่าหนังสือเรียน", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน",
               "ค่าตกแต่งสวนหย่อม"):
        it = AccountItem(account_id=a.id, fiscal_year=FY, name=nm, deposit_type="bank")
        db.add(it)
        db.flush()
        ids[nm] = it.id
    # ครั้งที่ 1 (ธ.ค. 2568) · ครั้งที่ 2 (พ.ค./ส.ค. 2569)
    for d, kind, amt, item, acct in [
            (datetime(2025, 12, 5), "in", 100000, "ค่าจัดการเรียนการสอน", a),
            (datetime(2025, 12, 20), "out", 30000, "ค่าจัดการเรียนการสอน", a),
            (datetime(2026, 5, 10), "in", 50000, "ค่าหนังสือเรียน", a),
            (datetime(2026, 5, 20), "out", 20000, "ค่าหนังสือเรียน", a),
            (datetime(2026, 8, 3), "out", 4000, "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", a),
            (datetime(2026, 8, 9), "out", 1500, "ค่าตกแต่งสวนหย่อม", a),
            (datetime(2026, 6, 1), "in", 2000, None, inc)]:
        db.add(FinanceTxn(account_id=acct.id, fiscal_year=FY, date=d, kind=kind,
                          amount=amt, note=item or "รับเงินรายได้",
                          item_id=ids.get(item) if item else None))
    db.commit()
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"},
               follow_redirects=False)
    assert r.status_code in (302, 303)
    return c, tid


def _build(tid, rnd):
    from app.services.ebudget import build
    from app.tenancy import session_for
    db = session_for(tid)
    try:
        return build(db, FY, rnd)
    finally:
        db.close()


def test_period_matches_the_official_windows():
    from app.services.ebudget import period
    s1, e1, l1 = period(FY, 1)
    s2, e2, l2 = period(FY, 2)
    assert (s1.day, s1.month, s1.year) == (1, 10, 2025)      # 1 ต.ค. 2568
    assert (e1.day, e1.month, e1.year) == (31, 3, 2026)      # 31 มี.ค. 2569
    assert (s2.day, s2.month) == (1, 4) and (e2.day, e2.month) == (30, 9)
    assert "1 ต.ค." in l1 and "30 ก.ย." in l2


@pytest.mark.parametrize("name,code", [
    ("ค่าจัดการเรียนการสอน", "3.1.1"),
    ("ค่าหนังสือเรียน", "3.1.2"),
    ("ค่าอุปกรณ์การเรียน", "3.1.3"),
    ("ค่าเครื่องแบบนักเรียน", "3.1.4"),
    ("ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", "3.1.5"),
    ("ปัจจัยพื้นฐานนักเรียนยากจน", "3.1.6"),
    ("เงินอุดหนุนนักเรียนยากจนพิเศษ (ทุนเสมอภาค) กสศ.", "3.12"),
    ("เงินรายได้สถานศึกษา", "3.5"),
    ("เงินประกันสัญญา", "3.7"),
    ("เงินภาษีหัก ณ ที่จ่าย", "3.8"),
    ("ค่าอาหารกลางวัน", "3.2.2"),
    ("ค่าตกแต่งสวนหย่อม", "3.13"),
])
def test_money_type_maps_to_the_right_box(name, code):
    """ทุนเสมอภาคต้องไม่ตกไปช่อง 'ปัจจัยพื้นฐานนักเรียนยากจน' (ชื่อมีคำว่ายากจนเหมือนกัน)"""
    from app.services.ebudget import classify
    assert classify(name)[0] == code, name


def test_round_one_counts_only_its_own_window(env):
    _c, tid = env
    d = _build(tid, 1)
    assert d["income"]["3.1.1"] == 100000
    assert d["income"]["3.1.2"] == 0          # ของรอบ 2 ต้องไม่หลุดมา
    assert d["totals"]["expense"] == 30000


def test_round_two_counts_only_its_own_window(env):
    _c, tid = env
    d = _build(tid, 2)
    assert d["income"]["3.1.2"] == 50000
    assert d["income"]["3.1.1"] == 0
    assert d["totals"]["expense"] == 25500    # 20,000 + 4,000 + 1,500


def test_opening_carries_the_earlier_window(env):
    """ยกมาต้นงวดรอบ 2 = ผลของรอบ 1 (รับ 100,000 − จ่าย 30,000) + ยอดตั้งต้นบัญชี"""
    _c, tid = env
    d = _build(tid, 2)
    assert d["opening"]["3.1.1"] == 70000
    assert d["opening"]["3.5"] == 5000        # เงินรายได้สถานศึกษา ยอดตั้งต้น


def test_totals_balance_like_the_website_checks(env):
    """(ยกมา + รายรับ) − รายจ่าย = คงเหลือ · ถ้าไม่ตรง e-Budget จะไม่ให้กรอก"""
    for rnd in (1, 2):
        _c, tid = env
        d = _build(tid, rnd)
        t = d["totals"]
        assert round(t["opening"] + t["income"] - t["expense"] - t["closing"], 2) == 0
        assert d["check"] == 0


def test_expense_is_split_by_funding_source(env):
    _c, tid = env
    d = _build(tid, 2)
    assert d["expense"]["free"] == 24000      # หนังสือเรียน + กิจกรรมพัฒนา
    assert d["expense"]["etc"] == 1500        # รายการที่จับคู่ไม่ได้
    assert sum(d["expense"].values()) == d["totals"]["expense"]


def test_unmapped_items_are_reported_not_hidden(env):
    _c, tid = env
    d = _build(tid, 2)
    assert "ค่าตกแต่งสวนหย่อม" in d["unmapped"]


def test_page_lists_every_box_with_copy_buttons(env):
    c, _tid = env
    html = c.get(f"/finance/ebudget?year={FY}&round=2").text
    assert "ช่วยกรอก e-Budget" in html
    for label in ("รายหัว", "ค่าหนังสือเรียน", "เงินรายได้สถานศึกษา", "ทุนเสมอภาค"):
        assert label in html, label
    assert "cpText(this,'50000.00')" in html         # รายรับค่าหนังสือเรียน
    assert "ส่วนที่ 2" in html and "ส่วนที่ 5" in html
    assert "ไม่ได้ส่งข้อมูลไปที่ e-Budget" in html    # บอกชัดว่าต้องคัดลอกไปวางเอง
    assert "ค่าตกแต่งสวนหย่อม" in html                # เตือนรายการที่จับคู่ไม่ได้


def test_page_switches_rounds(env):
    c, _tid = env
    assert "cpText(this,'100000.00')" in c.get(f"/finance/ebudget?year={FY}&round=1").text
    assert "cpText(this,'100000.00')" not in c.get(f"/finance/ebudget?year={FY}&round=2").text


def test_nav_links_the_page(env):
    c, _tid = env
    assert "/finance/ebudget" in c.get("/finance").text


def test_parent_rows_are_the_sum_of_their_children(env):
    """3.1 ในแบบ e-Budget เป็นยอดรวมของ 3.1.1-3.1.7 ไม่ใช่ช่องแยก
    ถ้าไม่รวมให้ ครูจะคัดลอก 0.00 ไปกรอกช่องหัวข้อรวม"""
    _c, tid = env
    d = _build(tid, 2)
    kids = sum(d["income"][k] for k in
               ("3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.1.7"))
    assert d["income"]["3.1"] == kids > 0
    assert d["opening"]["3.1"] == sum(d["opening"][k] for k in
                                      ("3.1.1", "3.1.2", "3.1.3", "3.1.4",
                                       "3.1.5", "3.1.6", "3.1.7"))


def test_totals_still_balance_after_rollup(env):
    """ยอดรวมต้องไม่ถูกนับซ้ำจากหัวข้อรวม"""
    _c, tid = env
    d = _build(tid, 2)
    assert d["check"] == 0
