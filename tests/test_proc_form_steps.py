"""ฟอร์มสร้างเรื่องจัดซื้อแบ่งเป็นขั้นตอน + งบโครงการคงเหลือระหว่างกรอก + กล่องขั้นตอนต่อไปหน้าเรื่อง"""
from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_form_has_steps_and_budget_lookup(env):
    from app.models import Project, Procurement
    from app.services.budget import current_plan_year
    from app.models import School
    page = env.get("/procurement/new?case=normal").text
    for k in ('id="pfSteps"', 'data-step="0"', 'data-step="1"', 'data-step="2"', 'data-step="3"',
              'id="pfMoney"', 'id="pfReview"', 'class="pf-opt"', 'name="subject"', 'name="member_name"'):
        assert k in page, k
    special = env.get("/procurement/new?case=w119t2").text
    assert "ข้อมูลเอกสาร" in special and 'id="members"' not in special

    with _db() as s:
        py = current_plan_year(s.query(School).first())
        pj = Project(name="โครงการทดสอบงบคงเหลือ", plan_year=py, budget=10000); s.add(pj); s.commit()
        pid = pj.id
    assert env.get("/procurement/project-budget?name=ไม่มีโครงการนี้").json() == {"found": False}
    d = env.get("/procurement/project-budget?name=โครงการทดสอบงบคงเหลือ").json()
    assert d["found"] and d["left"] == 10000

    with _db() as s:
        pr = Procurement(subject="ซื้อวัสดุ", project_id=pid, project_name="โครงการทดสอบงบคงเหลือ",
                         fiscal_year=py, total_amount=2500, proc_type="ซื้อ"); s.add(pr); s.commit()
        prid = pr.id
    assert env.get("/procurement/project-budget?name=โครงการทดสอบงบคงเหลือ").json()["left"] == 7500
    # แก้ไขเรื่องเดิม: ไม่นับยอดตัวเองซ้ำ
    assert env.get(f"/procurement/project-budget?name=โครงการทดสอบงบคงเหลือ&exclude={prid}").json()["left"] == 10000

    detail = env.get(f"/procurement/{prid}?keep=1").text
    assert "ขั้นตอนต่อไป" in detail and 'class="pt-steps"' in detail and 'id="dn-order"' in detail and 'id="dn-inspect"' in detail
    assert detail.index("ลงเลขที่และวันที่") < detail.index(">ออกเอกสาร<")
    edit = env.get(f"/procurement/{prid}/edit").text
    assert 'id="pfSaveNow"' in edit and 'id="pfSteps"' in edit


def test_track_hidden_for_special_cases(env):
    from app.models import Procurement
    with _db() as s:
        pr = Procurement(subject="ค่าอาหารว่าง", proc_case="w119t2", fiscal_year=2569, total_amount=500, proc_type="ซื้อ")
        s.add(pr); s.commit(); pid = pr.id
    assert "ขั้นตอนต่อไป" not in env.get(f"/procurement/{pid}?keep=1").text
