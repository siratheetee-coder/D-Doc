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


def _plan(year, sources):
    """แผนงบปี year + รายการเงินอื่น ๆ [(name, amount)] คืน id ของรายการเงิน"""
    from app.models import PlanBudget, PlanFunding
    db = _db()
    try:
        p = PlanBudget(year=year, mode="budget", start_date=datetime(year - 544, 10, 1), end_date=datetime(year - 543, 9, 30))
        db.add(p); db.flush()
        ids = []
        for i, (n, a) in enumerate(sources):
            s = PlanFunding(plan_id=p.id, source_key=f"other:test:{i}", kind="other", name=n, amount=a, payload="{}")
            db.add(s); db.flush(); ids.append(s.id)
        db.commit()
        return ids
    finally:
        db.close()


def _alloc(pid):
    from app.models import ProjectFunding
    db = _db()
    try:
        return {a.funding_id: a.amount for a in db.query(ProjectFunding).filter_by(project_id=pid)}
    finally:
        db.close()


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


def test_form_data_without_and_with_plan(env):
    from app.models import Department
    db = _db()
    try:
        db.add_all([Department(name="ฝ่ายวิชาการ"), Department(name="ฝ่ายงบประมาณ")]); db.commit()
    finally:
        db.close()
    d = env.get("/finance/projects/quick-form").json()
    cur = _cur()
    assert d["plan_year"] == cur and cur in d["years"] and d["has_plan"] is False and d["sources"] == []
    assert d["departments"] == ["ฝ่ายงบประมาณ", "ฝ่ายวิชาการ"] and d["plan_link"] == f"/plan-budget/{cur}"
    ids = _plan(cur, [("เงินบริจาค", 10000), ("เงินหมด", 0)])
    d = env.get(f"/finance/projects/quick-form?year={cur}").json()
    assert d["has_plan"] and [s["id"] for s in d["sources"]] == [ids[0]], "ไม่แสดงรายการที่ไม่เหลือให้จัดสรร"
    assert d["sources"][0] == {"id": ids[0], "name": "เงินบริจาค", "kind": "เงินอื่น ๆ", "available": 10000.0}
    assert env.get("/finance/projects/quick-form?year=99999").json()["plan_year"] == cur


def test_create_with_details_and_allocation(env):
    cur = _cur()
    fid, fid2 = _plan(cur, [("เงินบริจาค", 10000), ("เงินระดมทรัพย์", 3000)])
    r = env.post("/finance/projects/quick", data={"name": "  ทัศนศึกษา   ป.6 ", "budget": "8000", "plan_year": str(cur),
                                                  "responsible": "ฝ่ายวิชาการ", f"fund_{fid}": "6000", f"fund_{fid2}": "2000"})
    d = r.json()
    assert r.status_code == 200 and d["created"] is True and d["label"] == f"ทัศนศึกษา ป.6 · ปีแผน {cur}"
    assert d["link"] == f"/projects/{d['id']}"
    assert _projects()[-1] == ("ทัศนศึกษา ป.6", cur, 8000.0, "ฝ่ายวิชาการ", True)
    assert _alloc(d["id"]) == {fid: 6000.0, fid2: 2000.0}
    left = {s["id"]: s["available"] for s in env.get(f"/finance/projects/quick-form?year={cur}").json()["sources"]}
    assert left == {fid: 4000.0, fid2: 1000.0}, "เงินที่เหลือให้จัดสรรลดลงตามที่จัดสรร"
    # ชื่อซ้ำปีเดียวกัน = ใช้โครงการเดิม ไม่สร้างซ้ำ ไม่จัดสรรเพิ่ม
    n = len(_projects())
    again = env.post("/finance/projects/quick", data={"name": "ทัศนศึกษา ป.6", "plan_year": str(cur), f"fund_{fid}": "100"}).json()
    assert again["id"] == d["id"] and again["created"] is False and "อยู่แล้ว" in again["message"]
    assert len(_projects()) == n and _alloc(d["id"]) == {fid: 6000.0, fid2: 2000.0}


def test_allocation_errors_roll_back_project(env):
    cur = _cur()
    (fid,) = _plan(cur, [("เงินบริจาค", 5000)])
    n = len(_projects())
    r = env.post("/finance/projects/quick", data={"name": "เกินงบโครงการ", "budget": "1000", "plan_year": str(cur), f"fund_{fid}": "2000"})
    assert r.status_code == 400 and "เกินงบโครงการ" in r.json()["detail"]
    r = env.post("/finance/projects/quick", data={"name": "เกินเงินแผน", "budget": "9000", "plan_year": str(cur), f"fund_{fid}": "6000"})
    assert r.status_code == 400 and "เกินวงเงิน" in r.json()["detail"]
    r = env.post("/finance/projects/quick", data={"name": "ไม่มีแผน", "budget": "9000", "plan_year": str(cur + 1), "fund_1": "10"})
    assert r.status_code == 400 and "ยังไม่ได้กำหนดงบที่ใช้จัดทำแผน" in r.json()["detail"]
    r = env.post("/finance/projects/quick", data={"name": "ผิดแผน", "budget": "9000", "plan_year": str(cur), "fund_99999": "10"})
    assert r.status_code == 400
    assert len(_projects()) == n, "จัดสรรไม่ผ่าน = ไม่สร้างโครงการค้างไว้"
    ok = env.post("/finance/projects/quick", data={"name": "ไม่จัดสรร", "budget": "9000", "plan_year": str(cur), f"fund_{fid}": "0"})
    assert ok.status_code == 200 and _alloc(ok.json()["id"]) == {}, "ช่องจัดสรร 0 = ไม่จัดสรร"


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
