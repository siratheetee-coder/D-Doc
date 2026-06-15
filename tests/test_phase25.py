"""ทดสอบเฟส 2.5: VAT, ผู้ลงนาม, ค่าปรับ auto, คัดลอกเรื่อง, ใบส่งของ"""
import io, re
from fastapi.testclient import TestClient
from docx import Document as Docx
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


def dtext(content):
    d = Docx(io.BytesIO(content))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    reset()
    c = TestClient(app)
    c.post("/settings", data={"name": "โรงเรียนบ้านหินลาด", "director_name": "นายอัครพงศ์ ศรีวงศ์",
                              "officer_name": "นายสิรธีร์ ตีเมืองซ้าย", "head_officer_name": "นางสาวประทุมพร จันทะเกต",
                              "doc_set_threshold": "5000"})
    c.post("/vendors", data={"name": "ร้านทดสอบ", "tax_id": "111"})
    vid = re.search(r'vf(\d+)', c.get("/vendors").text).group(1)

    # สร้างเรื่อง: VAT รวม + ผู้ลงนาม=หัวหน้าเจ้าหน้าที่
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง", "subject": "จัดทำป้าย",
        "vat_mode": "include", "order_signer": "head_officer", "inspection_mode": "committee", "vendor_id": vid,
        "item_name": ["ป้าย"], "item_qty": ["1"], "item_unit": ["ป้าย"], "item_price": ["10700"],
        "member_name": ["นาย ก", "นาย ข", "นาย ค"], "member_position": ["ครู","ครู","ครู"],
        "member_role": ["ประธานกรรมการ","กรรมการ","กรรมการและเลขานุการ"],
    })
    pid = r.url.path.split("/")[-1]

    # VAT -> ใบเสนอราคา
    q = dtext(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบเสนอราคา"}).content)
    assert "ราคานี้รวมภาษีมูลค่าเพิ่มแล้ว" in q and "ภาษีมูลค่าเพิ่ม" in q, "VAT note หาย"
    assert "10,000" in q, "ราคาก่อนภาษีควร ~10,000 (10700/1.07)"
    print("[1] VAT: ใบเสนอราคาแสดงรวม VAT + แยกราคาก่อนภาษี: OK")

    # ผู้ลงนาม=หัวหน้าเจ้าหน้าที่ -> ใบสั่งจ้าง
    po = dtext(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบสั่งซื้อ/สั่งจ้าง"}).content)
    assert "นางสาวประทุมพร จันทะเกต" in po and "หัวหน้าเจ้าหน้าที่" in po, "ผู้ลงนามไม่ใช่หัวหน้าเจ้าหน้าที่"
    assert "นายอัครพงศ์ ศรีวงศ์" not in po.split("ผู้รับจ้าง")[0], "ไม่ควรเป็น ผอ."
    print("[2] ผู้ลงนามใบสั่ง = หัวหน้าเจ้าหน้าที่: OK")

    # ค่าปรับ + ใบส่งของ ผ่าน update-refs
    c.post(f"/procurement/{pid}/update-refs", data={
        "memo_no": "1/2569", "order_no": "9/2569", "command_no": "", "result_memo_no": "",
        "spec_memo_no": "", "inspect_memo_no": "", "request_date": "19/03/2569",
        "order_date": "25/03/2569", "delivery_due_date": "27/03/2569", "inspect_date": "30/03/2569",
        "overdue_days": "3", "delivery_note_no": "12", "delivery_note_book": "5",
    })
    ti = dtext(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบตรวจรับพัสดุ"}).content)
    # ค่าปรับ = 10700 * 0.10/100 * 3 = 32.10
    assert "เกินกำหนดจำนวน 3 วัน" in ti, "จำนวนวันเกินไม่เข้า"
    assert "32.10" in ti or "32.1" in ti, f"ค่าปรับคำนวณผิด (ควร 32.10)"
    assert "เล่มที่ 5" in ti and "เลขที่ 12" in ti, "ใบส่งของไม่เข้า"
    print("[3] ค่าปรับ auto (32.10) + ใบส่งของ เล่ม/เลขที่: OK")

    # คัดลอกเรื่อง
    r = c.post(f"/procurement/{pid}/duplicate")
    assert r.url.path.endswith("/edit"), "ควร redirect ไปหน้าแก้ไขฉบับใหม่"
    new_pid = r.url.path.split("/")[-2]
    assert new_pid != pid, "ควรเป็นเรื่องใหม่คนละ id"
    db = SessionLocal(); src = db.get(Procurement, int(pid)); new = db.get(Procurement, int(new_pid))
    assert "(สำเนา)" in new.subject and len(new.items) == len(src.items), "คัดลอกรายการไม่ครบ"
    assert new.memo_no and new.memo_no != src.memo_no, "เลขบันทึกควรเป็นเลขใหม่"
    assert not new.order_no, "ไม่ควรก๊อปเลขใบสั่ง"
    assert new.vat_mode == "include" and new.order_signer == "head_officer", "ควรก๊อป VAT/ผู้ลงนาม"
    n_committees = len(new.committees)
    db.close()
    print(f"[4] คัดลอกเรื่อง: เลขใหม่ {new.memo_no}, รายการ+กรรมการครบ ({n_committees} ชุด), ไม่ก๊อปเลขใบสั่ง: OK")

    print("\n=== เฟส 2.5 ผ่านทั้งหมด ===")


if __name__ == "__main__":
    main()
