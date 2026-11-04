# -*- coding: utf-8 -*-
"""ทะเบียนคุมโครงการรายเดือน: จ่ายจริงแยกเดือนตามช่วงแผน บวกกันลงตัวกับ ใช้/กันงบ
รัน: .venv\Scripts\python.exe -m pytest tests/test_project_monthly.py
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import FinanceAccount, FinanceTxn, PlanBudget, Project, School
from app.services.project_monthly import build, months_of, xlsx


@pytest.fixture()
def db():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(School(name="ทดสอบ", project_year_mode="academic"))
    s.add(PlanBudget(year=2569, mode="academic", start_date=datetime(2026, 5, 16), end_date=datetime(2027, 5, 15)))
    s.commit()
    yield s
    s.close()


def test_months_follow_the_plan_period():
    ms = months_of(datetime(2026, 5, 16), datetime(2027, 5, 15))
    assert [lb for _, _, lb in ms][:2] == ["พ.ค. 69", "มิ.ย. 69"] and ms[-1][2] == "พ.ค. 70" and len(ms) == 13


def test_monthly_values_add_up_to_used(db):
    acc = FinanceAccount(name="เงินอุดหนุน"); db.add(acc); db.flush()
    a = Project(name="พัฒนาครู", budget=20946.15, plan_year=2569, spent_before=1023.15, responsible="ฝ่ายบุคคล")
    b = Project(name="กีฬาสี", budget=10000, plan_year=2569, responsible="ฝ่ายวิชาการ")
    db.add_all([a, b]); db.flush()
    db.add_all([FinanceTxn(account_id=acc.id, fiscal_year=2570, kind="out", amount=18000, date=datetime(2026, 10, 20), project_id=a.id),
                FinanceTxn(account_id=acc.id, fiscal_year=2570, kind="out", amount=800, date=datetime(2026, 11, 2), project_id=a.id),
                FinanceTxn(account_id=acc.id, fiscal_year=2569, kind="out", amount=500, date=datetime(2026, 3, 1), project_id=b.id)])
    db.flush()
    d = build(db, 2569, [a, b])
    ra = next(r for g in d["groups"] for r in g["rows"] if r["p"].id == a.id)
    i_oct = [lb for _, _, lb in d["months"]].index("ต.ค. 69")
    assert ra["months"][i_oct] == 18000 and ra["months"][i_oct + 1] == 800
    assert round(ra["before"] + sum(ra["months"]) + ra["other"] + ra["waiting"], 2) == ra["used"] == 19823.15
    rb = next(r for g in d["groups"] for r in g["rows"] if r["p"].id == b.id)
    assert rb["other"] == 500 and d["has_other"], "จ่ายก่อนช่วงแผน แยกช่องนอกช่วงแผน ยอดรวมยังตรง"
    assert [g["name"] for g in d["groups"]] == ["ฝ่ายบุคคล", "ฝ่ายวิชาการ"]
    assert d["total"]["used"] == round(ra["used"] + rb["used"], 2)
    wb = xlsx("ทดสอบ", "ปีการศึกษา", 2569, d)
    assert wb.active.max_row >= 8
