"""ตรวจว่าเอกสารที่ออกมามีตราครุฑฝังอยู่จริง"""
from docx import Document as Docx
from app.models import School, Procurement, ProcurementItem, Committee, CommitteeMember
from app.services.render import render_document


def main():
    school = School(name="โรงเรียนบ้านหินลาด", director_name="นายอัครพงศ์ ศรีวงศ์",
                    officer_name="นายสิรธีร์ ตีเมืองซ้าย", head_officer_name="นางสาวประทุมพร จันทะเกต")
    p = Procurement(fiscal_year=2569, memo_no="1/2569", proc_type="ซื้อ",
                    subject="วัสดุสำนักงาน", project_name="พัฒนาคุณภาพ",
                    total_amount=500.0, inspection_mode="single")
    p.items.append(ProcurementItem(name="ปากกา", quantity=10, unit="ด้าม", unit_price=50))
    c = Committee(kind="inspect", mode="single")
    c.members.append(CommitteeMember(name="นายสิรธีร์ ตีเมืองซ้าย", position="ครู", role="ผู้ตรวจรับ"))
    p.committees.append(c)

    path = render_document("รายงานขอซื้อ", p, school)
    doc = Docx(path)
    n = len(doc.inline_shapes)
    print("จำนวนรูปในเอกสาร:", n)
    assert n >= 1, "ไม่พบตราครุฑในเอกสาร!"
    # ตรวจว่าไม่มีข้อความ placeholder หลงเหลือ
    txt = "\n".join(pp.text for pp in doc.paragraphs)
    assert "วางไฟล์ครุฑ" not in txt, "ยังเป็น placeholder อยู่ (ไม่ได้ใช้รูปจริง)"
    print("ผ่าน: เอกสารมีตราครุฑฝังอยู่ ->", path.split("\\")[-1])


if __name__ == "__main__":
    main()
