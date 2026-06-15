"""ทดสอบแบนเนอร์ 'ไม่จำเป็นต้องกรอก' สำหรับ กก.คุณลักษณะ / คำสั่งแต่งตั้งผู้ตรวจรับ"""
import re
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import (School, Vendor, Procurement, ProcurementItem, Person, Department,
                        Project, DocNumberCounter, Committee, CommitteeMember, Document)

NOTE = "ท่านไม่มีข้อมูลของเอกสารนี้"   # ใช้กับ กก.คุณลักษณะ (ซ่อนช่อง)
HINT = "แต่กรอกได้หากต้องการออกคำสั่ง"  # ใช้กับคำสั่ง (ยังกรอกได้)


def reset():
    db = SessionLocal()
    for M in (Document, CommitteeMember, Committee, ProcurementItem, Procurement,
              DocNumberCounter, Vendor, Person, Department, Project, School):
        db.query(M).delete()
    db.commit(); db.close()


def main():
    reset()
    c = TestClient(app)
    c.post("/settings", data={"name": "ร.ร.ทดสอบ", "doc_set_threshold": "5000"})

    # เคส A: วงเงินเล็ก คนเดียว ไม่มี spec -> ทั้ง 2 ส่วนขึ้นแบนเนอร์
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "ซื้อ", "subject": "วัสดุเล็ก", "inspection_mode": "single",
        "item_name": ["ปากกา"], "item_qty": ["2"], "item_unit": ["ด้าม"], "item_price": ["20"],
        "member_name": ["นาย ก"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    })
    pidA = r.url.path.split("/")[-1]
    page = c.get(f"/procurement/{pidA}").text
    assert page.count(NOTE) == 1, f"สเปกควรขึ้นแบนเนอร์ 1 จุด ได้ {page.count(NOTE)}"
    assert HINT in page, "คำสั่งควรมีหมายเหตุว่าไม่จำเป็นแต่กรอกได้"
    assert 'name="spec_memo_no"' not in page, "ไม่มีสเปกไม่ควรมีช่องสเปก"
    assert 'name="command_no"' in page, "คำสั่งต้องยังกรอกได้เสมอ"
    print("[A] เล็ก/คนเดียว -> สเปกแบนเนอร์(ซ่อนช่อง), คำสั่งมีหมายเหตุแต่ยังกรอกได้: OK")

    # เคส B: คณะกรรมการ + มีกรรมการคุณลักษณะ -> ขึ้นช่องกรอกทั้งคู่ ไม่มีแบนเนอร์
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "subject": "งานใหญ่", "inspection_mode": "committee",
        "item_name": ["งาน"], "item_qty": ["1"], "item_unit": ["งาน"], "item_price": ["8000"],
        "member_name": ["นาย ก", "นาย ข", "นาย ค"], "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
        "spec_member_name": ["สเปก X", "สเปก Y"], "spec_member_position": ["ครู", "ครู"],
        "spec_member_role": ["ประธานกรรมการ", "กรรมการ"],
    })
    pidB = r.url.path.split("/")[-1]
    page = c.get(f"/procurement/{pidB}").text
    assert NOTE not in page and HINT not in page, "เคสใหญ่ครบไม่ควรมีแบนเนอร์/หมายเหตุ"
    assert 'name="spec_memo_no"' in page and 'name="command_no"' in page, "ควรมีช่องกรอกทั้งคู่"
    print("[B] คณะกรรมการ + มีสเปก -> มีช่องกรอกครบ ไม่มีแบนเนอร์: OK")

    # เคส C: คณะกรรมการ แต่ไม่มีสเปก -> command มีช่อง, spec ขึ้นแบนเนอร์
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "subject": "งานกลาง", "inspection_mode": "committee",
        "item_name": ["งาน"], "item_qty": ["1"], "item_unit": ["งาน"], "item_price": ["8000"],
        "member_name": ["นาย ก", "นาย ข", "นาย ค"], "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
    })
    pidC = r.url.path.split("/")[-1]
    page = c.get(f"/procurement/{pidC}").text
    assert page.count(NOTE) == 1, f"ควรมีแบนเนอร์เฉพาะสเปก 1 จุด ได้ {page.count(NOTE)}"
    assert 'name="command_no"' in page, "คณะกรรมการต้องมีช่องเลขคำสั่ง"
    print("[C] คณะกรรมการ/ไม่มีสเปก -> แบนเนอร์เฉพาะสเปก, มีช่องคำสั่ง: OK")

    print("\n=== แบนเนอร์เงื่อนไขทำงานถูกต้องทั้งหมด ===")


if __name__ == "__main__":
    main()
