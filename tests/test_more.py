"""ทดสอบ: (1) กก.คุณลักษณะแยกชุด (2) ประวัติเอกสาร (3) บังคับโหมดตามวงเงิน"""
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


def docx_text(content):
    d = Docx(io.BytesIO(content))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    reset()
    c = TestClient(app)
    c.post("/settings", data={"name": "โรงเรียนบ้านหินลาด", "director_name": "นายอัครพงศ์",
                              "officer_name": "นายสิรธีร์", "head_officer_name": "นางสาวประทุมพร",
                              "doc_set_threshold": "5000"})

    # (3) วงเงินเกินเกณฑ์ + เลือก single -> ระบบบังคับเป็น committee
    # (1) ใส่กรรมการคุณลักษณะแยกจากผู้ตรวจรับ
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง",
        "subject": "จัดทำป้าย", "inspection_mode": "single",  # เลือกคนเดียว แต่วงเงินเกิน
        "item_name": ["ป้าย"], "item_qty": ["1"], "item_unit": ["ป้าย"], "item_price": ["8000"],
        "member_name": ["ผู้ตรวจ ก", "ผู้ตรวจ ข", "ผู้ตรวจ ค"],
        "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
        "spec_member_name": ["สเปก X", "สเปก Y", "สเปก Z"],
        "spec_member_position": ["ครู", "ครู", "ครู"],
        "spec_member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
    })
    pid = r.url.path.split("/")[-1]
    db = SessionLocal(); p = db.get(Procurement, int(pid))
    assert p.inspection_mode == "committee", f"วงเงินเกินต้องบังคับ committee ได้ {p.inspection_mode}"
    kinds = {cc.kind for cc in p.committees}
    assert "spec" in kinds and "inspect" in kinds, f"ต้องมีทั้ง spec+inspect: {kinds}"
    db.close()
    print("[3] วงเงินเกินเกณฑ์ บังคับเป็นคณะกรรมการ: OK")

    # (1) เอกสารแต่งตั้ง กก.คุณลักษณะ ใช้รายชื่อ spec (ไม่ใช่ผู้ตรวจรับ)
    t_spec = docx_text(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "แต่งตั้งกรรมการคุณลักษณะ"}).content)
    assert "สเปก X" in t_spec and "สเปก Z" in t_spec, "แต่งตั้งคุณลักษณะไม่ใช้รายชื่อ spec"
    assert "ผู้ตรวจ ก" not in t_spec, "ไม่ควรมีรายชื่อผู้ตรวจรับในเอกสารคุณลักษณะ"
    # คำสั่งแต่งตั้งผู้ตรวจรับ ใช้รายชื่อ inspect
    t_insp = docx_text(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "คำสั่งแต่งตั้งผู้ตรวจรับ"}).content)
    assert "ผู้ตรวจ ก" in t_insp and "สเปก X" not in t_insp, "คำสั่งตรวจรับใช้รายชื่อผิดชุด"
    print("[1] กก.คุณลักษณะ แยกชุดจากผู้ตรวจรับ: OK")

    # (2) ประวัติเอกสาร: หน้า detail ต้องโชว์ + ดาวน์โหลดซ้ำได้
    page = c.get(f"/procurement/{pid}").text
    assert "ประวัติเอกสารที่ออก" in page
    ids = re.findall(r"/document/(\d+)/download", page)
    assert len(ids) >= 2, f"ควรมีประวัติ >=2 รายการ ได้ {len(ids)}"
    rd = c.get(f"/document/{ids[0]}/download")
    assert rd.status_code == 200 and "wordprocessing" in rd.headers.get("content-type", "")
    print("[2] ประวัติเอกสาร + ดาวน์โหลดซ้ำ: OK")

    # bundle เก็บประวัติเป็นแถวเดียว
    c.post(f"/procurement/{pid}/bundle", data={"kinds": ["รายงานขอซื้อ", "ใบตรวจรับพัสดุ"]})
    page2 = c.get(f"/procurement/{pid}").text
    assert "ชุดเอกสาร (2 ใบ)" in page2, "bundle ควรบันทึกประวัติเป็นชุดเดียว"
    print("[2] bundle บันทึกประวัติเป็นชุดเดียว: OK")

    print("\n=== ทั้ง 3 ข้อ ผ่านทั้งหมด ===")


if __name__ == "__main__":
    main()
