"""
ทดสอบกับเซิร์ฟเวอร์จริงที่รันอยู่ (http://127.0.0.1:8000) ด้วย httpx ผ่าน socket จริง
นี่คือเส้นทางเดียวกับที่เบราว์เซอร์ใช้ (ส่งฟอร์มแบบ UTF-8)
ไฟล์นี้บันทึกเป็น UTF-8 จึงไม่มีปัญหา encoding ของซอร์สโค้ด
"""
import httpx

BASE = "http://127.0.0.1:8000"


def main():
    c = httpx.Client(base_url=BASE, follow_redirects=True, timeout=15)

    # 1) ตั้งค่าโรงเรียน (ภาษาไทย)
    r = c.post("/settings", data={
        "name": "โรงเรียนบ้านหนองทดสอบ",
        "director_name": "นายสมชาย ใจดี",
        "director_position": "ผู้อำนวยการโรงเรียน",
        "supply_officer": "นางสาวสมหญิง รักงาน",
        "doc_prefix": "ศธ", "address": "123 หมู่ 4 ต.ทดสอบ",
    })
    assert r.status_code == 200
    # ยืนยันว่าหน้า settings แสดงชื่อไทยกลับมาถูกต้อง
    assert "โรงเรียนบ้านหนองทดสอบ" in r.text, "ชื่อโรงเรียนเพี้ยน!"
    print("[1] ตั้งค่าโรงเรียน + อ่านกลับมาเป็นไทยถูกต้อง: OK")

    # 2) เพิ่มผู้ขาย
    r = c.post("/vendors", data={"name": "ร้านเครื่องเขียนวิทยา", "tax_id": "1234567890123"})
    assert r.status_code == 200
    assert "ร้านเครื่องเขียนวิทยา" in r.text
    print("[2] เพิ่มผู้ขาย: OK")

    # 3) สร้างเรื่องจัดซื้อ (มีหลายรายการ -> ส่ง key ซ้ำด้วย list)
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569",
        "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุสำนักงาน",
        "purpose": "ใช้ในการจัดการเรียนการสอน",
        "budget_source": "เงินอุดหนุนรายหัว",
        "item_name": ["กระดาษ A4", "ปากกาลูกลื่น"],
        "item_qty": ["10", "24"],
        "item_unit": ["รีม", "ด้าม"],
        "item_price": ["125.50", "8"],
    })
    assert r.status_code == 200
    # หน้า detail ต้องโชว์ชื่อเรื่องไทยถูกต้อง + ยอดเงิน
    assert "วัสดุสำนักงาน" in r.text, "ชื่อเรื่องเพี้ยน!"
    assert "กระดาษ A4" in r.text and "ปากกาลูกลื่น" in r.text
    # ยอดรวม = 10*125.50 + 24*8 = 1447.00
    assert "1,447.00" in r.text, "ยอดเงินผิด!"
    print("[3] สร้างเรื่องจัดซื้อ + ชื่อไทย + คำนวณยอดเงินถูกต้อง: OK")

    # 4) หาเลขที่หนังสือที่รันให้
    import re
    m = re.search(r"/procurement/(\d+)", r.url.path) if hasattr(r, "url") else None
    # ดึง id จาก url หลัง redirect
    proc_id = r.url.path.split("/")[-1]
    print(f"    เลขที่หนังสือถูกออกอัตโนมัติ, id={proc_id}")

    # 5) ออกเอกสาร Word ทั้งสองชนิด
    for kind in ["รายงานขอซื้อขอจ้าง", "ใบตรวจรับพัสดุ"]:
        r = c.post(f"/procurement/{proc_id}/generate", data={"doc_kind": kind})
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "wordprocessing" in ct, ct
        assert len(r.content) > 5000
        print(f"[5] ออกเอกสาร {kind}: OK ({len(r.content)} bytes)")

    # 6) ทะเบียน Excel
    r = c.get("/register.xlsx?year=2569")
    assert r.status_code == 200
    assert "spreadsheet" in r.headers.get("content-type", "")
    print("[6] ดาวน์โหลดทะเบียน Excel: OK")

    # 7) Dashboard
    r = c.get("/?year=2569")
    assert "วัสดุสำนักงาน" in r.text
    print("[7] Dashboard แสดงรายการเป็นไทยถูกต้อง: OK")

    print("\n=== ผ่านทุกการทดสอบผ่านเซิร์ฟเวอร์จริง ===")
    c.close()


if __name__ == "__main__":
    main()
