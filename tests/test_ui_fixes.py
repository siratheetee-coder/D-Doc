"""ทดสอบการแก้ 4 ข้อ: ลบ memo_no ในฟอร์มสร้าง, วันที่ พ.ศ., label ผู้ขายตามประเภท, จัดกลุ่ม section"""
import io
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
    c.post("/settings", data={"name": "โรงเรียนบ้านหินลาด", "director_name": "นายอัครพงศ์ ศรีวงศ์"})

    # ข้อ 1: หน้าฟอร์มสร้าง มีช่อง memo_no (เติมเลขรันอัตโนมัติ + แบนเนอร์), label ผู้ขายขึ้นต้น
    form_html = c.get("/procurement/new").text
    assert 'name="memo_no"' in form_html, "ควรมีช่องเลขที่บันทึก (เติมเลขรันให้)"
    assert "รันต่อจากเลขล่าสุด" in form_html, "ควรมีแบนเนอร์อธิบายการรันเลขอัตโนมัติ"
    assert 'id="vendorLabel"' in form_html and "syncType" in form_html, "label ผู้ขายไดนามิกหาย"
    print("[1] ฟอร์มสร้าง: ช่องเลขบันทึก (รันอัตโนมัติ) + แบนเนอร์ + label ผู้ขายไดนามิก: OK")

    # สร้างเรื่อง (ไม่ส่ง memo_no) -> ระบบออกเลขให้อัตโนมัติ
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง",
        "subject": "จัดทำป้ายไวนิล", "inspection_mode": "single",
        "item_name": ["ป้าย"], "item_qty": ["1"], "item_unit": ["ป้าย"], "item_price": ["5000"],
        "member_name": ["นาย ก"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    })
    pid = r.url.path.split("/")[-1]
    db = SessionLocal(); proc = db.get(Procurement, int(pid))
    assert proc.memo_no == "1/2569", f"เลขบันทึกอัตโนมัติผิด: {proc.memo_no}"
    db.close()
    print("[2] สร้างเรื่องไม่ใส่เลข -> ระบบออก 1/2569 อัตโนมัติ: OK")

    # ข้อ 2: กรอกวันที่เป็น พ.ศ. -> เก็บเป็น ค.ศ. ถูกต้อง
    c.post(f"/procurement/{pid}/update-refs", data={
        "memo_no": "1/2569", "order_no": "9/2569", "command_no": "", "result_memo_no": "",
        "spec_memo_no": "", "inspect_memo_no": "",
        "request_date": "19/03/2569", "order_date": "25/03/2569",
        "delivery_due_date": "", "inspect_date": "",
    })
    db = SessionLocal(); proc = db.get(Procurement, int(pid))
    assert proc.request_date.year == 2026 and proc.request_date.month == 3 and proc.request_date.day == 19, \
        f"แปลง พ.ศ.->ค.ศ. ผิด: {proc.request_date}"
    db.close()
    print("[2] วันที่ พ.ศ. 19/03/2569 -> เก็บเป็น 2026-03-19: OK")

    # ข้อ 4: หน้า detail แสดงกลุ่ม docgrp + วันที่เป็น พ.ศ. (ไม่มี type=date)
    page = c.get(f"/procurement/{pid}").text
    assert page.count("docgrp-h") >= 6, "ยังไม่จัดกลุ่มเอกสาร 6 กลุ่ม"
    assert 'type="date"' not in page, "ยังใช้ช่อง type=date (ค.ศ.) อยู่"
    assert "19/03/2569" in page, "วันที่ในฟอร์มควรแสดงเป็น พ.ศ."
    print("[4] หน้า detail: จัดกลุ่ม 6 กลุ่ม + วันที่ พ.ศ.: OK")

    # เอกสารที่ออกมาใช้วันที่ พ.ศ.
    r = c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบสั่งซื้อ/สั่งจ้าง"})
    from docx import Document as Docx
    d = Docx(io.BytesIO(r.content))
    txt = "\n".join(p.text for p in d.paragraphs)
    assert "25 มีนาคม 2569" in txt, "เอกสารควรพิมพ์วันที่ใบสั่งเป็น พ.ศ."
    print("[2] เอกสารพิมพ์วันที่เป็น พ.ศ. (25 มีนาคม 2569): OK")

    print("\n=== แก้ครบทั้ง 4 ข้อ ผ่านทั้งหมด ===")


if __name__ == "__main__":
    main()
