"""ทดสอบการเติมข้อมูลลงแม่แบบ docxtpl (โหมดผู้ตรวจรับคนเดียว และคณะกรรมการ)"""
from docx import Document as Docx

from app.models import School, Procurement, ProcurementItem, Committee, CommitteeMember
from app.services.render import render_document


def make_school():
    return School(
        name="โรงเรียนบ้านหินลาด", address="ตำบลท่าสองคอน อำเภอเมือง จังหวัดมหาสารคาม",
        director_name="นายอัครพงศ์ ศรีวงศ์", director_position="ผู้อำนวยการโรงเรียน",
        officer_name="นายสิรธีร์ ตีเมืองซ้าย", head_officer_name="นางสาวประทุมพร จันทะเกต",
        doc_prefix="ศธ",
    )


def make_proc(mode, members):
    p = Procurement(
        fiscal_year=2569, memo_no="68/2569", subject="วัสดุโครงการวันคริสต์มาส",
        project_name="วันสำคัญทางวิชาการ", department="ฝ่ายบริหารงานวิชาการ",
        purpose="ใช้จัดกิจกรรมวันคริสต์มาส", proc_type="ซื้อ", method="เฉพาะเจาะจง",
        budget_source="อุดหนุน", total_amount=4370.0, delivery_days=3,
        inspection_mode=mode,
    )
    p.items.append(ProcurementItem(name="สีไม้", quantity=20, unit="กล่อง", unit_price=70))
    p.items.append(ProcurementItem(name="สมุด", quantity=60, unit="เล่ม", unit_price=10))
    c = Committee(kind="inspect", mode=mode)
    for i, (nm, pos, role) in enumerate(members):
        c.members.append(CommitteeMember(name=nm, position=pos, role=role, seq=i))
    p.committees.append(c)
    return p


