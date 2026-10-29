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


def test_case_flows(env):
    """รูปแบบพิเศษมีขั้นตอนของตัวเอง ออกเอกสารแล้วขั้นนั้นเป็น "ทำแล้ว" (บันทึกประวัติการออกเอกสาร)"""
    import json
    import re
    from app.models import Procurement, ProcurementItem, Vendor, Document
    with _db() as s:
        v = Vendor(name="ร้านทดสอบขั้นตอน"); s.add(v); s.flush()
        made = {}
        for case, extra in (("w804", {"inspector": "ครูเอ"}), ("w119t1", {}), ("clause79", {"receipt_no": "12"}),
                            ("w119t2", {"t2_item": "ค่าอาหารว่างและเครื่องดื่ม", "pay_mode": "ยืมเงินไปจ่าย"})):
            pr = Procurement(subject="ทดสอบ " + case, proc_case=case, fiscal_year=2569, total_amount=900,
                             proc_type="ซื้อ", vendor_id=v.id, memo_no="5/2569", case_extra=json.dumps(extra, ensure_ascii=False))
            s.add(pr); s.flush()
            s.add(ProcurementItem(procurement_id=pr.id, name="ของ", quantity=1, unit="ชิ้น", unit_price=900))
            made[case] = pr.id
        s.commit()

    def labels(pid):
        html = env.get(f"/procurement/{pid}?keep=1").text
        box = html[html.index('class="pt-steps"'):html.index("</ol>", html.index('class="pt-steps"'))]
        return re.findall(r"<b>([^<]+)</b>", box), box

    lab, box = labels(made["w804"])
    assert lab[:4] == ["ลงเลขที่และผู้ตรวจรับ", "ออกรายงานขอซื้อ", "ซื้อและรับของ", "รายงานสรุปผล"] and lab[-1] == "เบิกจ่าย"
    assert "เข้าทะเบียน" in lab
    lab, _ = labels(made["w119t1"])
    assert lab[:3] == ["ซื้อไปก่อน", "ลงเลขรายงาน", "ออกเอกสาร"]
    lab, _ = labels(made["clause79"])
    assert lab[:4] == ["ซื้อ/จ้างไปก่อน", "ลงใบเสร็จ", "ลงเลขรายงาน", "ออกรายงาน"]
    lab, _ = labels(made["w119t2"])
    assert lab == ["เลือกรายการ", "ยืมเงิน", "ลงใบเสร็จ", "ออกบันทึกเบิกจ่าย", "ส่งใช้เงินยืม", "เบิกจ่าย"]

    # ออกเอกสาร ว.804 -> บันทึกประวัติ + ขั้น "ออกรายงานขอซื้อ" ทำแล้ว
    assert env.get(f"/procurement/{made['w804']}/altdoc/w804").status_code == 200
    with _db() as s:
        assert s.query(Document).filter_by(procurement_id=made["w804"]).count() == 1
    _, box = labels(made["w804"])
    seg = box[box.index("ออกรายงานขอซื้อ"):]
    assert "ทำแล้ว" in seg[:seg.index("</li>")]


def test_lunch_installment_chips():
    from types import SimpleNamespace as N
    from app.services.module_setup import installment_chips
    insts = [N(id=1, seq=1, status="จ่ายแล้ว"), N(id=2, seq=2, status="ส่งมอบแล้ว"),
             N(id=3, seq=3, status="ตรวจรับแล้ว"), N(id=4, seq=4, status="ร่าง")]
    chips = installment_chips(insts, "/lunch/round/9/plan")
    assert [c["label"] for c in chips] == ["งวด 1 จ่ายแล้ว", "งวด 2 รอตรวจรับ", "งวด 3 รอจ่ายเงิน", "งวด 4 รอส่งมอบ"]
    assert [c["state"] for c in chips] == ["done", "wait", "wait", "todo"]
    assert chips[1]["href"] == "/lunch/round/9/plan#inst-2"
