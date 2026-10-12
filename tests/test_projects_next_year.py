# -*- coding: utf-8 -*-
"""ระยะ 4: ปิดปีแผน ยกโครงการที่ทำต่อไปปีถัดไป

เรื่องเงินมีอยู่แล้ว (ยกยอดเงินในหน้าหลักการเงิน และนำเงินเหลือเข้าแผนใหม่)
ส่วนที่ขาดคือโครงการ: เดิมต้องพิมพ์โครงการปีใหม่ทีละโครงการ หรือย้ายปีโครงการเดิม
(ซึ่งย้ายประวัติการใช้เงินทั้งหมดไปด้วย ผิด) หน้านี้สร้างโครงการใหม่ในปีถัดไป ยอดใช้ไปเริ่มที่ 0
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_projects_next_year.py
"""
import pathlib
from datetime import datetime

import pytest

from app.models import DisburseMemo, Project, ProjectBudgetRevision

ROOT = pathlib.Path(__file__).resolve().parents[1]
YEAR = 2594
MARK = "ทดสอบยกโครงการ_"


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
    """ปี YEAR: กีฬาสี (ใช้ไป 12,000 มียอดตั้งต้น มีการปรับงบ) ค่ายคุณธรรม พัฒนาครู
    ปี YEAR+1 มี "พัฒนาครู" อยู่แล้ว"""
    from app.tenancy import session_for
    s = session_for(1)
    sport = Project(name=MARK + "กีฬาสี", budget=30000, plan_year=YEAR, responsible="ฝ่ายกิจการนักเรียน",
                    spent_before=4000, spent_before_at=datetime.now())
    camp = Project(name=MARK + "ค่ายคุณธรรม", budget=25000, plan_year=YEAR)
    teach = Project(name=MARK + "พัฒนาครู", budget=15000, plan_year=YEAR)
    teach_next = Project(name=MARK + "พัฒนาครู", budget=18000, plan_year=YEAR + 1)
    s.add_all([sport, camp, teach, teach_next]); s.flush()
    s.add(ProjectBudgetRevision(project_id=sport.id, seq=1, amount=32000, reason="ปรับกลางปี"))
    s.add(DisburseMemo(fiscal_year=2570, subject=MARK + "ซื้อป้าย", amount=8000, project_id=sport.id))
    s.commit()
    w = dict(s=s, sport=sport.id, camp=camp.id, teach=teach.id)
    yield w
    s.rollback()
    ids = [p.id for p in s.query(Project).filter(Project.name.like(MARK + "%"))]
    s.query(DisburseMemo).filter(DisburseMemo.subject.like(MARK + "%")).delete(synchronize_session=False)
    s.query(ProjectBudgetRevision).filter(ProjectBudgetRevision.project_id.in_(ids)).delete(
        synchronize_session=False)
    s.query(Project).filter(Project.id.in_(ids)).delete(synchronize_session=False)
    s.commit(); s.close()


def _next(w, name):
    w["s"].expire_all()
    return w["s"].query(Project).filter_by(name=MARK + name, plan_year=YEAR + 1).all()


def test_page_opens_and_lists_the_year(client, world):
    r = client.get(f"/projects/next-year?year={YEAR}")
    assert r.status_code == 200, r.status_code        # ต้องไม่ถูกอ่านเป็นเลขโครงการ
    assert MARK + "กีฬาสี" in r.text and "มีในปี" in r.text
    for step in ("เงินในบัญชี", "เลือกโครงการที่ทำต่อ", "นำเงินเหลือเข้าแผน"):
        assert step in r.text, step


def test_copies_only_ticked_projects_with_the_new_budget_and_a_clean_slate(client, world):
    r = client.post("/projects/next-year", data={
        "year": str(YEAR), "copy": [str(world["sport"])],
        f"budget_{world['sport']}": "35,000", f"budget_{world['camp']}": "25000"},
        follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers["location"]
    new = _next(world, "กีฬาสี")
    assert len(new) == 1
    p = new[0]
    assert p.budget == 35000 and p.responsible == "ฝ่ายกิจการนักเรียน" and p.active
    assert (p.spent_before or 0) == 0, "ยอดตั้งต้นของปีเก่าห้ามตามมา"
    assert not p.revisions, "ประวัติปรับงบของปีเก่าห้ามตามมา"
    from app.services.budget import project_spent
    assert project_spent(p) == 0, "ปีใหม่ยอดใช้ไปเริ่มที่ 0"
    assert _next(world, "ค่ายคุณธรรม") == [], "ไม่ได้ติ๊กต้องไม่สร้าง"


def test_old_year_is_untouched(client, world):
    client.post("/projects/next-year", data={"year": str(YEAR), "copy": [str(world["sport"])],
                                             f"budget_{world['sport']}": "35000"}, follow_redirects=False)
    world["s"].expire_all()
    old = world["s"].get(Project, world["sport"])
    assert old.plan_year == YEAR and old.spent_before == 4000 and old.revisions


def test_never_duplicates_a_project_that_already_exists_next_year(client, world):
    client.post("/projects/next-year", data={"year": str(YEAR), "copy": [str(world["teach"])],
                                             f"budget_{world['teach']}": "15000"}, follow_redirects=False)
    assert len(_next(world, "พัฒนาครู")) == 1
    for _ in range(2):                                    # กดซ้ำ
        client.post("/projects/next-year", data={"year": str(YEAR), "copy": [str(world["camp"])],
                                                 f"budget_{world['camp']}": "25000"}, follow_redirects=False)
    assert len(_next(world, "ค่ายคุณธรรม")) == 1


def test_bad_budget_saves_nothing(client, world):
    r = client.post("/projects/next-year", data={
        "year": str(YEAR), "copy": [str(world["sport"]), str(world["camp"])],
        f"budget_{world['sport']}": "35000", f"budget_{world['camp']}": "-1"}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert _next(world, "กีฬาสี") == [] and _next(world, "ค่ายคุณธรรม") == []


def test_projects_list_offers_it_near_the_end_of_the_year(world):
    from app.routers.pages import _suggest_next_year
    s = world["s"]
    rows = s.query(Project).filter(Project.plan_year == YEAR).all()
    assert not _suggest_next_year(s, YEAR, rows), "ปีถัดไปมีโครงการแล้ว ไม่ต้องชวน"
    old = Project(name=MARK + "โครงการปีเก่ามาก", budget=1000, plan_year=2530)
    s.add(old); s.commit()
    assert _suggest_next_year(s, 2530, [old]) == "ended", "ปีที่จบไปแล้วและปีถัดไปว่าง ต้องชวน และบอกว่าสิ้นปีแล้ว"
    assert not _suggest_next_year(s, 2530, []), "ไม่มีโครงการ ไม่ต้องชวน"


def test_entry_button_is_on_the_projects_page():
    html = (ROOT / "app/templates/projects.html").read_text(encoding="utf-8")
    assert "/projects/next-year?year=" in html


# ---------------- คำที่เจ้าของเลือก ----------------
def test_owner_wording_for_spending_before_using_the_system():
    """เจ้าของให้ใช้ "ใช้ไปก่อนเริ่มใช้ระบบ" แทน "ใช้ไปก่อนใช้ระบบ" """
    for rel in ("app/templates/projects_start.html", "app/templates/project_detail.html",
                "app/services/project_summary.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert "ใช้ไปก่อนเริ่มใช้ระบบ" in txt, rel
        assert "ใช้ไปก่อนใช้ระบบ" not in txt, rel
