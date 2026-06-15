"""ทดสอบฟีเจอร์แก้ไขเลขที่/วันที่ภายหลัง + ออกใบสั่งซื้อ/จ้าง + วันที่ไหลเข้าเอกสาร"""
import io
import httpx
from docx import Document as Docx

BASE = "http://127.0.0.1:8000"


def docx_text(content):
    doc = Docx(io.BytesIO(content))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def main():
    c = httpx.Client(base_url=BASE, follow_redirects=True, timeout=20)

    c.post("/settings", data={
        "name": "โรงเรียนบ้านหินลาด", "address": "ต.ท่าสองคอน อ.เมือง จ.ขอนแก่น",
        "director_name": "นายอัครพงศ์ ศรีวงศ์", "officer_name": "นายสิรธีร์ ตีเมืองซ้าย",
        "head_officer_name": "นางสาวประทุมพร จันทะเกต", "doc_set_threshold": "5000",
    })
    c.post("/vendors", data={"name": "นายชัชชัย ธรรมเวียง", "tax_id": "3440100413359",
                             "address": "50 ต.ตลาด อ.เมือง จ.ขอนแก่น", "bank_account": "123-4-56789-0"})
    import re
    vid = re.search(r'/vendors/(\d+)/delete', c.get("/vendors").text).group(1)

    # สร้างเรื่องจ้าง
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "memo_no": "68/2569", "proc_type": "จ้าง", "method": "เฉพาะเจาะจง",
        "subject": "จัดทำป้ายไวนิล", "delivery_days": "2", "inspection_mode": "committee",
        "vendor_id": vid,
        "item_name": ["ป้ายไวนิล"], "item_qty": ["6"], "item_unit": ["ป้าย"], "item_price": ["930"],
        "member_name": ["นายมรรคพันธุ์ คุณวงศ์", "นายเกริกไกร สุขเพลีย", "นายจักรพงษ์ ดงอุทิศ"],
        "member_position": ["ครู", "ครู", "ครู"],
        "member_role": ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"],
    })
    pid = r.url.path.split("/")[-1]
    print(f"[1] สร้างเรื่องจ้าง id={pid}: OK")

    # แก้ไขเลขที่ + วันที่ภายหลัง
    r = c.post(f"/procurement/{pid}/update-refs", data={
        "memo_no": "68/2569", "order_no": "9/2569", "command_no": "33/2569",
        "result_memo_no": "71/2569", "spec_memo_no": "", "inspect_memo_no": "",
        "request_date": "2026-03-19", "order_date": "2026-03-25",
        "delivery_due_date": "2026-03-27", "inspect_date": "2026-03-26",
    })
    assert r.status_code == 200
    page = r.text
    assert 'value="9/2569"' in page and 'value="33/2569"' in page, "เลขที่ไม่ถูกบันทึก"
    assert 'value="2026-03-25"' in page, "วันที่ใบสั่งไม่ถูกบันทึก"
    print("[2] แก้ไขเลขที่ + วันที่ภายหลัง: OK")

    # ระบบ bump เลขใบสั่งจ้าง -> เสนอ 10/2569
    assert "เสนอ 10/2569" in page, "counter ใบสั่งจ้างไม่ bump"
    print("[3] counter ใบสั่งจ้าง bump เป็น 10/2569: OK")

    # ออกใบสั่งจ้าง -> ตรวจวันที่/เลข/ผู้รับจ้างไหลเข้าเอกสาร
    r = c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบสั่งซื้อ/สั่งจ้าง"})
    t = docx_text(r.content)
    assert "ใบสั่งจ้าง" in t and "9/2569" in t
    assert "นายชัชชัย ธรรมเวียง" in t and "3440100413359" in t
    assert "25 มีนาคม 2569" in t, "วันที่ใบสั่งไม่เข้าเอกสาร"
    assert "27 มีนาคม 2569" in t, "ครบกำหนดส่งมอบไม่เข้าเอกสาร"
    print("[4] ใบสั่งจ้าง: เลข+วันที่+ผู้รับจ้างไหลเข้าเอกสารถูกต้อง: OK")

    # ออกใบตรวจรับ -> วันที่ตรวจรับ/ใบสั่งเข้าเอกสาร (ไม่เป็นจุดไข่ปลา)
    r = c.post(f"/procurement/{pid}/generate", data={"doc_kind": "ใบตรวจรับพัสดุ"})
    t = docx_text(r.content)
    assert "26 มีนาคม 2569" in t, "วันที่ตรวจรับไม่เข้าเอกสาร"
    assert "9/2569" in t, "เลขใบสั่งไม่เข้าใบตรวจรับ"
    print("[5] ใบตรวจรับ: วันที่ตรวจรับ + เลขใบสั่งไหลเข้าเอกสาร: OK")

    print("\n=== ฟีเจอร์แก้ไขเลขที่/วันที่ภายหลัง + ใบสั่งซื้อจ้าง ผ่านทั้งหมด ===")
    c.close()


if __name__ == "__main__":
    main()
