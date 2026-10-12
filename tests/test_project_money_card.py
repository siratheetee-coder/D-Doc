# -*- coding: utf-8 -*-
"""หน้าโครงการ: งบโครงการ กับ เงินที่จัดสรรแล้ว เป็นคนละตัวเลขโดยตั้งใจ (docs/plan-funding.md)

เจ้าของเลือกคงสองตัวเลขไว้ แต่ให้อ่านง่าย: "งบ 30,000 · จัดสรรเงินแล้ว 20,000 · ยังไม่ได้จัดสรร 10,000"
(เดิมใช้ "ยังขาด" เจ้าของบอกว่างง ฟังเหมือนโรงเรียนขาดเงิน)
และบอกว่าเงินมาจากหมวดไหน กดไปทะเบียนคุมเงินได้
ยอด "ใช้ไปแล้ว" กับ "จ่ายจริงตามทะเบียนคุมเงิน" เดิมอยู่คนละที่ของหน้า อ่านแล้วงงว่าตัวไหนจริง
ตอนนี้อยู่ด้วยกัน และบอกส่วนที่ "ทำเรื่องแล้วรอจ่าย" ให้เห็น
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_project_money_card.py
"""
import pathlib
from datetime import datetime

import pytest

from app.models import AccountItem, DisburseMemo, FinanceAccount, Project

try:
    from app.models import PlanBudget, PlanFunding, ProjectFunding
except ImportError:                                   # pragma: no cover
    PlanBudget = PlanFunding = ProjectFunding = None
pytestmark = pytest.mark.skipif(PlanFunding is None, reason="ยังไม่มีระบบจัดสรรงบให้โครงการ")

ROOT = pathlib.Path(__file__).resolve().parents[1]
YEAR = 2598                     # ปีที่ไม่มีใครใช้ ข้อมูลทดสอบจะไม่ชนกับข้อมูลจริง
MARK = "ทดสอบการ์ดเงินโครงการ_"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    auth_mod.authenticate = lambda u, p: {"uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
                                          "display_name": "t", "must_change": False, "is_owner": True}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {"is_owner": True, "modules": "", "active": True,
                                               "welcomed": True}
    c = TestClient(app)
    assert c.post("/login", data={"username": "t", "password": "x"},
                  follow_redirects=False).status_code in (302, 303)
    return c


@pytest.fixture
def world():
    """โครงการกีฬาสี งบ 30,000 · หมวดค่ากิจกรรม · แผนปี YEAR (ยังไม่จัดสรร)"""
    from app.tenancy import session_for
    s = session_for(1)
    acc = FinanceAccount(name=MARK + "เงินอุดหนุน"); s.add(acc); s.flush()
    item = AccountItem(account_id=acc.id, fiscal_year=2570, name=MARK + "ค่ากิจกรรม", opening_balance=100000)
    s.add(item); s.flush()
    plan = PlanBudget(year=YEAR, mode="budget", start_date=datetime(2054, 10, 1), end_date=datetime(2055, 9, 30))
    s.add(plan); s.flush()
    f = PlanFunding(plan_id=plan.id, source_key=MARK + "src", kind="other", name=item.name,
                    amount=100000, account_item_id=item.id)
    s.add(f); s.flush()
    pj = Project(name=MARK + "กีฬาสี", budget=30000, plan_year=YEAR)
    bare = Project(name=MARK + "โครงการปีอื่น", budget=5000, plan_year=YEAR + 1)
    s.add_all([pj, bare]); s.commit()
    w = dict(s=s, acc=acc.id, item=item.id, plan=plan.id, fund=f.id, pj=pj.id, bare=bare.id)
    yield w
    s.rollback()
    s.query(DisburseMemo).filter(DisburseMemo.subject.like(MARK + "%")).delete(synchronize_session=False)
    s.query(ProjectFunding).filter(ProjectFunding.project_id.in_([w["pj"], w["bare"]])).delete(
        synchronize_session=False)
    s.query(PlanFunding).filter_by(plan_id=w["plan"]).delete()
    s.query(PlanBudget).filter_by(id=w["plan"]).delete()
    s.query(Project).filter(Project.id.in_([w["pj"], w["bare"]])).delete(synchronize_session=False)
    s.query(AccountItem).filter_by(account_id=w["acc"]).delete()
    s.query(FinanceAccount).filter_by(id=w["acc"]).delete()
    s.commit(); s.close()


def _allocate(w, amount):
    s = w["s"]
    s.add(ProjectFunding(project_id=w["pj"], funding_id=w["fund"], amount=amount)); s.commit()


def test_partly_funded_project_says_how_much_is_still_missing(client, world):
    _allocate(world, 20000)
    html = client.get(f"/projects/{world['pj']}").text
    assert "จัดสรรเงินแล้ว <b>20,000.00</b>" in html
    assert "ยังไม่ได้จัดสรร <b>10,000.00</b>" in html
    assert f'href="/finance/accounts/{world["acc"]}?year=2570"' in html, "ต้องกดไปหมวดในทะเบียนคุมเงินได้"
    assert MARK + "ค่ากิจกรรม" in html


def test_fully_funded_project_says_so(client, world):
    _allocate(world, 30000)
    html = client.get(f"/projects/{world['pj']}").text
    assert "จัดสรรครบแล้ว" in html and "ยังไม่ได้จัดสรร <b>" not in html


def test_plan_in_use_but_nothing_allocated_points_to_where_to_do_it(client, world):
    html = client.get(f"/projects/{world['pj']}").text
    assert "จัดสรรเงินแล้ว <b>0.00</b>" in html and "ยังไม่ได้จัดสรร <b>30,000.00</b>" in html
    assert "ยังไม่ได้จัดสรรเงินให้โครงการนี้" in html


def test_the_confusing_word_is_gone():
    html = (ROOT / "app/templates/project_detail.html").read_text(encoding="utf-8")
    assert "ยังขาด <b>" not in html, 'เจ้าของบอกว่า "ยังขาด" งง ให้ใช้ "ยังไม่ได้จัดสรร"'


def test_school_not_using_allocation_sees_the_old_simple_page(client, world):
    html = client.get(f"/projects/{world['bare']}").text
    assert "จัดสรรเงินแล้ว" not in html and "ยังไม่ได้จัดสรร <b>" not in html
    assert "งบโครงการ" in html and "ใช้ไปแล้ว" in html and "คงเหลือ" in html


def test_spent_and_paid_are_shown_together_with_what_is_still_waiting(client, world):
    """ใช้ไปแล้ว รวมเรื่องที่ทำแล้วแต่ยังไม่จ่าย · ต้องบอกให้เห็นว่าส่วนไหนจ่ายจริงแล้ว"""
    _allocate(world, 20000)
    s = world["s"]
    s.add(DisburseMemo(fiscal_year=2570, subject=MARK + "ซื้อป้าย", amount=8000, project_id=world["pj"],
                       account_id=world["acc"], item_id=world["item"], status="อนุมัติ"))
    s.commit()
    html = client.get(f"/projects/{world['pj']}").text
    assert "จ่ายจริงตามทะเบียนคุมเงิน 0.00" in html
    assert "ทำเรื่องแล้วรอจ่าย 8,000.00" in html
    assert html.count("จ่ายจริงตามทะเบียนคุมเงิน") == 1, "ตัวเลขนี้ต้องอยู่ที่เดียว ไม่ซ้ำสองที่"
