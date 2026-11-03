# -*- coding: utf-8 -*-
"""เพิ่มโครงการจาก pop-up ในช่องเลือกโครงการ (ฟอร์มบันทึกรับ-จ่าย/ขอเบิกจ่าย)
กรอกได้ครบเหมือนหน้าโครงการ + จัดสรรงบจากแผนงบ (หน้างบที่ใช้จัดทำแผน) ในคราวเดียว
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_quick_project.py
"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _projects():
    from app.models import Project
    db = _db()
    try:
        return [(p.name, p.plan_year, p.budget, p.responsible, p.active) for p in db.query(Project).order_by(Project.id)]
    finally:
        db.close()


def _cur():
    from app.services.budget import current_plan_year
    from app.models import School
    db = _db()
    try:
        return current_plan_year(db.query(School).first())
    finally:
        db.close()


def test_create_with_details(env):
    cur = _cur()
    r = env.post("/finance/projects/quick", data={"name": "  ทัศนศึกษา   ป.6 ", "budget": "8000", "plan_year": str(cur),
                                                  "responsible": "ฝ่ายวิชาการ", "fund_1": "6000"})
    d = r.json()
    assert r.status_code == 200 and d["created"] is True and d["label"] == f"ทัศนศึกษา ป.6 · ปีแผน {cur}"
    assert _projects()[-1] == ("ทัศนศึกษา ป.6", cur, 8000.0, "ฝ่ายวิชาการ", True)
    n = len(_projects())
    again = env.post("/finance/projects/quick", data={"name": "ทัศนศึกษา ป.6", "plan_year": str(cur)}).json()
    assert again["id"] == d["id"] and again["created"] is False and "อยู่แล้ว" in again["message"]
    assert len(_projects()) == n


def test_page_wiring(env):
    from app.models import FinanceAccount
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา", "deposit_type": "bank", "eb_slot": "3.5"})
    db = _db()
    try:
        aid = db.query(FinanceAccount).filter_by(name="เงินรายได้สถานศึกษา").one().id
    finally:
        db.close()
    html = env.get(f"/finance/accounts/{aid}?year={FY}").text
    assert "data-quick-project" in html and "/static/quick-project.js" in html and "qp-box" not in html
    assert "data-quick-project" in env.get(f"/finance/disburse?year={FY}").text


def test_form_data(env):
    from app.models import Department
    db = _db()
    try:
        db.add_all([Department(name="ฝ่ายวิชาการ"), Department(name="ฝ่ายงบประมาณ")]); db.commit()
    finally:
        db.close()
    d = env.get("/finance/projects/quick-form").json()
    cur = _cur()
    assert d["plan_year"] == cur and cur in d["years"] and "sources" not in d, "ไม่มีช่องจัดสรรเงินแล้ว"
    assert d["departments"] == ["ฝ่ายงบประมาณ", "ฝ่ายวิชาการ"]
    assert env.get("/finance/projects/quick-form?year=99999").json()["plan_year"] == cur


def test_validation_and_defaults(env):
    cur = _cur()
    assert env.post("/finance/projects/quick", data={"name": "   "}).status_code == 400
    assert env.post("/finance/projects/quick", data={"name": "ก" * 301}).status_code == 400
    env.post("/finance/projects/quick", data={"name": "งบติดลบ", "budget": "-50", "plan_year": "abc"})
    assert _projects()[-1][:3] == ("งบติดลบ", cur, 0.0)
    env.post("/finance/projects/quick", data={"name": "ปีเพี้ยน", "plan_year": "99999"})
    assert _projects()[-1][:2] == ("ปีเพี้ยน", cur)
    other = env.post("/finance/projects/quick", data={"name": "งบติดลบ", "plan_year": str(cur + 1)}).json()
    assert other["created"] is True, "คนละปีแผน สร้างใหม่ได้"
    r = env.post("/finance/projects/quick", data={"name": "ช่องว่าง", "plan_year": str(cur + 1), "fund_1": "0", "fund_2": ""})
    assert r.status_code == 200, "ช่องจัดสรรเป็น 0/ว่าง ไม่ต้องมีแผนงบ"


def test_new_project_usable_in_txn(env):
    from app.models import FinanceAccount, FinanceTxn
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา", "deposit_type": "bank", "eb_slot": "3.5"})
    db = _db()
    try:
        aid = db.query(FinanceAccount).filter_by(name="เงินรายได้สถานศึกษา").one().id
    finally:
        db.close()
    pid = env.post("/finance/projects/quick", data={"name": "ค่ารถทัศนศึกษา"}).json()["id"]
    env.post(f"/finance/accounts/{aid}/txn", data={"kind": "out", "amount": "500", "date": "05/11/2569",
             "fiscal_year": FY, "note": "ค่ารถ", "project_id": str(pid)})
    r = env.post(f"/finance/accounts/{aid}/txn", data={"kind": "out", "amount": "1", "date": "05/11/2569",
                 "fiscal_year": FY, "note": "ไม่ผูก", "project_id": "__new"}, follow_redirects=False)
    assert r.status_code == 303
    db = _db()
    try:
        assert db.query(FinanceTxn).filter_by(note="ค่ารถ").one().project_id == pid
        assert db.query(FinanceTxn).filter_by(note="ไม่ผูก").one().project_id is None
    finally:
        db.close()
