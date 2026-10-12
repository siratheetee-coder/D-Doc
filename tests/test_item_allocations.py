# -*- coding: utf-8 -*-
"""ระยะ 2 ฝั่งการเงิน: หมวดในทะเบียนคุมเงินบอกว่าจัดสรรให้โครงการไหนบ้าง

แถบสามสีของแต่ละหมวด: จ่ายแล้ว / รอใช้ในโครงการ / ยังไม่จัดสรรให้โครงการ
(คำที่เจ้าของเลือก ห้ามเปลี่ยนเป็น "ยังไม่ได้จัดให้ใคร")

ตัวอย่างหลักตรงกับภาพที่คุยกันไว้
  หมวดค่ากิจกรรมฯ มีเงิน 100,000 · จัดสรรให้กีฬาสี 30,000 ค่ายคุณธรรม 25,000 · กีฬาสีจ่ายไป 8,000
  -> จ่ายแล้ว 8,000 · รอใช้ในโครงการ 47,000 · ยังไม่จัดสรรให้โครงการ 45,000 · รวม 92,000 = เงินคงเหลือจริง
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_item_allocations.py
"""
import pathlib
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Project

try:
    from app.models import PlanBudget, PlanFunding, ProjectFunding
except ImportError:                                   # pragma: no cover
    PlanBudget = PlanFunding = ProjectFunding = None
pytestmark = pytest.mark.skipif(PlanFunding is None, reason="ยังไม่มีระบบจัดสรรงบให้โครงการ")

from app.services.project_money import item_allocations

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2570


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close(); eng.dispose()


def _setup(db, opening=100000):
    acc = FinanceAccount(name="เงินอุดหนุน")
    db.add(acc); db.flush()
    act = AccountItem(account_id=acc.id, fiscal_year=FY, name="ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน",
                      opening_balance=opening)
    db.add(act); db.flush()
    plan = PlanBudget(year=2569, mode="academic", start_date=datetime(2026, 5, 1),
                      end_date=datetime(2027, 4, 30))
    db.add(plan); db.flush()
    sport = Project(name="กีฬาสี", budget=30000, plan_year=2569)
    camp = Project(name="ค่ายคุณธรรม", budget=25000, plan_year=2569)
    db.add_all([sport, camp]); db.flush()
    return acc, act, plan, sport, camp


def _allocate(db, plan, item, project, amount, key=None):
    f = PlanFunding(plan_id=plan.id, source_key=key or f"t:{item.id}:{project.id}", kind="opening",
                    name=item.name, amount=amount, account_item_id=item.id)
    db.add(f); db.flush()
    db.add(ProjectFunding(project_id=project.id, funding_id=f.id, amount=amount)); db.flush()


def _pay(db, acc, item, amount, project=None):
    t = FinanceTxn(account_id=acc.id, fiscal_year=FY, kind="out", amount=amount, item_id=item.id,
                   project_id=project.id if project else None, date=datetime(2026, 11, 1))
    db.add(t); db.flush()
    return t


def _rows(db, *items, level_of=None):
    """แถวหมวดแบบเดียวกับหน้าทะเบียนคุมเงิน (ยอดคงเหลือ = ยกมา + รับ - จ่าย รวมลูก)"""
    db.expire_all()
    level_of = level_of or {}
    out = []
    for it in items:
        kids = [k for k in items if level_of.get(k.id) == 1 and k.parent_id == it.id]
        fam = [it] + kids if level_of.get(it.id, 0) == 0 else [it]
        tin = sum(t.amount for f in fam for t in f.account.txns if t.item_id == f.id and t.kind == "in")
        tout = sum(t.amount for f in fam for t in f.account.txns if t.item_id == f.id and t.kind == "out")
        opening = sum(f.opening_balance or 0 for f in fam)
        out.append({"it": it, "level": level_of.get(it.id, 0), "tin": tin, "tout": tout,
                    "remain": round(opening + tin - tout, 2)})
    return out


def _txn_project(db):
    return {t.id: db.get(Project, t.project_id) for t in db.query(FinanceTxn).all() if t.project_id}


# ---------------- ตัวอย่างหลัก ----------------
def test_the_example_we_agreed_on(db):
    acc, act, plan, sport, camp = _setup(db)
    _allocate(db, plan, act, sport, 30000)
    _allocate(db, plan, act, camp, 25000)
    _pay(db, acc, act, 8000, sport)
    al = item_allocations(db, _rows(db, act), _txn_project(db))[act.id]
    assert al["paid"] == 8000
    assert al["waiting"] == 47000, "รอใช้ในโครงการ = (30,000 - 8,000) + 25,000"
    assert al["free"] == 45000, "ยังไม่จัดสรรให้โครงการ"
    assert al["remain"] == 92000
    assert al["waiting"] + al["free"] == al["remain"], "สองส่วนรวมกันต้องเท่าเงินคงเหลือจริง"
    assert [p["project"].name for p in al["projects"]] == ["กีฬาสี", "ค่ายคุณธรรม"]
    assert al["projects"][0]["used"] == 8000


