"""ตรวจว่าหน้ารายละเอียด render ได้ และมี UI ปุ่มใหม่ครบ"""
import re
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import (School, Vendor, Procurement, ProcurementItem,
                        DocNumberCounter, Committee, CommitteeMember, Document)


def reset():
    db = SessionLocal()
    for M in (Document, CommitteeMember, Committee, ProcurementItem, Procurement,
              DocNumberCounter, Vendor, School):
        db.query(M).delete()
    db.commit(); db.close()


def main():
    reset()
    c = TestClient(app)
    c.post("/settings", data={"name": "โรงเรียนบ้านหินลาด"})
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "memo_no": "1/2569", "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุ", "inspection_mode": "single",
        "item_name": ["ปากกา"], "item_qty": ["1"], "item_unit": ["ด้าม"], "item_price": ["50"],
        "member_name": ["นาย ก"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    })
    assert r.status_code == 200
    html = r.text
    assert "btn-bundle" in html, "ไม่พบปุ่มหลัก bundle"
    assert "ออกเอกสารทั้งชุด" in html
    assert ".zip" not in html, "ยังมีคำว่า zip ค้างอยู่"
    assert "doc-onebyone" in html, "ไม่พบกล่องปุ่มรายใบ"
    # ปุ่มรายใบครบ 10
    assert html.count('name="doc_kind"') == 10
    print("OK: ปุ่มหลักเด่น + ไม่มี zip + ปุ่มรายใบ 10 ใบจัด flex")


if __name__ == "__main__":
    main()
