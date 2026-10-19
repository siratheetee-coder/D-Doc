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


def test_checklist_walks_to_ready_and_section3_uses_chosen_source(env, school):
    """หน้า e-Budget ใช้ยาก -> มีกล่องขั้นตอนก่อนกรอก ติ๊กเองจากข้อมูลจริง
    ส่วนที่ 3 ใช้ "ใครให้เงินมา" ที่เลือกตอนบันทึกรับ (เดิมบันทึกไว้แต่ไม่ได้ใช้)"""
    import re
    import app.tenancy as tn
    from app.models import FinanceTxn
    sid, ids = school
    page = lambda: env.get(f"/finance/ebudget?year={FY}&round=1").text          # noqa: E731
    html = page()
    assert 'id="setup-ebudget"' in html and "ขั้นตอนก่อนกรอก e-Budget" in html
    nxt = re.search(r'fs-step is-next.*?fs-name">\d\. ([^<]+)<', html, re.S).group(1)
    assert nxt == "บอกระบบว่าเงินแต่ละบัญชีลงช่องไหน"
    assert "ยังไม่ได้ระบุข้อย่อยของเงินรับอีก <b>1 รายการ</b>" in html
    env.post("/finance/ebudget/slot", data={"kind": "account", "id": ids["bank"], "slot": "3.5", "year": FY})
    nxt = re.search(r'fs-step is-next.*?fs-name">\d\. ([^<]+)<', page(), re.S).group(1)
    assert nxt == "ระบุที่มาของเงินรับทุกรายการ (ส่วนที่ 3)"
    db = tn.session_for(sid)
    try:
        t_in = db.query(FinanceTxn).filter_by(account_id=ids["bank"]).one().id
        t_out = db.query(FinanceTxn).filter_by(item_id=ids["book"]).one().id
    finally:
        db.close()
    env.post("/finance/ebudget/fill", data={"year": FY, "round": 1, f"eb_{t_in}": "i5.3", f"eb_{t_out}": "1.3"})
    html = page()
    assert 'id="setup-ebudget"' not in html and "พร้อมกรอกแล้ว" in html
    sec3 = html.split('id="sec3"', 1)[1].split("</table>", 1)[0]
    row = re.search(r'<tr class="lv1 nz">\s*<td>5\.3 เงินรายได้สถานศึกษา[^<]*</td>\s*<td class="right[^"]*">(.*?)</td>', sec3, re.S)
    assert row and "2,500.00" in row.group(1), "ข้อย่อยที่เลือกขึ้นยอดในตารางส่วนที่ 3"
    assert re.search(r'<tr class="lv0 nz">\s*<td>5\. เงินนอกงบประมาณ', sec3), "ข้อใหญ่รวมยอดข้อย่อย"
    assert '<tr class="lv1 z">' in sec3, "ข้อที่เป็น 0 ซ่อนไว้ กดแสดงทุกข้อได้"


def test_legacy_top_income_code_asks_for_sub_item(school, env):
    """รายการที่เคยเลือกแค่ข้อใหญ่ (รุ่นเก่า i5) = ยังไม่ระบุข้อย่อย ต้องกลับไปเลือก ระบบเดาให้จากประเภทเงินของบัญชี"""
    from app.models import FinanceTxn
    import app.tenancy as tn
    from app.services.ebudget import build, section3_rows
    sid, ids = school
    env.post("/finance/ebudget/slot", data={"kind": "account", "id": ids["bank"], "slot": "3.5", "year": FY})
    db = tn.session_for(sid)
    try:
        t = db.query(FinanceTxn).filter_by(account_id=ids["bank"]).one()
        t.eb_code = "i5"
        db.commit()
        tid = t.id
        d = build(db, FY, 1)
        assert tid in d["income_missing"]
        top5 = next(r for r in section3_rows(d) if r["code"] == "i5")
        assert top5["amount"] == 2500 and top5["unsorted"] == 2500
    finally:
        db.close()
    fill = env.get(f"/finance/ebudget/fill?year={FY}&round=1").text
    assert f'name="eb_{tid}"' in fill
    sel = fill.split(f'name="eb_{tid}"', 1)[1].split("</select>", 1)[0]
    assert '<option value="i5.3" selected' in sel, "เดาจากช่อง 3.5 ของบัญชี = 5.3 เงินรายได้สถานศึกษา"
    assert "ยังไม่ระบุข้อย่อย" in env.get(f"/finance/ebudget?year={FY}&round=1").text


@pytest.mark.parametrize("text,code", [
    ("ค่าขยายเขตไฟฟ้าอาคาร 2", "3.4"),
    ("ค่าไฟฟ้าเดือน พ.ย.", "4.1.1"),
    ("ค่าจ้างพี่เลี้ยงเด็กพิการ", "2.1.7"),
    ("ค่าจ้างบรรณารักษ์", "2.1.9"),
    ("อบรมครูเรื่องการวัดผล", "2.2"),
    ("ค่าอาหารนักเรียนพักนอน", "5.2"),
    ("ค่าอาหารพักนอนพื้นที่ยากลำบาก", "5.11"),
    ("เงินลูกเสือ ปีการศึกษา 2569", "5.4"),
    ("ค่ากิจกรรมเข้าค่ายลูกเสือ", "1.6"),
    ("เงินยุวกาชาด", "5.6"),
    ("กิจกรรมสร้างความสัมพันธ์ชุมชน", "4.5"),
])
def test_more_expense_guesses(text, code):
    from app.services.ebudget_cat import guess_expense
    assert guess_expense(text) == code
