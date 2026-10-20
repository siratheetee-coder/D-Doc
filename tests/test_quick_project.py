# -*- coding: utf-8 -*-
"""เพิ่มโครงการจากช่องเลือกโครงการในฟอร์มบันทึกรับ-จ่าย/ขอเบิกจ่าย
รัน: .venv\Scripts\python.exe -m pytest tests/test_quick_project.py
"""
from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


def _projects():
    import app.tenancy as tn
    from app.models import Project
    db = tn.session_for(next(iter(tn._engines)))
    try:
        return [(p.name, p.plan_year, p.budget, p.active) for p in db.query(Project).order_by(Project.id)]
    finally:
        db.close()


def test_quick_add_creates_selects_and_dedupes(env):
    from app.models import FinanceAccount
    import app.tenancy as tn
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา", "deposit_type": "bank", "eb_slot": "3.5"})
    db = tn.session_for(next(iter(tn._engines)))
    try:
        aid = db.query(FinanceAccount).filter_by(name="เงินรายได้สถานศึกษา").one().id
    finally:
        db.close()
    html = env.get(f"/finance/accounts/{aid}?year={FY}").text
    assert "data-quick-project" in html and "/static/quick-project.js" in html
    assert "data-quick-project" in env.get(f"/finance/disburse?year={FY}").text
    before = len(_projects())
    r = env.post("/finance/projects/quick", data={"name": "  ทัศนศึกษา   ป.6 ", "budget": "15000", "plan_year": "2570"})
    d = r.json()
    assert r.status_code == 200 and d["created"] is True and d["label"] == "ทัศนศึกษา ป.6 · ปีแผน 2570"
    assert _projects()[-1] == ("ทัศนศึกษา ป.6", 2570, 15000.0, True)
    again = env.post("/finance/projects/quick", data={"name": "ทัศนศึกษา ป.6", "budget": "1", "plan_year": "2570"}).json()
    assert again["id"] == d["id"] and again["created"] is False and len(_projects()) == before + 1, "ชื่อซ้ำปีเดียวกัน ไม่สร้างซ้ำ"
    other = env.post("/finance/projects/quick", data={"name": "ทัศนศึกษา ป.6", "plan_year": "2571"}).json()
    assert other["id"] != d["id"], "คนละปีแผน สร้างใหม่ได้"
    assert env.post("/finance/projects/quick", data={"name": "   "}).status_code == 400
    assert env.post("/finance/projects/quick", data={"name": "ก" * 301}).status_code == 400
    neg = env.post("/finance/projects/quick", data={"name": "งบติดลบ", "budget": "-50", "plan_year": "abc"}).json()
    from app.services.budget import current_plan_year
    from app.models import School
    db = tn.session_for(next(iter(tn._engines)))
    try:
        cur = current_plan_year(db.query(School).first())
    finally:
        db.close()
    assert _projects()[-1] == ("งบติดลบ", cur, 0.0, True) and neg["label"].endswith(f"ปีแผน {cur}")
    env.post("/finance/projects/quick", data={"name": "ปีเพี้ยน", "plan_year": "99999"})
    assert _projects()[-1][:2] == ("ปีเพี้ยน", cur), "ปีแผนนอกช่วง = ปีปัจจุบัน"

    # ใช้โครงการใหม่ได้ทันทีตอนบันทึกรายการ
    env.post(f"/finance/accounts/{aid}/txn", data={"kind": "out", "amount": "500", "date": "05/11/2569",
             "fiscal_year": FY, "note": "ค่ารถ", "project_id": str(d["id"])})
    from app.models import FinanceTxn
    db = tn.session_for(next(iter(tn._engines)))
    try:
        assert db.query(FinanceTxn).filter_by(note="ค่ารถ").one().project_id == d["id"]
    finally:
        db.close()
    # ค่าพิเศษ "__new" (ถ้า JS ไม่ทำงาน) ไม่ทำให้พัง = ไม่ผูกโครงการ
    r = env.post(f"/finance/accounts/{aid}/txn", data={"kind": "out", "amount": "1", "date": "05/11/2569",
                 "fiscal_year": FY, "note": "ไม่ผูก", "project_id": "__new"}, follow_redirects=False)
    assert r.status_code == 303
