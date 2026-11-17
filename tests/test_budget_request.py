"""คำขอใช้งบประมาณ ช่วงที่ 1: สร้าง แก้ไข ออก Word เลขรันจากทะเบียน ครูผู้รับผิดชอบเห็นแบบอ่านอย่างเดียว"""
from docx import Document as Docx

from app.models import BudgetRequest, IssuedDocNo, Person, Project
from app.services import budget_request as svc
from app.tenancy import session_for
from tests.test_subsidy import env  # noqa: F401


def _db():
    from app.accounts import acc_session, Tenant
    with acc_session() as a:
        tid = a.query(Tenant).first().id
    return tid, session_for(tid)


def _payload(**kw):
    data = {"fiscal_year": "2570", "request_no": "", "date": "16/11/2569", "owner": "", "department": "วิชาการ",
            "activity_date": "16/12/2569", "purpose": "", "inspectors": "นาย ก\nนาง ข\nนาย ค",
            "ln_type": ["ค่าวัสดุ", "ค่าใช้สอย", "ค่าตอบแทน"],
            "ln_name": ["วัสดุจัดกิจกรรม", "ค่าอาหารว่าง", "ค่าวิทยากร"],
            "ln_qty": ["1", "50", "3"], "ln_unit": ["ชุด", "คน", "ชม."], "ln_price": ["15000", "35", "600"],
            "ln_method": ["จัดซื้อ", "ยืมเงิน", "ยืมเงิน"]}
    data.update(kw)
    return data


def test_create_edit_doc_and_teacher_view(env):
    c = env
    tid, db = _db()
    try:
        proj = Project(name="พัฒนาบุคลากร", budget=50000, plan_year=2570)
        teacher = db.query(Person).first()
        db.add(proj); db.commit()
        r = c.post("/budget-requests/new", data=_payload(project_id=str(proj.id), owner_person_id=str(teacher.id)),
                   follow_redirects=False)
        assert r.status_code == 303, r.text
        rid = int(r.headers["location"].split("/")[-1].split("?")[0])
        db.expire_all()
        req = db.get(BudgetRequest, rid)
        assert req.request_no and req.owner == teacher.name and len(req.lines) == 3
        assert svc.total(req) == 15000 + 50 * 35 + 3 * 600
        groups = {g["method"]: g["total"] for g in svc.by_method(req)}
        assert groups == {"จัดซื้อ": 15000, "ยืมเงิน": 3550}
        # เลขบันทึกเข้าทะเบียนเลขหนังสือ
        assert db.query(IssuedDocNo).filter_by(source="budget_request", ref_id=rid).count() == 1
        # ไม่มีรายการ = บันทึกไม่ได้
        bad = c.post(f"/budget-requests/{rid}/edit", data=_payload(ln_name=["", "", ""]), follow_redirects=False)
        assert bad.status_code == 400
        # แก้ไข: ลดเหลือ 2 แถว
        ok = c.post(f"/budget-requests/{rid}/edit", data=_payload(project_id=str(proj.id), owner_person_id=str(teacher.id),
                    request_no=req.request_no, ln_type=["ค่าวัสดุ", "ค่าใช้สอย"], ln_name=["วัสดุ", "ค่าไวนิล"],
                    ln_qty=["1", "1"], ln_unit=["ชุด", "ผืน"], ln_price=["1000", "450"], ln_method=["จัดซื้อ", "จัดจ้าง"]),
                    follow_redirects=False)
        assert ok.status_code == 303
        db.expire_all(); req = db.get(BudgetRequest, rid)
        assert [ln.name for ln in req.lines] == ["วัสดุ", "ค่าไวนิล"] and svc.total(req) == 1450
        assert db.query(IssuedDocNo).filter_by(source="budget_request", ref_id=rid).count() == 1
        # หน้ารายละเอียด + Word
        page = c.get(f"/budget-requests/{rid}")
        assert page.status_code == 200 and "จัดจ้าง" in page.text and "1,450.00" in page.text
        doc = c.get(f"/budget-requests/{rid}/doc.docx")
        assert doc.status_code == 200
        import io
        text = "\n".join(p.text for p in Docx(io.BytesIO(doc.content)).paragraphs)
        assert "ค่าไวนิล" in text and "พัฒนาบุคลากร" in text and "{{" not in text
        # การ์ดหน้าหลักครู
        cards = svc.teacher_cards(db, teacher.id)
        assert cards and cards[0]["href"] == f"/me/budget-requests/{rid}" and cards[0]["total"] == 1450
        assert cards[0]["left"] == 50000
    finally:
        db.close()


def test_teacher_sees_only_own_request_read_only(env):
    from tests.test_access_shared_pages import _account
    tid, db = _db()
    try:
        mine = db.query(Person).first()
        other = Person(name="ครูคนอื่น"); db.add(other); db.flush()
        a = BudgetRequest(fiscal_year=2570, request_no="1/2570", owner_person_id=mine.id)
        b = BudgetRequest(fiscal_year=2570, request_no="2/2570", owner_person_id=other.id)
        db.add_all([a, b]); db.commit()
        t = _account("ครูขอใช้งบ", "academic")
        assert t.get(f"/me/budget-requests/{a.id}").status_code == 200
        assert t.get(f"/me/budget-requests/{b.id}").status_code == 403
        assert t.get("/budget-requests", follow_redirects=False).status_code == 403
        assert t.get(f"/budget-requests/{a.id}", follow_redirects=False).status_code == 403
        assert t.post(f"/budget-requests/{a.id}/delete", follow_redirects=False).status_code == 403
    finally:
        db.close()


