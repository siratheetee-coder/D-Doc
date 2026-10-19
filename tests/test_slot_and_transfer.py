# -*- coding: utf-8 -*-
"""ปิดช่องว่างจากการเทียบกับ FinVouch (2026-10-19)

1) เลือก "ลงช่องไหนใน e-Budget" ตั้งแต่ตอนสร้างบัญชี/หมวด (ระบบเดาจากชื่อให้ก่อน)
   เดิมรู้ตัวตอนเปิดหน้า e-Budget แล้วเห็นเงินกองที่ "อื่น ๆ"
2) "ไม่นับเป็นรายรับ/รายจ่าย" สำหรับโอนเงินภายในโรงเรียน (ฝากเงินสดเข้าธนาคาร/ถอน/โอนระหว่างบัญชี)
   ยอดคงเหลือขยับ แต่รายรับ-รายจ่ายใน e-Budget และหน้าหลักไม่บวม
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_slot_and_transfer.py
"""
from datetime import datetime

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _account(name):
    from app.models import FinanceAccount
    db = _db()
    try:
        return db.query(FinanceAccount).filter_by(name=name).one()
    finally:
        db.close()


def test_create_account_with_slot_and_guess(env):
    html = env.get(f"/finance/accounts?year={FY}").text
    assert 'name="eb_slot" required data-eb-guess' in html and "ลงช่องไหนใน e-Budget *" in html
    env.post("/finance/accounts", data={"name": "ออมทรัพย์ 123-4-56789-0", "opening_balance": "0",
                                        "deposit_type": "bank", "eb_slot": "3.5"})
    env.post("/finance/accounts", data={"name": "บัญชีมั่ว", "deposit_type": "bank", "eb_slot": "9.9"})
    assert _account("ออมทรัพย์ 123-4-56789-0").eb_slot == "3.5"
    assert _account("บัญชีมั่ว").eb_slot == "", "ช่องที่ไม่มีในแบบ = ไม่บันทึก"
    assert env.get("/finance/ebudget/guess?name=เงินรายได้สถานศึกษา").json() == {"slot": "3.5", "other": False}
    assert env.get("/finance/ebudget/guess?name=ออมทรัพย์ 999").json()["other"] is True
    acc = _account("ออมทรัพย์ 123-4-56789-0")
    g = env.get(f"/finance/ebudget/guess?name=ค่าอะไรก็ได้&account_id={acc.id}").json()
    assert g == {"slot": "3.5", "other": False}, "หมวดชื่อไม่บอกอะไร -> ตามบัญชี"
    assert env.get(f"/finance/ebudget/guess?name=ค่าหนังสือเรียน&account_id={acc.id}").json()["slot"] == "3.1.2"
    html = env.get(f"/finance/accounts?year={FY}").text
    assert f'action="/finance/accounts/{acc.id}/eb-slot"' in html and "e-Budget: 3.5 เงินรายได้สถานศึกษา" in html
    env.post(f"/finance/accounts/{acc.id}/eb-slot", data={"eb_slot": "3.4", "year": FY})
    assert _account("ออมทรัพย์ 123-4-56789-0").eb_slot == "3.4"


def test_item_slot_on_create_and_inline(env):
    from app.models import AccountItem
    env.post("/finance/accounts", data={"name": "เงินอุดหนุนรายหัว", "deposit_type": "bank", "eb_slot": "3.1.1"})
    acc = _account("เงินอุดหนุนรายหัว")
    env.post(f"/finance/accounts/{acc.id}/item", data={"name": "ค่าซื้อของพิเศษ", "fiscal_year": FY, "eb_slot": "3.1.5"})
    db = _db()
    try:
        it = db.query(AccountItem).filter_by(account_id=acc.id, name="ค่าซื้อของพิเศษ").one()
        assert it.eb_slot == "3.1.5"
        iid = it.id
    finally:
        db.close()
    html = env.get(f"/finance/accounts/{acc.id}?year={FY}").text
    assert "<th>ช่อง e-Budget</th>" in html and 'data-account-id="%d"' % acc.id in html
    env.post(f"/finance/items/{iid}/update", data={"eb_slot": "3.1.3", "year": FY})
    db = _db()
    try:
        assert db.get(AccountItem, iid).eb_slot == "3.1.3"
    finally:
        db.close()
    env.post(f"/finance/items/{iid}/update", data={"budget": "500", "year": FY})
    db = _db()
    try:
        assert db.get(AccountItem, iid).eb_slot == "3.1.3", "แก้ช่องอื่นของหมวด ไม่ล้างช่อง e-Budget"
    finally:
        db.close()


