# -*- coding: utf-8 -*-
"""เงินอุดหนุนเรียนฟรี 15 ปี: คำนวณยอดที่ควรได้รับแต่ละงวด

กติกาที่ต้องถูก (ถ้าพลาด โรงเรียนจะตั้งงบผิดทั้งปี)
  - ภาคเรียนละ 2 งวด 70% แล้ว 30%
  - ภาคเรียนที่ 1: 70% ใช้ DMC 10 พ.ย. ปีที่แล้ว · 30% ใช้ 10 มิ.ย. ปีนี้
  - ภาคเรียนที่ 2: 70% ใช้ 10 มิ.ย. ปีนี้ · 30% ใช้ 10 พ.ย. ปีนี้
  - ภาคเรียนที่ 1 ได้ 5 รายการ · ภาคเรียนที่ 2 ได้ 3 รายการ
    (ค่าหนังสือเรียน/ค่าเครื่องแบบ จ่ายปีละครั้งในภาคเรียนที่ 1)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_subsidy.py
"""
import importlib.util
import pathlib
import re
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AY = 2569


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


# ---------------------------------------------------------------- ตัวคำนวณ
def _counts(nov_prev, jun, nov):
    return {f"nov{AY - 1}": {"ป.1": nov_prev}, f"jun{AY}": {"ป.1": jun},
            f"nov{AY}": {"ป.1": nov}}


RATES = {"ป.1": {"teach": 2000, "book": 600, "equip": 400, "uniform": 360, "activity": 500}}


def test_each_round_uses_its_own_census():
    """งวดละรอบสำรวจ ใช้ผิดรอบ = เงินผิดทั้งงวด"""
    from app.services.subsidy import compute
    r = compute(_counts(10, 20, 30), RATES, AY)
    got = [(x["term"], x["pct"], x["census_key"], x["heads"]) for x in r["rounds"]]
    assert got == [
        (1, 0.70, f"nov{AY - 1}", 10),
        (1, 0.30, f"jun{AY}", 20),
        (2, 0.70, f"jun{AY}", 20),
        (2, 0.30, f"nov{AY}", 30),
    ]


def test_term_two_has_only_three_items():
    from app.services.subsidy import compute
    r = compute(_counts(10, 10, 10), RATES, AY)
    t1 = [x for x in r["rounds"] if x["term"] == 1]
    t2 = [x for x in r["rounds"] if x["term"] == 2]
    assert all(len(x["amounts"]) == 5 for x in t1)
    assert all(len(x["amounts"]) == 3 for x in t2)
    for x in t2:
        assert "book" not in x["amounts"] and "uniform" not in x["amounts"]


def test_amounts_follow_the_rule():
    """ตรวจเลขจริง: รายหัวแบ่งครึ่งต่อภาคเรียนแล้วคูณสัดส่วนงวด · หนังสือเรียนเต็มจำนวนเทอม 1"""
    from app.services.subsidy import compute
    r = compute(_counts(10, 10, 10), RATES, AY)
    t1_70 = r["rounds"][0]["amounts"]
    assert t1_70["teach"] == pytest.approx(2000 * 10 * 0.5 * 0.70)     # 7,000
    assert t1_70["book"] == pytest.approx(600 * 10 * 1.0 * 0.70)       # 4,200
    t2_30 = r["rounds"][3]["amounts"]
    assert t2_30["teach"] == pytest.approx(2000 * 10 * 0.5 * 0.30)     # 3,000
    # รวมทั้งปีของแต่ละรายการต้องเท่ากับอัตราเต็ม x จำนวนนักเรียน (เมื่อยอดนักเรียนเท่ากันทุกรอบ)
    assert r["by_item"]["teach"] == pytest.approx(2000 * 10)
    assert r["by_item"]["book"] == pytest.approx(600 * 10)
    assert r["by_item"]["uniform"] == pytest.approx(360 * 10)


def test_rates_differ_by_level():
    """คิดตามยอดนักเรียนแต่ละระดับชั้น ไม่ใช่เหมารวม"""
    from app.services.subsidy import compute, default_rates
    rates = default_rates()
    counts = {f"nov{AY - 1}": {"อ.1": 10, "ป.1": 10}, f"jun{AY}": {"อ.1": 10, "ป.1": 10},
              f"nov{AY}": {"อ.1": 10, "ป.1": 10}}
    r = compute(counts, rates, AY)
    expect = (rates["อ.1"]["teach"] + rates["ป.1"]["teach"]) * 10
    assert r["by_item"]["teach"] == pytest.approx(expect)
    assert rates["อ.1"]["teach"] != rates["ป.1"]["teach"]