def test_phase2_create_targets_link_and_status(env):
    """ช่วงที่ 2: ปุ่มสร้างเอกสารปลายทางเติมข้อมูลให้ บันทึกแล้วผูกรายการ เลิกผูกได้ ขั้นตอนขยับตาม"""
    from app.models import BudgetRequestLine, DisburseMemo, MoneyLoan, Procurement
    c = env
    tid, db = _db()
    try:
        req = BudgetRequest(fiscal_year=2570, request_no="9/2570", owner="ครูทดสอบ", status="ส่งแล้ว",
                            inspectors="นาย ก\nนาง ข\nนาย ค")
        db.add(req); db.flush()
        for i, (n, m, p) in enumerate([("กระดาษ", "จัดซื้อ", 500), ("อาหารว่าง", "ยืมเงิน", 700),
                                       ("ค่าวิทยากร", "เบิกจ่ายตรง", 1200)]):
            db.add(BudgetRequestLine(request_id=req.id, seq=i, cost_type="ค่าวัสดุ", name=n, qty=1, unit="ชุด", price=p, method=m))
        db.commit(); rid = req.id
        assert svc.step_of(req, db) == 1
        # ปุ่มจัดซื้อ -> หน้าเลือกรูปแบบ (พา br ไปด้วย) -> ฟอร์มเติมรายการ+กรรมการ
        go = c.get(f"/budget-requests/{rid}/go?m=จัดซื้อ", follow_redirects=False)
        assert go.status_code == 303 and "/procurement/new?br=" in go.headers["location"]
        form = c.get(go.headers["location"] + "&case=normal")
        assert "กระดาษ" in form.text and 'name="from_br"' in form.text and "ประธานกรรมการ" in form.text
        r = c.post("/procurement/new", data={"fiscal_year": "2570", "memo_no": "", "proc_type": "ซื้อ",
                   "method": "เฉพาะเจาะจง", "subject": "กระดาษ", "inspection_mode": "single", "item_name": ["กระดาษ"],
                   "item_spec": [""], "item_qty": ["1"], "item_unit": ["ชุด"], "item_price": ["500"], "item_cost_type": [""],
                   "member_name": ["นาย ก"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
                   "from_br": str(rid), "from_br_m": "จัดซื้อ"}, follow_redirects=False)
        pid = int(r.headers["location"].split("/")[-1])
        db.expire_all()
        assert db.get(Procurement, pid) and req.lines[0].procurement_id == pid
        assert svc.step_of(req, db) == 2
        # ยืมเงิน: ฟอร์มเติมผู้ยืม+ยอด บันทึกแล้วกลับหน้าคำขอ
        page = c.get(f"/finance/loans?year=2570&br={rid}&br_m=ยืมเงิน")
        assert 'value="700.0"' in page.text and "ครูทดสอบ" in page.text
        r = c.post("/finance/loans", data={"fiscal_year": "2570", "borrower": "ครูทดสอบ", "amount": "700",
                   "within_days": "15", "from_br": str(rid), "from_br_m": "ยืมเงิน"}, follow_redirects=False)
        assert r.headers["location"] == f"/budget-requests/{rid}?linked=1"
        db.expire_all()
        loan = db.query(MoneyLoan).order_by(MoneyLoan.id.desc()).first()
        assert req.lines[1].loan_id == loan.id and "อาหารว่าง" in loan.items
        # เบิกจ่ายตรง
        page = c.get(f"/finance/disburse?year=2570&br={rid}&br_m=เบิกจ่ายตรง")
        assert "ค่าวิทยากร" in page.text and 'name="from_br"' in page.text
        r = c.post("/finance/disburse", data={"fiscal_year": "2570", "subject": "ค่าวิทยากร", "payee": "ครูทดสอบ",
                   "amount": "1200", "proc_kind": "ค่าใช้จ่ายอื่น", "from_br": str(rid), "from_br_m": "เบิกจ่ายตรง"},
                   follow_redirects=False)
        mid = int(r.headers["location"].split("/")[-1].split("?")[0])
        db.expire_all()
        assert db.get(DisburseMemo, mid) and req.lines[2].disburse_id == mid
        assert svc.step_of(req, db) == 3   # ทำเรื่องครบ รอจ่าย
        detail = c.get(f"/budget-requests/{rid}")
        assert "สัญญายืม" in detail.text and "บันทึกขอเบิก" in detail.text and "ยังไม่ทำเรื่อง" not in detail.text
        # ปุ่มทำซ้ำไม่ได้เมื่อผูกครบแล้ว
        assert c.get(f"/budget-requests/{rid}/go?m=ยืมเงิน", follow_redirects=False).headers["location"] == f"/budget-requests/{rid}"
        # เลิกผูก แล้วผูกกลับกับเอกสารเดิม
        c.post(f"/budget-requests/{rid}/unlink", data={"m": "ยืมเงิน", "target_id": str(loan.id)})
        db.expire_all(); assert req.lines[1].loan_id is None
        c.post(f"/budget-requests/{rid}/link", data={"m": "ยืมเงิน", "target_id": str(loan.id)})
        db.expire_all(); assert req.lines[1].loan_id == loan.id
        # เอกสารถูกลบ = กลับเป็นยังไม่ทำเรื่อง
        db.delete(db.get(DisburseMemo, mid)); db.commit()
        assert len(svc.pending_lines(req, "เบิกจ่ายตรง", db)) == 1
    finally:
        db.close()
