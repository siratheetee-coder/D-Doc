"""
ทดสอบการทำงานจริงผ่าน HTTP (จำลองการกรอกฟอร์มจากเบราว์เซอร์)
รันด้วย: .venv\\Scripts\\python.exe -m tests.test_http_flow
"""
import os
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import School, Vendor, Procurement, ProcurementItem, DocNumberCounter
from app.main import app


def reset_db():
    db = SessionLocal()
    db.query(ProcurementItem).delete()
    db.query(Procurement).delete()
    db.query(DocNumberCounter).delete()
    db.query(School).delete()
    db.query(Vendor).delete()
    db.commit()
    db.close()


def main():
    reset_db()
    client = TestClient(app)

    # 1) ตั้งค่าโรงเรียน (ส่งฟอร์มแบบ UTF-8 เหมือนเบราว์เซอร์)
    r = client.post("/settings", data={
        "name": "โรงเรียนบ้านหนองทดสอบ",
        "director_name": "นายสมชาย ใจดี",
        "director_position": "ผู้อำนวยการโรงเรียน",
        "supply_officer": "นางสาวสมหญิง รักงาน",
        "doc_prefix": "ศธ", "address": "123 หมู่ 4",
    })
    assert r.status_code == 200, r.status_code

    # 2) เพิ่มผู้ขาย
    r = client.post("/vendors", data={"name": "ร้านเครื่องเขียนวิทยา", "tax_id": "1234567890123"})
    assert r.status_code == 200
    db = SessionLocal()
    vendor = db.query(Vendor).first()
    db.close()

    # 3) สร้าง 3 เรื่อง -> ตรวจรันเลขต่อเนื่อง
    doc_nos = []
    for i in range(3):
        r = client.post("/procurement/new", data=[
            ("fiscal_year", "2569"),
            ("proc_type", "ซื้อ"), ("method", "เฉพาะเจาะจง"),
            ("subject", f"วัสดุสำนักงานชุดที่ {i+1}"),
            ("purpose", "ใช้ในการจัดการเรียนการสอน"),
            ("budget_source", "เงินอุดหนุนรายหัว"),
            ("vendor_id", str(vendor.id)),
            ("item_name", "กระดาษ A4"), ("item_qty", "10"), ("item_unit", "รีม"), ("item_price", "125.50"),
            ("item_name", "ปากกา"), ("item_qty", "24"), ("item_unit", "ด้าม"), ("item_price", "8"),
        ])
        assert r.status_code == 200, r.text[:300]

    db = SessionLocal()
    procs = db.query(Procurement).order_by(Procurement.id).all()
    doc_nos = [p.doc_no for p in procs]
    print("เลขที่หนังสือ:", doc_nos)
    assert doc_nos == ["1/2569", "2/2569", "3/2569"], doc_nos
    # ตรวจ subject ไม่เพี้ยน
    print("ชื่อเรื่องเก็บถูกต้อง:", procs[0].subject)
    assert procs[0].subject == "วัสดุสำนักงานชุดที่ 1"
    assert abs(procs[0].total_amount - (10*125.50 + 24*8)) < 0.01
    last_id = procs[-1].id
    db.close()

    # 4) ออกเอกสาร Word ผ่าน endpoint จริง
    for kind in ["รายงานขอซื้อขอจ้าง", "ใบตรวจรับพัสดุ"]:
        r = client.post(f"/procurement/{last_id}/generate", data={"doc_kind": kind})
        assert r.status_code == 200, r.status_code
        cd = r.headers.get("content-disposition", "")
        assert ".docx" in cd, cd
        assert len(r.content) > 5000  # ได้ไฟล์จริง
        print(f"ออกเอกสาร {kind}: OK ({len(r.content)} bytes)")

    # 5) ดาวน์โหลดทะเบียน Excel
    r = client.get("/register.xlsx?year=2569")
    assert r.status_code == 200
    assert len(r.content) > 3000
    print("ดาวน์โหลดทะเบียน Excel: OK")

    # 6) ตรวจชื่อไฟล์ที่สร้างจริงในโฟลเดอร์ (ต้องเป็นภาษาไทยถูกต้อง ไม่มี _ แทน)
    docs = os.listdir("data/documents")
    bad = [d for d in docs if "____" in d]
    assert not bad, f"พบชื่อไฟล์เพี้ยน: {bad}"
    print("ชื่อไฟล์ภาษาไทยถูกต้อง ไม่มีการเพี้ยน")

    # 7) หน้า dashboard แสดงผลได้
    r = client.get("/?year=2569")
    assert r.status_code == 200
    assert "วัสดุสำนักงานชุดที่ 1" in r.text
    print("Dashboard แสดงรายการถูกต้อง")

    print("\n=== ผ่านทุกการทดสอบ (HTTP end-to-end) ===")


if __name__ == "__main__":
    main()
