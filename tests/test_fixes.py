"""ตรวจการแก้บั๊ก: โครงการซ้ำ + .00 (จำลองเคสจริงจากภาพ export ของผู้ใช้)"""
from docx import Document as Docx
from app.models import School, Procurement, ProcurementItem, Committee, CommitteeMember
from app.services.render import render_document


def text_of(path):
    doc = Docx(path)
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    school = School(name="โรงเรียนบ้านหินลาด", director_name="นายอัครพงศ์ ศรีวงศ์",
                    officer_name="นายสิรธีร์ ตีเมืองซ้าย", head_officer_name="นางสาวประทุมพร จันทะเกต")
    p = Procurement(fiscal_year=2569, memo_no="1/2569", proc_type="จ้าง",
                    subject="จัดทำป้ายไวนิลสถานศึกษาสีขาว",
                    project_name="โครงการสถานศึกษาสีขาว",   # ขึ้นต้นด้วย 'โครงการ'
                    department="ฝ่ายบริหารงานทั่วไป", method="เฉพาะเจาะจง",
                    total_amount=3610.0, inspection_mode="single")
    p.items.append(ProcurementItem(name="ป้ายไวนิล", quantity=1, unit="ป้าย", unit_price=3610))
    c = Committee(kind="inspect", mode="single")
    c.members.append(CommitteeMember(name="นายเนติพงษ์ มาตรเรียง", position="ครู", role="ผู้ตรวจรับ"))
    p.committees.append(c)

    t = text_of(render_document("รายงานขอซื้อ", p, school))

    assert "โครงการโครงการ" not in t, "ยังมีคำว่าโครงการซ้ำ!"
    assert "ตามโครงการสถานศึกษาสีขาว" in t, "ข้อความโครงการไม่ถูก"
    assert "3,610.00" not in t, "ยังมี .00"
    assert "3,610 บาท" in t, "เลขเงินไม่ถูก"
    assert "สามพันหกร้อยสิบบาทถ้วน" in t
    assert "รายละเอียดงานที่จะจ้างคือ" in t, "ถ้อยคำข้อ 2 ยังไม่แก้"
    assert "โรงเรียนบ้านหินลาด" in t, "ส่วนราชการ/ผอ. ควรมีชื่อโรงเรียน"
    print("ผ่าน: ไม่มีโครงการซ้ำ, ตัด .00, ถ้อยคำข้อ 2 ถูก, มีชื่อโรงเรียน")


if __name__ == "__main__":
    main()
