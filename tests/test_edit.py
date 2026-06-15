"""ทดสอบการแก้ไขเรื่อง + ผู้ขาย + มาสเตอร์ + แบนเนอร์เตือนตั้งค่า"""
import re
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import (School, Vendor, Procurement, ProcurementItem, Person, Department,
                        Project, DocNumberCounter, Committee, CommitteeMember, Document)


def reset():
    db = SessionLocal()
    for M in (Document, CommitteeMember, Committee, ProcurementItem, Procurement,
              DocNumberCounter, Vendor, Person, Department, Project, School):
        db.query(M).delete()
    db.commit(); db.close()


def main():
    reset()
    c = TestClient(app)

    # แบนเนอร์เตือน: ยังไม่ตั้งค่าโรงเรียน -> หน้าหลักต้องเตือน
    assert "ยังตั้งค่าโรงเรียนไม่ครบ" in c.get("/").text, "ไม่มีแบนเนอร์เตือนตั้งค่า"
    c.post("/settings", data={"name": "โรงเรียนบ้านหินลาด", "director_name": "นายอัครพงศ์",
                              "officer_name": "นายสิรธีร์", "head_officer_name": "นางสาวประทุมพร"})
    assert "ยังตั้งค่าโรงเรียนไม่ครบ" not in c.get("/").text, "ตั้งค่าครบแล้วยังเตือน"
    print("[1] แบนเนอร์เตือนตั้งค่าโรงเรียน: OK")

    c.post("/vendors", data={"name": "ร้าน ก", "tax_id": "111"})
    vid = re.search(r'vf(\d+)', c.get("/vendors").text).group(1)

    # สร้างเรื่อง (ซื้อ, คนเดียว)
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุเดิม", "inspection_mode": "single", "vendor_id": vid,
        "item_name": ["ปากกา"], "item_qty": ["2"], "item_unit": ["ด้าม"], "item_price": ["10"],
        "member_name": ["นาย ก"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    })
    pid = r.url.path.split("/")[-1]
    db = SessionLocal(); p0 = db.get(Procurement, int(pid)); memo0 = p0.memo_no; db.close()
    assert memo0 == "1/2569"

    # หน้าแก้ไขต้องเติมค่าเดิม
    ef = c.get(f"/procurement/{pid}/edit").text
    assert 'value="วัสดุเดิม"' in ef and 'value="ปากกา"' in ef, "ฟอร์มแก้ไขไม่เติมค่าเดิม"
    print("[2] หน้าแก้ไขเติมค่าเดิม: OK")

    # แก้ไข: เปลี่ยนเป็นจ้าง, เปลี่ยนชื่อเรื่อง+รายการ+ราคา, เป็นคณะกรรมการ 3 คน
    c.post(f"/procurement/{pid}/edit", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง",
        "subject": "จัดทำป้ายใหม่", "inspection_mode": "committee", "vendor_id": vid,
        "item_name": ["ป้าย", "ขาตั้ง"], "item_qty": ["3", "1"], "item_unit": ["ป้าย", "อัน"],
        "item_price": ["500", "200"],
        "member_name": ["นาย ก", "นาย ข", "นาย ค"], "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
    })
    db = SessionLocal(); p1 = db.get(Procurement, int(pid))
    assert p1.subject == "จัดทำป้ายใหม่" and p1.proc_type == "จ้าง"
    assert abs(p1.total_amount - 1700) < 0.01, f"total ไม่อัปเดต: {p1.total_amount}"
    assert len(p1.items) == 2, "รายการไม่อัปเดต"
    insp = next(c2 for c2 in p1.committees if c2.kind == "inspect")
    assert len(insp.members) == 3 and insp.mode == "committee", "กรรมการไม่อัปเดต"
    assert p1.memo_no == memo0, "เลขบันทึกไม่ควรหายตอนแก้ไขเรื่อง"
    db.close()
    print("[2] แก้ไขเรื่อง (ประเภท/รายการ/ยอด/กรรมการ) + คงเลขบันทึก: OK")

    # แก้ไขผู้ขาย
    c.post(f"/vendors/{vid}/update", data={"name": "ร้าน ก (แก้)", "tax_id": "999",
                                           "phone": "08", "bank_account": "123", "address": "ที่อยู่ใหม่"})
    db = SessionLocal(); v = db.get(Vendor, int(vid))
    assert v.name == "ร้าน ก (แก้)" and v.tax_id == "999" and v.address == "ที่อยู่ใหม่"
    db.close()
    print("[3] แก้ไขผู้ขาย: OK")

    # มาสเตอร์: เพิ่ม person แล้วแก้ชื่อ
    c.post("/masters/person", data={"name": "นาย เดิม", "position": "ครู"})
    db = SessionLocal(); per = db.query(Person).first(); per_id = per.id; db.close()
    c.post(f"/masters/person/{per_id}/update", data={"name": "นาย ใหม่", "position": "ครูชำนาญการ"})
    db = SessionLocal(); per = db.get(Person, per_id)
    assert per.name == "นาย ใหม่" and per.position == "ครูชำนาญการ"
    db.close()
    print("[4] แก้ไขบุคลากร (มาสเตอร์): OK")

    print("\n=== แก้ไขได้ครบ (เรื่อง/ผู้ขาย/มาสเตอร์) + แบนเนอร์เตือน ผ่านทั้งหมด ===")


if __name__ == "__main__":
    main()