# ---------------------------------------------------------------- หน้าเว็บ
def _plain(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_page_saves_and_recalculates(env):
    c = env
    data = {"academic_year": AY}
    for key, n in ((f"nov{AY - 1}", 10), (f"jun{AY}", 20), (f"nov{AY}", 30)):
        data[f"n_{key}_ป.1"] = n
    for item, amount in RATES["ป.1"].items():
        data[f"r_ป.1_{item}"] = amount
    r = c.post("/finance/subsidy", data=data, follow_redirects=False)
    assert r.status_code == 303

    text = _plain(c.get(f"/finance/subsidy?year={AY}").text)
    # ภาคเรียนที่ 1 งวด 70%: นักเรียน 10 คน -> รายหัว 7,000 + หนังสือ 4,200 + อุปกรณ์ 1,400
    #                        + เครื่องแบบ 2,520 + กิจกรรม 1,750 = 16,870
    assert "16,870.00" in text
    assert "DMC 10 พฤศจิกายน 2568" in text


def test_page_compares_with_money_actually_received(env):
    """รับเงินงวดแรกแล้ว ต้องเห็นว่ายังขาดเท่าไร"""
    from datetime import date

    from app.models import AccountItem, FinanceAccount, FinanceTxn
    from app.tenancy import session_for
    c = env
    db = session_for(1)
    acct = FinanceAccount(name="เงินอุดหนุน", fund_type="เงินงบประมาณ", deposit_type="bank")
    db.add(acct)
    db.flush()
    item = AccountItem(account_id=acct.id, fiscal_year=AY + 1, name="ค่าจัดการเรียนการสอน")
    db.add(item)
    db.flush()
    db.add(FinanceTxn(account_id=acct.id, item_id=item.id, fiscal_year=AY + 1, kind="in",
                      amount=7000, date=date(2026, 6, 1), note="รับงวดที่ 1"))
    db.commit()
    db.close()

    data = {"academic_year": AY}
    for key in (f"nov{AY - 1}", f"jun{AY}", f"nov{AY}"):
        data[f"n_{key}_ป.1"] = 10
    for item_key, amount in RATES["ป.1"].items():
        data[f"r_ป.1_{item_key}"] = amount
    c.post("/finance/subsidy", data=data, follow_redirects=False)

    text = _plain(c.get(f"/finance/subsidy?year={AY}").text)
    assert "7,000.00" in text          # รับจริง
    assert "-13,000.00" in text        # ควรได้ 20,000 รับแล้ว 7,000


def test_push_to_budget_creates_the_five_items(env):
    """ตั้งงบให้ทะเบียนคุม 5 รายการ และกดซ้ำไม่สร้างซ้ำ"""
    from app.models import AccountItem, FinanceAccount
    from app.tenancy import session_for
    c = env
    db = session_for(1)
    acct = FinanceAccount(name="เงินอุดหนุน", fund_type="เงินงบประมาณ", deposit_type="bank")
    db.add(acct)
    db.commit()
    aid = acct.id
    db.close()

    data = {"academic_year": AY}
    for key in (f"nov{AY - 1}", f"jun{AY}", f"nov{AY}"):
        data[f"n_{key}_ป.1"] = 10
    for item_key, amount in RATES["ป.1"].items():
        data[f"r_ป.1_{item_key}"] = amount
    c.post("/finance/subsidy", data=data, follow_redirects=False)

    for _ in range(2):          # กดสองครั้ง
        r = c.post("/finance/subsidy/to-budget", data={"year": AY, "account_id": aid},
                   follow_redirects=False)
        assert r.status_code == 303

    db = session_for(1)
    rows = db.query(AccountItem).filter_by(account_id=aid, fiscal_year=AY + 1).all()
    names = sorted(r.name for r in rows)
    budgets = {r.name: r.budget for r in rows}
    db.close()
    assert len(rows) == 5, names
    assert budgets["ค่าจัดการเรียนการสอน"] == pytest.approx(2000 * 10)
    assert budgets["ค่าหนังสือเรียน"] == pytest.approx(600 * 10)
