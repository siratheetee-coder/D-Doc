# -*- coding: utf-8 -*-
"""ยกยอดไปปีงบถัดไปแล้ว ทุกหน้าต้องเห็นยอดยกมาก้อนเดียวกัน

กติกาที่ต้องถูก
  - กดยกยอด = ยอดคงเหลือสิ้นปีเก่า กลายเป็นยอดยกมาของปีใหม่ ข้อมูลปีเก่ายังอยู่
  - ทุกหน้าที่พูดถึงยอดยกมา ต้องได้เลขเดียวกัน (เคยมีหน้ารายไตรมาสที่ไม่ตรง)
  - กดซ้ำได้ ไม่ทบยอด
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_carry_forward.py
"""
import importlib.util
import pathlib
import re
import sys
import tempfile
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2569
CLOSING = "48,000.00"      # 10,000 ยอดตั้งต้น + 50,000 รับ - 12,000 จ่าย


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

    from app.models import FinanceAccount, FinanceTxn
    from app.tenancy import session_for
    db = session_for(1)
    acct = FinanceAccount(name="เงินอุดหนุนรายหัว", fund_type="เงินงบประมาณ",
                          deposit_type="bank", opening_balance=10000.0)
    db.add(acct)
    db.flush()
    db.add(FinanceTxn(account_id=acct.id, fiscal_year=FY, kind="in", amount=50000.0,
                      date=date(2026, 1, 15), note="รับจัดสรรงวดที่ 1"))
    db.add(FinanceTxn(account_id=acct.id, fiscal_year=FY, kind="out", amount=12000.0,
                      date=date(2026, 2, 10), note="ค่าวัสดุสำนักงาน"))
    db.commit()
    aid = acct.id
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    c.post("/finance/carry-forward", data={"year": FY}, follow_redirects=False)
    return c, aid


def _plain(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.mark.parametrize("page", [
    "/finance/accounts?year={n}",
    "/finance/accounts/{aid}?year={n}",
    "/finance/cashbook?year={n}",
    "/finance/report?year={n}",
    "/finance/quarter?year={n}&q=1",
    "/finance/ebudget?year={n}&round=1",
])
def test_every_page_shows_the_same_carried_amount(env, page):
    """เคยพังที่หน้ารายไตรมาส ใช้ยอดตั้งต้นตอนสร้างบัญชีแทนยอดที่ยกมา"""
    c, aid = env
    url = page.format(n=FY + 1, aid=aid)
    r = c.get(url)
    assert r.status_code == 200, url
    text = _plain(r.text)
    assert "ยกมา" in text, url
    assert CLOSING in text, f"{url} ไม่เห็นยอดยกมา {CLOSING}"


def test_old_year_is_untouched(env):
    """ยกยอดแล้วข้อมูลปีเก่าต้องยังอยู่ครบ กดกลับไปดูได้"""
    c, aid = env
    text = _plain(c.get(f"/finance/accounts/{aid}?year={FY}").text)
    assert "50,000.00" in text and "12,000.00" in text


def test_carrying_twice_does_not_double(env):
    """กดซ้ำต้องได้ยอดเท่าเดิม ไม่ทบ"""
    c, aid = env
    c.post("/finance/carry-forward", data={"year": FY}, follow_redirects=False)
    text = _plain(c.get(f"/finance/accounts/{aid}?year={FY + 1}").text)
    assert CLOSING in text and "96,000.00" not in text


def test_word_register_carries_too(env):
    import io
    import zipfile
    c, aid = env
    r = c.get(f"/finance/accounts/{aid}/money-register.docx?year={FY + 1}")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        doc = re.sub(r"<[^>]+>", "", z.read("word/document.xml").decode("utf-8"))
    assert "ยกมา" in doc and CLOSING in doc
