# -*- coding: utf-8 -*-
"""กล่องสรุปหน้าโครงการหลัก: นับเฉพาะโครงการที่รู้หมวดเงินแล้ว ทั้งงบและเงินมาจากชุดเดียวกัน

เจอจริงที่บ้านหินลาด: โครงการอาหารกลางวันยังไม่เคยจ่ายในระบบ ถ้านับงบแต่ไม่นับเงิน จะขึ้นว่ารอเงินเกินจริง 254,400
รัน: .venv\Scripts\python.exe -m pytest tests/test_project_cash.py
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Project
from app.services.project_money import project_cash

FY = 2570


@pytest.fixture()
def db():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    yield s
    s.close()


def test_only_projects_with_a_known_category_are_counted(db):
    acc = FinanceAccount(name="เงินอุดหนุน"); db.add(acc); db.flush()
    teach = AccountItem(account_id=acc.id, fiscal_year=FY, name="ค่าจัดการเรียนการสอน", opening_balance=38387.48)
    db.add(teach); db.flush()
    staff = Project(name="พัฒนาครู", budget=20946.15, plan_year=2569, spent_before=1023.15)
    lunch = Project(name="อาหารกลางวัน", budget=513600, plan_year=2569, spent_before=259200)
    done = Project(name="จบแล้ว", budget=2000, plan_year=2569, spent_before=2000)
    db.add_all([staff, lunch, done]); db.flush()
    memo = DisburseMemo(fiscal_year=FY, subject="อบรม", amount=18800, account_id=acc.id, item_id=teach.id,
                        project_id=staff.id)
    db.add(memo); db.flush()
    db.add(FinanceTxn(account_id=acc.id, item_id=teach.id, fiscal_year=FY, kind="out", amount=18800,
                      date=datetime(2026, 10, 20), disburse_id=memo.id))
    db.flush()
    c = project_cash(db, [staff, lunch, done], FY)
    assert c["n"] == 1 and c["need"] == 1123.0, "พัฒนาครูเหลือ 20,946.15 - 1,023.15 - 18,800"
    assert c["skipped"] == 1, "อาหารกลางวันยังไม่รู้หมวด ไม่นับ แต่บอกว่ายังไม่นับ"
    assert [r["item"].id for r in c["rows"]] == [teach.id] and c["cash"] == 19587.48
    assert c["gap"] == round(1123 - 19587.48, 2)
