"""ทดสอบ flow เฟส 2 ผ่านเซิร์ฟเวอร์จริง (http://127.0.0.1:8000)"""
import io
import httpx
from docx import Document as Docx

BASE = "http://127.0.0.1:8000"


def docx_text(content: bytes) -> str:
    doc = Docx(io.BytesIO(content))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    c = httpx.Client(base_url=BASE, follow_redirects=True, timeout=20)

    # 1) ตั้งค่าโรงเรียน
    r = c.post("/settings", data={
        "name": "โรงเรียนบ้านหินลาด", "address": "ต.ท่าสองคอน อ.เมือง จ.มหาสารคาม",
        "director_name": "นายอัครพงศ์ ศรีวงศ์", "director_position": "ผู้อำนวยการโรงเรียน",
        "officer_name": "นายสิรธีร์ ตีเมืองซ้าย", "head_officer_name": "นางสาวประทุมพร จันทะเกต",
        "doc_prefix": "ศธ", "doc_set_threshold": "5000",
    })
    assert r.status_code == 200
    print("[1] ตั้งค่าโรงเรียน: OK")

    # 2) มาสเตอร์ลิสต์
    c.post("/masters/person", data={"name": "นายสิรธีร์ ตีเมืองซ้าย", "position": "ครู"})
    c.post("/masters/department", data={"name": "ฝ่ายบริหารงานวิชาการ"})
    c.post("/masters/project", data={"name": "วันสำคัญทางวิชาการ"})
    r = c.get("/masters")
    assert "ฝ่ายบริหารงานวิชาการ" in r.text
    print("[2] เพิ่มมาสเตอร์ลิสต์ (บุคลากร/ฝ่าย/โครงการ): OK")

    # 3) ผู้ขาย
    c.post("/vendors", data={"name": "ร้านวัฒนาเครื่องเขียน"})
    db_vendor = c.get("/vendors").text
    assert "ร้านวัฒนาเครื่องเขียน" in db_vendor

    # 4) สร้างเรื่อง #1 (ผู้ตรวจรับคนเดียว) — memo_no เว้นให้ระบบเสนอ = 1/2569
    r = c.get("/procurement/new")
    assert "1/2569" in r.text, "ไม่เสนอเลขบันทึก 1/2569"
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "memo_no": "1/2569", "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุโครงการวันคริสต์มาส", "project_name": "วันสำคัญทางวิชาการ",
        "department": "ฝ่ายบริหารงานวิชาการ", "purpose": "ใช้จัดกิจกรรม",
        "budget_source": "อุดหนุน", "price_ref_source": "การสืบราคาจากท้องตลาด", "delivery_days": "3",
        "inspection_mode": "single",
        "item_name": ["สีไม้", "สมุด"], "item_qty": ["20", "60"],
        "item_unit": ["กล่อง", "เล่ม"], "item_price": ["70", "10"],
        "member_name": ["นายสิรธีร์ ตีเมืองซ้าย"], "member_position": ["ครู"], "member_role": ["ผู้ตรวจรับ"],
    })
    assert r.status_code == 200
    assert "วัสดุโครงการวันคริสต์มาส" in r.text
    assert "2,000.00" in r.text  # 20*70 + 60*10 = 1400+600 = 2000
    assert "ผู้ตรวจรับคนเดียว" in r.text
    pid1 = r.url.path.split("/")[-1]
    print(f"[4] สร้างเรื่อง #1 (คนเดียว) id={pid1} + คำนวณยอด 2,000: OK")

    # 5) ออกเอกสารรายงานขอซื้อ
    r = c.post(f"/procurement/{pid1}/generate", data={"doc_kind": "รายงานขอซื้อ"})
    assert r.status_code == 200 and "wordprocessing" in r.headers.get("content-type", "")
    txt = docx_text(r.content)
    assert "วัสดุโครงการวันคริสต์มาส" in txt
    assert "สองพันบาทถ้วน" in txt, "บาทถ้วนผิด/หาย"
    assert "โดยอนุโลม" in txt, "ข้อความผู้ตรวจรับคนเดียวหาย"
    assert "นายสิรธีร์ ตีเมืองซ้าย" in txt
    assert "สีไม้" in txt and "สมุด" in txt
    print("[5] ออกเอกสารรายงานขอซื้อ (คนเดียว): OK")

    # 6) ทดสอบ override + bump: สร้างเรื่อง #2 ใส่ memo_no=5/2569 เอง
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "memo_no": "5/2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง",
        "subject": "จ้างทำป้ายไวนิล", "delivery_days": "2", "inspection_mode": "committee",
        "item_name": ["ป้ายไวนิล"], "item_qty": ["6"], "item_unit": ["ป้าย"], "item_price": ["466.67"],
        "member_name": ["นายมรรคพันธุ์ คุณวงศ์", "นายเกริกไกร สุขเพลีย", "นายจักรพงษ์ ดงอุทิศ"],
        "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
    })
    assert r.status_code == 200
    pid2 = r.url.path.split("/")[-1]
    # หลังใส่ 5/2569 -> เลขถัดไปที่เสนอควรเป็น 6/2569
    r = c.get("/procurement/new")
    assert "6/2569" in r.text, "ระบบไม่ bump เลขเป็น 6/2569 หลังพิมพ์ทับ 5"
    print("[6] override เลข 5/2569 แล้วระบบ bump เป็น 6/2569: OK")

    # 7) เอกสารโหมดคณะกรรมการ
    r = c.post(f"/procurement/{pid2}/generate", data={"doc_kind": "รายงานขอซื้อ"})
    txt = docx_text(r.content)
    assert "คณะกรรมการตรวจรับ ดังนี้" in txt
    assert "นายมรรคพันธุ์ คุณวงศ์" in txt and "ประธานกรรมการ" in txt
    assert "รายงานขอจ้าง" in txt
    print("[7] เอกสารโหมดคณะกรรมการ 3 คน: OK")

    # 8) ทะเบียน Excel
    r = c.get("/register.xlsx?year=2569")
    assert r.status_code == 200 and "spreadsheet" in r.headers.get("content-type", "")
    print("[8] ทะเบียน Excel: OK")

    print("\n=== เฟส 2 ผ่านทุกการทดสอบผ่านเซิร์ฟเวอร์จริง ===")
    c.close()


if __name__ == "__main__":
    main()
