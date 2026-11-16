"""บันทึกขอใช้งบประมาณ: สวิตช์เปิด/ปิด ประเภทค่าใช้จ่าย ค่าใช้จ่ายอื่น และเลขบันทึกไม่ชนรายงานขอซื้อ"""
import io
import json

from docx import Document as Docx
from fastapi.testclient import TestClient

from app.main import app
from app.models import Procurement, School
from app.services.budget_memo import build_lines
from app.services.render import kinds_for, render_document
from app.tenancy import session_for
from tests.test_subsidy import env  # noqa: F401  (ล็อกอินโรงเรียนตัวอย่างในโฟลเดอร์ชั่วคราว)


def _create(c, **extra):
    data = {
        "fiscal_year": "2569", "memo_no": "", "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุทดสอบบันทึกขอใช้งบ", "inspection_mode": "single",
        "item_name": ["กระดาษ", "เครื่องพิมพ์"], "item_spec": ["", ""], "item_qty": ["2", "1"],
        "item_unit": ["รีม", "เครื่อง"], "item_price": ["120", "15000"],
        "item_cost_type": ["", "ค่าครุภัณฑ์"],
        "member_name": ["นาย ง"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    }
    data.update(extra)
    r = c.post("/procurement/new", data=data, follow_redirects=False)
    return int(r.headers["location"].rstrip("/").split("/")[-1].split("?")[0])


def test_budget_memo_off_by_default_and_on_when_selected(env):
    c = env
    off_id = _create(c)
    on_id = _create(c, budget_memo_on="1", budget_owner="นางสาวสิริมล บุญธรรม",
                    budget_activity_date="16/12/2569",
                    bx_type=["ค่าใช้สอย", "ค่าตอบแทน"], bx_name=["ค่าอาหารว่าง", "ค่าวิทยากร"],
                    bx_qty=["50", "3"], bx_unit=["คน", "ชม."], bx_price=["35", "600"])
    from app.accounts import acc_session, Tenant
    a = acc_session(); tid = a.query(Tenant).first().id; a.close()
    db = session_for(tid)
    try:
        off, on = db.get(Procurement, off_id), db.get(Procurement, on_id)
        assert "บันทึกขอใช้งบประมาณ" not in kinds_for(off)
        assert kinds_for(on)[0] == "บันทึกขอใช้งบประมาณ"
        # ประเภทที่เลือกเองต้องถูกเก็บ ไม่เดาจากราคา
        assert [it.cost_type for it in on.items] == ["", "ค่าครุภัณฑ์"]
        assert len(json.loads(on.budget_extra)) == 2
        # เลขบันทึกขอใช้งบไม่ชนเลขรายงานขอซื้อของเรื่องเดียวกัน
        assert on.budget_memo_no and on.budget_memo_no != on.memo_no
        lines, total = build_lines(on)
        texts = [ln["text"] for ln in lines]
        assert any(t.startswith("1. ค่าวัสดุ จำนวน 1 รายการ") for t in texts)
        assert any("ค่าครุภัณฑ์" in t for t in texts)
        assert any("ค่าอาหารว่าง" in t for t in texts)
        assert total == 2 * 120 + 15000 + 50 * 35 + 3 * 600
        # ออกเอกสารได้ และไม่มีตัวแปรค้าง
        c.post("/settings", data={"name": "โรงเรียนทดสอบ", "director_name": "นายทดสอบ"})
        db.expire_all(); on = db.get(Procurement, on_id)
        path = render_document("บันทึกขอใช้งบประมาณ", on, db.query(School).first())
        text = "\n".join(p.text for p in Docx(path).paragraphs)
        assert "ขออนุมัติใช้งบประมาณ" in text and "นางสาวสิริมล บุญธรรม" in text
        assert "{{" not in text and "}}" not in text
    finally:
        db.close()
