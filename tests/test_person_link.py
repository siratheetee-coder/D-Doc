"""ทดสอบ: ตำแหน่งเลือกได้ + ผูกบุคลากรกับ role + auto-fill ตำแหน่ง"""
import re
from fastapi.testclient import TestClient
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


def main():
    reset()
    c = TestClient(app)
    # เพิ่มบุคลากร: นายอัครพงศ์ = ผู้อำนวยการโรงเรียน
    c.post("/masters/person", data={"name": "นายอัครพงศ์ ศรีวงศ์", "position": "ผู้อำนวยการโรงเรียน"})
    c.post("/masters/person", data={"name": "นายสิรธีร์ ตีเมืองซ้าย", "position": "เจ้าหน้าที่"})

    # masters: มี dropdown ตำแหน่ง + แสดงชื่อเต็ม (คอลัมน์กว้าง)
    m = c.get("/masters").text
    assert 'id="positions"' in m and "ผู้อำนวยการโรงเรียน" in m, "ไม่มี dropdown ตำแหน่ง"
    assert 'width:50%' in m, "คอลัมน์ชื่อควรกว้างขึ้น"
    print("[1] masters: dropdown ตำแหน่ง + คอลัมน์ชื่อกว้าง: OK")

    # settings: role เลือกจากบุคลากรได้ (datalist persons)
    s = c.get("/settings").text
    assert '<datalist id="persons">' in s and "นายอัครพงศ์ ศรีวงศ์" in s, "settings ไม่มี datalist บุคลากร"
    assert 'name="director_name" list="persons"' in s, "ผอ. ควรเลือกจากบุคลากรได้"
    assert 'name="head_officer_name" list="persons"' in s
    print("[2] settings: ผอ./เจ้าหน้าที่/หัวหน้า เลือกจากบุคลากรได้: OK")

    # ตั้ง ผอ. = นายอัครพงศ์ -> เอกสารต้องใช้ชื่อนี้เป็น ผอ.
    c.post("/settings", data={"name": "ร.ร.ทดสอบ", "director_name": "นายอัครพงศ์ ศรีวงศ์",
                              "officer_name": "นายสิรธีร์ ตีเมืองซ้าย", "head_officer_name": "นายสิรธีร์ ตีเมืองซ้าย"})
    db = SessionLocal(); sc = db.query(School).first()
    assert sc.director_name == "นายอัครพงศ์ ศรีวงศ์"
    db.close()
    print("[3] กำหนด ผอ. จากบุคลากร -> ระบบจำเป็นผู้ลงนามเอกสาร: OK")

    # create form: มี PERSON_POS (auto-fill) + member_position เลือกตำแหน่งได้
    f = c.get("/procurement/new").text
    assert "PERSON_POS" in f and "ผู้อำนวยการโรงเรียน" in f, "ไม่มีแผนที่ชื่อ->ตำแหน่ง"
    assert 'name="member_position" list="positions"' in f, "ตำแหน่งกรรมการควรเลือกได้"
    print("[4] create form: เลือกชื่อ -> เติมตำแหน่งอัตโนมัติ (PERSON_POS) + dropdown: OK")

    print("\n=== ผูกบุคลากร-ตำแหน่ง + dropdown + ช่องกว้าง ผ่านทั้งหมด ===")


if __name__ == "__main__":
    main()
