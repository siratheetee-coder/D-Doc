# -*- coding: utf-8 -*-
"""หน้าตั้งยอดตั้งต้น: เลือก "ใช้เงินจาก" แล้วระบบจัดสรรให้ = งบ - ใช้ไปก่อนเริ่มใช้ระบบ"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PlanBudget, PlanFunding, Project, ProjectFunding, School
from app.routers.pages import _start_rows, _start_save_funds, _start_sources


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(School(name="ทดสอบ"))
    plan = PlanBudget(year=2569, mode="academic", start_date=datetime(2026, 5, 16), end_date=datetime(2027, 5, 15))
    s.add(plan); s.flush()
    s.add(PlanFunding(plan_id=plan.id, source_key="other:1", kind="other", name="ค่าจัดการเรียนการสอน", amount=59141.98))
    s.add_all([Project(name="ค่ายวิชาการ", budget=30000, plan_year=2569, spent_before=10000),
               Project(name="ซ่อมพัสดุ", budget=25000, plan_year=2569, spent_before=4053.85),
               Project(name="กีฬาสี", budget=15000, plan_year=2569)])
    s.commit()
    yield s
    s.close()


def _rows(db):
    return {r["p"].id: r for r in _start_rows(db, 2569)}


def test_choosing_source_allocates_budget_minus_used_before(db):
    sid = db.query(PlanFunding).one().id
    rows = _rows(db)
    form = {f"fund_{pid}": str(sid) for pid in rows}
    assert _start_save_funds(db, 2569, rows, form) == 3
    got = {db.get(Project, a.project_id).name: a.amount for a in db.query(ProjectFunding)}
    assert got == {"ค่ายวิชาการ": 20000, "ซ่อมพัสดุ": 20946.15, "กีฬาสี": 15000}
    src = _start_sources(db, 2569, _start_rows(db, 2569))[0]
    assert src["fixed"] == 0                       # ทุกโครงการแก้ได้ในหน้านี้


def test_unset_removes_and_over_allocation_is_refused(db):
    sid = db.query(PlanFunding).one().id
    rows = _rows(db)
    _start_save_funds(db, 2569, rows, {f"fund_{pid}": str(sid) for pid in rows})
    pid = next(p for p, r in rows.items() if r["p"].name == "กีฬาสี")
    _start_save_funds(db, 2569, _rows(db), {f"fund_{pid}": ""})
    assert not db.query(ProjectFunding).filter_by(project_id=pid).first()

    db.add(Project(name="โครงการใหญ่", budget=90000, plan_year=2569)); db.flush()
    rows = _rows(db)
    big = next(p for p, r in rows.items() if r["p"].name == "โครงการใหญ่")
    with pytest.raises(ValueError, match="เกินเงินที่มี"):
        _start_save_funds(db, 2569, rows, {f"fund_{big}": str(sid)})


def test_project_with_several_sources_is_left_alone(db):
    plan = db.query(PlanBudget).one()
    s1 = db.query(PlanFunding).one()
    s2 = PlanFunding(plan_id=plan.id, source_key="other:2", kind="other", name="เงินรายได้", amount=5000)
    db.add(s2); db.flush()
    pj = db.query(Project).filter_by(name="กีฬาสี").one()
    db.add_all([ProjectFunding(project_id=pj.id, funding_id=s1.id, amount=10000),
                ProjectFunding(project_id=pj.id, funding_id=s2.id, amount=5000)]); db.flush()
    rows = _rows(db)
    assert rows[pj.id]["multi"]
    _start_save_funds(db, 2569, rows, {f"fund_{pj.id}": str(s1.id)})
    assert db.query(ProjectFunding).filter_by(project_id=pj.id).count() == 2
    src = {s["id"]: s for s in _start_sources(db, 2569, list(rows.values()))}
    assert src[s1.id]["fixed"] == 10000 and src[s2.id]["fixed"] == 5000