def test_category_without_any_allocation_shows_nothing(db):
    acc, act, plan, sport, camp = _setup(db)
    _pay(db, acc, act, 500)
    assert item_allocations(db, _rows(db, act), _txn_project(db)) == {}


def test_spending_outside_projects_lowers_free_money_not_project_money(db):
    acc, act, plan, sport, camp = _setup(db)
    _allocate(db, plan, act, sport, 30000)
    _pay(db, acc, act, 5000)                               # จ่ายจากหมวด ไม่ผูกโครงการ
    al = item_allocations(db, _rows(db, act), _txn_project(db))[act.id]
    assert al["waiting"] == 30000, "เงินของกีฬาสีต้องยังรออยู่ครบ"
    assert al["free"] == 100000 - 5000 - 30000


def test_spending_reached_through_a_memo_counts_for_the_project(db):
    """จ่ายผ่านบันทึกขอเบิกจ่าย (รายการเงินไม่ได้ผูกโครงการตรง) ต้องนับให้โครงการด้วย"""
    acc, act, plan, sport, camp = _setup(db)
    _allocate(db, plan, act, sport, 30000)
    m = DisburseMemo(fiscal_year=FY, subject="ซื้อป้าย", amount=8000, account_id=acc.id,
                     item_id=act.id, project_id=sport.id)
    db.add(m); db.flush()
    t = _pay(db, acc, act, 8000)
    t.disburse_id = m.id; db.flush()
    from app.routers.finance import _txn_projects
    al = item_allocations(db, _rows(db, act), _txn_projects(db, [t]))[act.id]
    assert al["projects"][0]["used"] == 8000 and al["waiting"] == 22000


def test_project_spending_more_than_its_allocation_does_not_eat_other_projects_share(db):
    acc, act, plan, sport, camp = _setup(db)
    _allocate(db, plan, act, sport, 30000)
    _allocate(db, plan, act, camp, 25000)
    _pay(db, acc, act, 35000, sport)                       # เกินที่จัดสรรให้ 5,000
    al = item_allocations(db, _rows(db, act), _txn_project(db))[act.id]
    sport_row = [p for p in al["projects"] if p["project"].id == sport.id][0]
    assert sport_row["used"] == 30000, "นับใช้จากส่วนที่จัดสรรได้ไม่เกินที่จัดสรร"
    assert al["waiting"] == 25000, "ส่วนของค่ายคุณธรรมยังรออยู่ครบ"
    assert al["free"] == 100000 - 35000 - 25000


def test_allocating_more_than_the_money_in_the_category_goes_negative(db):
    """จัดสรรจากเงินอุดหนุนที่ยังไม่เข้า หน้าเว็บต้องเตือน ไม่ใช่โชว์ศูนย์เฉย ๆ"""
    acc, act, plan, sport, camp = _setup(db, opening=20000)
    _allocate(db, plan, act, sport, 30000)
    _allocate(db, plan, act, camp, 25000)
    al = item_allocations(db, _rows(db, act), _txn_project(db))[act.id]
    assert al["free"] == 20000 - 55000


def test_parent_category_adds_up_its_children(db):
    acc, act, plan, sport, camp = _setup(db, opening=0)
    parent = AccountItem(account_id=acc.id, fiscal_year=FY, name="เงินอุดหนุนรายหัว", opening_balance=0)
    db.add(parent); db.flush()
    k1 = AccountItem(account_id=acc.id, fiscal_year=FY, name="ค่าจัดการเรียนการสอน",
                     parent_id=parent.id, opening_balance=60000)
    k2 = AccountItem(account_id=acc.id, fiscal_year=FY, name="ค่ากิจกรรม",
                     parent_id=parent.id, opening_balance=40000)
    db.add_all([k1, k2]); db.flush()
    _allocate(db, plan, k1, sport, 10000)
    _allocate(db, plan, k2, camp, 5000)
    rows = _rows(db, parent, k1, k2, level_of={parent.id: 0, k1.id: 1, k2.id: 1})
    out = item_allocations(db, rows, _txn_project(db))
    assert out[parent.id]["waiting"] == 15000 and out[parent.id]["remain"] == 100000
    assert {p["project"].name for p in out[parent.id]["projects"]} == {"กีฬาสี", "ค่ายคุณธรรม"}
    assert out[k1.id]["waiting"] == 10000 and out[k2.id]["waiting"] == 5000