def text_of(path):
    doc = Docx(path)
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    school = make_school()

    # --- โหมดผู้ตรวจรับคนเดียว ---
    p1 = make_proc("single", [("นายสิรธีร์ ตีเมืองซ้าย", "ครู", "ผู้ตรวจรับ")])
    f1 = render_document("รายงานขอซื้อ", p1, school)
    t1 = text_of(f1)
    assert "วัสดุโครงการวันคริสต์มาส" in t1
    assert "สี่พันสามร้อยเจ็ดสิบบาทถ้วน" in t1, "บาทถ้วนหาย"
    assert "โดยอนุโลม" in t1, "ข้อความผู้ตรวจรับคนเดียวหาย"
    assert "นายสิรธีร์ ตีเมืองซ้าย" in t1
    assert "คณะกรรมการตรวจรับ ดังนี้" not in t1, "ไม่ควรมีข้อความคณะกรรมการในโหมดคนเดียว"
    assert "สีไม้" in t1 and "สมุด" in t1, "loop ตารางพัสดุไม่ทำงาน"
    assert "4,370" in t1 and "4,370.00" not in t1, "ควรตัด .00 สำหรับจำนวนเต็ม"
    print("[1] โหมดผู้ตรวจรับคนเดียว: OK ->", f1.split("\\")[-1])

    # --- โหมดคณะกรรมการ ---
    members = [
        ("นายมรรคพันธุ์ คุณวงศ์", "ครู", "ประธานกรรมการ"),
        ("ว่าที่ร้อยตรีเกริกไกร สุขเพลีย", "ครู", "กรรมการ"),
        ("นายจักรพงษ์ ดงอุทิศ", "ครู", "กรรมการและเลขานุการ"),
    ]
    p2 = make_proc("committee", members)
    p2.proc_type = "จ้าง"
    f2 = render_document("รายงานขอซื้อ", p2, school)
    t2 = text_of(f2)
    assert "คณะกรรมการตรวจรับ ดังนี้" in t2, "ข้อความคณะกรรมการหาย"
    assert "โดยอนุโลม" not in t2, "ไม่ควรมีข้อความคนเดียวในโหมดคณะกรรมการ"
    for nm, _, role in members:
        assert nm in t2, f"ไม่พบกรรมการ {nm}"
        assert role in t2, f"ไม่พบบทบาท {role}"
    assert "รายงานขอจ้าง" in t2, "proc_type ไม่แทนค่า"
    print("[2] โหมดคณะกรรมการ 3 คน: OK ->", f2.split("\\")[-1])

    # --- ใบตรวจรับพัสดุ: ผู้ตรวจรับคนเดียว (จากเรื่องซื้อ p1) ---
    ti1 = text_of(render_document("ใบตรวจรับพัสดุ", p1, school))
    assert "ใบตรวจรับพัสดุ" in ti1 and "ข้อ 175" in ti1
    assert "ผู้ตรวจรับพัสดุ" in ti1 and "คณะกรรมการตรวจรับพัสดุ" not in ti1
    assert "นายสิรธีร์ ตีเมืองซ้าย" in ti1
    assert "ใบสั่งซื้อ" in ti1 and "ผู้ขาย" in ti1
    assert "ขออนุมัติเบิกจ่ายเงินให้ผู้ขาย" in ti1
    assert "สี่พันสามร้อยเจ็ดสิบบาทถ้วน" in ti1
    print("[3] ใบตรวจรับพัสดุ (คนเดียว/ซื้อ): OK")

    # --- ใบตรวจรับพัสดุ: คณะกรรมการ (จากเรื่องจ้าง p2) ---
    ti2 = text_of(render_document("ใบตรวจรับพัสดุ", p2, school))
    assert "คณะกรรมการตรวจรับพัสดุ" in ti2
    assert "ใบสั่งจ้าง" in ti2 and "ผู้รับจ้าง" in ti2
    for nm, _, role in members:
        assert nm in ti2 and role in ti2
    print("[4] ใบตรวจรับพัสดุ (คณะกรรมการ/จ้าง): OK")

    # --- ใบสั่งซื้อ (จากเรื่องซื้อ p1) ---
    po1 = text_of(render_document("ใบสั่งซื้อ/สั่งจ้าง", p1, school))
    assert "ใบสั่งซื้อ" in po1 and "ผู้สั่งซื้อ" in po1
    assert "สีไม้" in po1 and "สมุด" in po1
    assert "สี่พันสามร้อยเจ็ดสิบบาทถ้วน" in po1
    print("[5] ใบสั่งซื้อ (เรื่องซื้อ): OK")

    # --- ใบสั่งจ้าง (จากเรื่องจ้าง p2) ---
    po2 = text_of(render_document("ใบสั่งซื้อ/สั่งจ้าง", p2, school))
    assert "ใบสั่งจ้าง" in po2 and "ผู้สั่งจ้าง" in po2 and "ผู้รับจ้าง" in po2
    print("[6] ใบสั่งจ้าง (เรื่องจ้าง): OK")

    # --- รายงานผลการพิจารณาฯ (จากเรื่องจ้าง p2) ---
    rr = text_of(render_document("รายงานผลการพิจารณา", p2, school))
    assert "รายงานผลการพิจารณาและขออนุมัติสั่งจ้าง" in rr
    assert "ข้อ 79" in rr and "ข้อ 24" in rr
    assert "อนุมัติให้สั่งจ้าง" in rr
    assert "มีอาชีพรับจ้าง" in rr
    print("[7] รายงานผลการพิจารณาฯ: OK")

    # --- คำสั่งแต่งตั้งผู้ตรวจรับ (จากเรื่องจ้าง p2 คณะกรรมการ) ---
    cmd = text_of(render_document("คำสั่งแต่งตั้งผู้ตรวจรับ", p2, school))
    assert "คำสั่งโรงเรียนบ้านหินลาด" in cmd
    assert "แต่งตั้งผู้ตรวจรับพัสดุ" in cmd
    assert "คณะกรรมการตรวจรับพัสดุ" in cmd
    for nm, _, role in members:
        assert nm in cmd and role in cmd, f"ไม่พบ {nm}/{role} ในคำสั่ง"
    print("[8] คำสั่งแต่งตั้งผู้ตรวจรับ (loop กรรมการ): OK")

    # --- 5 ใบที่เหลือ (ใช้ p2 จ้าง/คณะกรรมการ) ---
    q = text_of(render_document("ใบเสนอราคา", p2, school))
    assert "ใบเสนอราคา" in q and "ผู้เสนอราคา" in q and "ผู้ต่อรองราคา" in q
    assert "สีไม้" in q
    print("[9] ใบเสนอราคา: OK")

    wn = text_of(render_document("ประกาศผู้ชนะ", p2, school))
    assert "ประกาศ" in wn and "ผู้ชนะการเสนอราคา" in wn and "เสนอราคาต่ำสุด" in wn
    print("[10] ประกาศผู้ชนะ: OK")

    sc = text_of(render_document("แต่งตั้งกรรมการคุณลักษณะ", p2, school))
    assert "คุณลักษณะเฉพาะ" in sc and "ข้อ 21" in sc
    for nm, _, _ in members:
        assert nm in sc
    print("[11] แต่งตั้งกรรมการคุณลักษณะ: OK")

    tor = text_of(render_document("รายละเอียดคุณลักษณะ(TOR)", p2, school))
    assert "TOR" in tor and "ราคากลาง" in tor and "หลักเกณฑ์" in tor
    print("[12] TOR: OK")

    dn = text_of(render_document("ใบส่งมอบงาน", p2, school))
    assert "ใบส่งมอบงาน" in dn and "แจ้งหนี้ขอเบิกเงิน" in dn
    print("[13] ใบส่งมอบงาน: OK")

    print("\n=== แม่แบบครบ 10/10 ทำงานถูกต้อง (loop + เงื่อนไข + ภาษาไทย) ===")


if __name__ == "__main__":
    main()