def _build():
    from app.services.ebudget import build
    db = _db()
    try:
        return build(db, FY, 1)
    finally:
        db.close()


def test_internal_transfer_moves_balance_but_not_income_or_expense(env):
    from app.models import FinanceTxn
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา (เงินสด)", "deposit_type": "cash", "eb_slot": "3.5"})
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา (ธนาคาร)", "deposit_type": "bank", "eb_slot": "3.5"})
    cash, bank = _account("เงินรายได้สถานศึกษา (เงินสด)"), _account("เงินรายได้สถานศึกษา (ธนาคาร)")
    base = _build()
    html = env.get(f"/finance/accounts/{cash.id}?year={FY}").text
    assert 'name="no_count" value="1"' in html and "ไม่นับเป็นรายรับ/รายจ่าย" in html
    env.post(f"/finance/accounts/{cash.id}/txn", data={"kind": "in", "amount": "3000", "date": "05/11/2569",
                                                     "fiscal_year": FY, "note": "รับค่าเช่าโรงอาหาร", "eb_code": "i5.10"})
    env.post(f"/finance/accounts/{cash.id}/txn", data={"kind": "out", "amount": "3000", "date": "06/11/2569",
                                                     "fiscal_year": FY, "note": "นำฝากธนาคาร", "no_count": "1", "eb_code": "4.9"})
    env.post(f"/finance/accounts/{bank.id}/txn", data={"kind": "in", "amount": "3000", "date": "06/11/2569",
                                                     "fiscal_year": FY, "note": "รับฝากจากเงินสด", "no_count": "1"})
    d = _build()
    assert d["totals"]["income"] - base["totals"]["income"] == 3000, "นับแค่รับค่าเช่า ไม่นับโอน"
    assert d["totals"]["expense"] == base["totals"]["expense"], "ฝากธนาคารไม่ใช่รายจ่าย"
    assert d["check"] == 0 and d["no_count_net"] == 0
    db = _db()
    try:
        out = db.query(FinanceTxn).filter_by(note="นำฝากธนาคาร").one()
        assert out.no_count and out.eb_code == "", "รายการโอนไม่ต้องมีหมวด e-Budget"
        assert out.id not in d["missing"], "ไม่ถามหมวดรายจ่ายของรายการโอน"
        tid = out.id
    finally:
        db.close()
    fill = env.get(f"/finance/ebudget/fill?year={FY}&round=1").text
    assert "นำฝากธนาคาร" not in fill and "รับฝากจากเงินสด" not in fill
    dash = env.get(f"/finance?year={FY}").text
    assert "3,000.00" in dash
    # โอนแล้วลงไม่ครบคู่ -> ยอดตรวจไม่ตรง พร้อมบอกสาเหตุ
    env.post(f"/finance/accounts/{bank.id}/txn", data={"kind": "out", "amount": "500", "date": "07/11/2569",
                                                     "fiscal_year": FY, "note": "ถอนเงินสดย่อย", "no_count": "1"})
    d = _build()
    assert d["check"] == 500 and d["no_count_net"] == -500
    from app.services.ebudget import checklist
    step = next(s for s in checklist(d, FY, 1)["steps"] if s["title"].startswith("ยอดตรวจ"))
    assert "ยังลงไม่ครบคู่" in step["detail"]
    # สลับกลับเป็นนับรายจ่ายได้จากแถวในประวัติ
    r = env.post(f"/finance/txn/{tid}/no-count", data={"value": ""}, follow_redirects=False)
    assert r.headers["location"].endswith("#txn-history")
    db = _db()
    try:
        assert db.get(FinanceTxn, tid).no_count is False
    finally:
        db.close()
    html = env.get(f"/finance/accounts/{bank.id}?year={FY}").text
    assert "โอนภายใน (ไม่นับรับ-จ่าย)" in html
    assert "ตั้งเป็นโอนภายใน" in env.get(f"/finance/accounts/{cash.id}?year={FY}").text, "รายการปกติมีปุ่มตั้งเป็นโอนภายใน"