def test_payments_from_another_category_do_not_count(db):
    acc, act, plan, sport, camp = _setup(db)
    other = AccountItem(account_id=acc.id, fiscal_year=FY, name="ค่าจัดการเรียนการสอน")
    db.add(other); db.flush()
    _allocate(db, plan, act, sport, 30000)
    _pay(db, acc, other, 8000, sport)                      # จ่ายให้กีฬาสีแต่จากอีกหมวด
    al = item_allocations(db, _rows(db, act, other), _txn_project(db))[act.id]
    assert al["projects"][0]["used"] == 0 and al["waiting"] == 30000


# ---------------- หน้าเว็บ ----------------
def test_ledger_uses_the_owners_words_and_links_to_projects():
    html = (ROOT / "app/templates/finance_ledger.html").read_text(encoding="utf-8")
    for want in ("จ่ายแล้ว", "รอใช้ในโครงการ", "ยังไม่จัดสรรให้โครงการ", "/projects/{{ pj.project.id }}",
                 "จัดสรรเกินเงินที่เหลือจริง"):
        assert want in html, want
    assert "ยังไม่ได้จัดให้ใคร" not in html, "เจ้าของบอกว่าคำนี้งง"


def test_http_ledger_page_renders_the_bar_with_real_data():
    """เทสต์ที่อ่านแค่ข้อความในเทมเพลตผ่านได้ทั้งที่หน้าจริงพัง (เคยเจอ endif เกินมาหนึ่งตัว)
    จึงต้องเปิดหน้าจริงที่มีข้อมูลการจัดสรร ให้ส่วนแถบสามสีได้ทำงานจริง"""
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    from app.tenancy import session_for
    auth_mod.authenticate = lambda u, p: {"uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
                                          "display_name": "t", "must_change": False, "is_owner": True}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {"is_owner": True, "modules": "", "active": True,
                                               "welcomed": True}
    mark = "ทดสอบแถบจัดสรร_"
    s = session_for(1)
    acc = FinanceAccount(name=mark + "เงินอุดหนุน"); s.add(acc); s.flush()
    act = AccountItem(account_id=acc.id, fiscal_year=FY, name=mark + "ค่ากิจกรรม", opening_balance=100000)
    low = AccountItem(account_id=acc.id, fiscal_year=FY, name=mark + "หมวดเงินน้อย", opening_balance=1000)
    s.add_all([act, low]); s.flush()
    plan = PlanBudget(year=2599, mode="budget", start_date=datetime(2055, 10, 1), end_date=datetime(2056, 9, 30))
    s.add(plan); s.flush()
    sport = Project(name=mark + "กีฬาสี", budget=30000, plan_year=2599)
    s.add(sport); s.flush()
    for item, amt in ((act, 30000), (low, 5000)):
        f = PlanFunding(plan_id=plan.id, source_key=f"{mark}{item.id}", kind="other", name=item.name,
                        amount=amt, account_item_id=item.id)
        s.add(f); s.flush()
        s.add(ProjectFunding(project_id=sport.id, funding_id=f.id, amount=amt))
    s.add(FinanceTxn(account_id=acc.id, fiscal_year=FY, kind="out", amount=8000, item_id=act.id,
                     project_id=sport.id, date=datetime(2026, 11, 1)))
    s.commit()
    ids = dict(acc=acc.id, plan=plan.id, sport=sport.id)
    try:
        c = TestClient(app)
        assert c.post("/login", data={"username": "t", "password": "x"},
                      follow_redirects=False).status_code in (302, 303)
        r = c.get(f"/finance/accounts/{ids['acc']}?year={FY}")
        assert r.status_code == 200, r.status_code
        assert "รอใช้ในโครงการ 22,000.00" in r.text and "ยังไม่จัดสรรให้โครงการ 70,000.00" in r.text
        assert "จัดสรรเกินเงินที่เหลือจริง 4,000.00" in r.text
        assert f'href="/projects/{ids["sport"]}"' in r.text
    finally:
        s.rollback()
        s.query(FinanceTxn).filter_by(account_id=ids["acc"]).delete()
        s.query(ProjectFunding).filter_by(project_id=ids["sport"]).delete()
        s.query(PlanFunding).filter_by(plan_id=ids["plan"]).delete()
        s.query(PlanBudget).filter_by(id=ids["plan"]).delete()
        s.query(Project).filter_by(id=ids["sport"]).delete()
        s.query(AccountItem).filter_by(account_id=ids["acc"]).delete()
        s.query(FinanceAccount).filter_by(id=ids["acc"]).delete()
        s.commit(); s.close()
