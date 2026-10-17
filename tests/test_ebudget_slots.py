# -*- coding: utf-8 -*-
"""e-Budget: เงินที่ระบบเดาช่องไม่ได้ ต้องให้ผู้ใช้เลือกช่องเองได้ที่หน้า e-Budget (ไม่ต้องไปแก้ชื่อบัญชี)

- ยอดที่เดาไม่ได้ไปตกช่อง "อื่น ๆ" และขึ้นรายการให้เลือกช่อง พร้อมลิงก์ไปแยกหมวดย่อย
- เลือกแล้วจำไว้ (บัญชี/หมวด) ยกยอดข้ามปีแล้วหมวดปีใหม่จำค่าเดิม
- ยอดยกมาแยกตามหมวดย่อย (เดิมลงทั้งก้อนตามชื่อบัญชี ช่องหมวดเลยติดลบ)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_ebudget_slots.py
"""
from datetime import datetime

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


@pytest.fixture()
def school(env):
    import app.tenancy as tn
    from app.models import AccountItem, AccountOpening, FinanceAccount, FinanceTxn
    sid = next(iter(tn._engines))
    db = tn.session_for(sid)
    sub = FinanceAccount(name="เงินอุดหนุนรายหัว"); bank = FinanceAccount(name="ออมทรัพย์ 123-4-56789-0")
    db.add_all([sub, bank]); db.flush()
    db.add(AccountOpening(account_id=sub.id, fiscal_year=FY, amount=100000))
    db.add(AccountOpening(account_id=bank.id, fiscal_year=FY, amount=40000))
    head = AccountItem(account_id=sub.id, fiscal_year=FY, name="ค่าจัดการเรียนการสอน", opening_balance=70000)
    book = AccountItem(account_id=sub.id, fiscal_year=FY, name="ค่าหนังสือเรียน", opening_balance=30000)
    db.add_all([head, book]); db.flush()
    db.add(FinanceTxn(account_id=sub.id, item_id=book.id, fiscal_year=FY, kind="out", amount=12000,
                      date=datetime(2026, 11, 5), note="ซื้อหนังสือเรียน"))
    db.add(FinanceTxn(account_id=bank.id, fiscal_year=FY, kind="in", amount=2500,
                      date=datetime(2026, 11, 10), note="รับเงิน"))
    db.commit()
    ids = {"sub": sub.id, "bank": bank.id, "book": book.id}
    db.close()
    return sid, ids


def _build(sid):
    import app.tenancy as tn
    from app.services.ebudget import build
    db = tn.session_for(sid)
    try:
        return build(db, FY, 1)
    finally:
        db.close()


def test_opening_is_split_by_sub_item(school):
    sid, _ = school
    d = _build(sid)
    assert d["opening"]["3.1.1"] == 70000 and d["opening"]["3.1.2"] == 30000
    assert d["closing"]["3.1.2"] == 18000, "เดิมได้ -12,000 เพราะยอดยกมาไปลงช่องรายหัวทั้งก้อน"
    assert d["check"] == 0


def test_unknown_account_can_be_assigned_on_the_page(env, school):
    sid, ids = school
    d = _build(sid)
    assert [r["name"] for r in d["unmapped"]] == ["ออมทรัพย์ 123-4-56789-0"]
    assert d["closing"]["3.13"] == 42500
    html = env.get(f"/finance/ebudget?year={FY}&round=1").text
    assert "เงินที่ระบบยังไม่รู้ว่าลงช่องไหนใน e-Budget" in html and "42,500.00" in html
    assert f'href="/finance/accounts/{ids["bank"]}?year={FY}">แยกหมวดย่อย' in html
    assert "3.1 3.1" not in html and "3.5 3.5" not in html, "เลขช่องไม่ขึ้นซ้ำ"
    r = env.post("/finance/ebudget/slot", data={"kind": "account", "id": ids["bank"], "slot": "3.5",
                                                "year": FY, "round": 1}, follow_redirects=False)
    assert r.headers["location"].endswith("#eb-slots")
    d = _build(sid)
    assert d["unmapped"] == [] and d["closing"]["3.5"] == 42500 and d["closing"]["3.13"] == 0
    html = env.get(f"/finance/ebudget?year={FY}&round=1").text
    assert "ช่องที่ท่านเลือกเองไว้ (1)" in html and '<option value="3.5" selected>' in html
    env.post("/finance/ebudget/slot", data={"kind": "account", "id": ids["bank"], "slot": "", "year": FY})
    assert [r["name"] for r in _build(sid)["unmapped"]] == ["ออมทรัพย์ 123-4-56789-0"], "ล้างแล้วกลับไปเดาจากชื่อ"


def test_choosing_other_on_purpose_stops_the_warning(env, school):
    sid, ids = school
    env.post("/finance/ebudget/slot", data={"kind": "account", "id": ids["bank"], "slot": "3.13", "year": FY})
    d = _build(sid)
    assert d["unmapped"] == [] and d["closing"]["3.13"] == 42500


def test_item_choice_overrides_name_and_bad_slot_is_rejected(env, school):
    sid, ids = school
    env.post("/finance/ebudget/slot", data={"kind": "item", "id": ids["book"], "slot": "3.1.5", "year": FY})
    d = _build(sid)
    assert d["closing"]["3.1.5"] == 18000 and d["closing"]["3.1.2"] == 0
    assert env.post("/finance/ebudget/slot", data={"kind": "item", "id": ids["book"], "slot": "3.1"}).status_code == 400, \
        "หัวข้อรวมเลือกไม่ได้ (คิดจากข้อย่อย)"


def test_carry_forward_keeps_the_chosen_slot(env, school):
    import app.tenancy as tn
    from app.models import AccountItem
    from app.services.finance_openings import carry
    sid, ids = school
    env.post("/finance/ebudget/slot", data={"kind": "item", "id": ids["book"], "slot": "3.1.5", "year": FY})
    db = tn.session_for(sid)
    try:
        carry(db, FY); db.commit()
        nxt = db.query(AccountItem).filter_by(fiscal_year=FY + 1, name="ค่าหนังสือเรียน").one()
        assert nxt.eb_slot == "3.1.5"
    finally:
        db.close()
