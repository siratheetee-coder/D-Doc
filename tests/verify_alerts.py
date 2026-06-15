# -*- coding: utf-8 -*-
"""ตรวจระดับความด่วนของกระดิ่งแจ้งเตือน: ร่าง / รอตรวจรับ / ใกล้ครบ / เลยกำหนด"""
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import (School, Vendor, Procurement, ProcurementItem, Person, Department,
                        Project, DocNumberCounter, Committee, CommitteeMember, Document)
from app.routers.pages import nav_alerts

def reset():
    db = SessionLocal()
    for M in (Document, CommitteeMember, Committee, ProcurementItem, Procurement,
              DocNumberCounter, Vendor, Person, Department, Project, School):
        db.query(M).delete()
    db.commit(); db.close()

reset()
db = SessionLocal()
today = datetime.now()
db.add_all([
    Procurement(memo_no="1/2569", subject="ร่างค้าง", proc_type="ซื้อ", fiscal_year=2569, status="ร่าง"),
    Procurement(memo_no="2/2569", subject="รอตรวจรับ", proc_type="ซื้อ", fiscal_year=2569, status="อนุมัติ",
                delivery_due_date=today + timedelta(days=30)),
    Procurement(memo_no="3/2569", subject="ใกล้ครบ", proc_type="ซื้อ", fiscal_year=2569, status="อนุมัติ",
                delivery_due_date=today + timedelta(days=3)),
    Procurement(memo_no="4/2569", subject="เลยกำหนด", proc_type="ซื้อ", fiscal_year=2569, status="อนุมัติ",
                delivery_due_date=today - timedelta(days=5)),
    Procurement(memo_no="5/2569", subject="เสร็จแล้ว", proc_type="ซื้อ", fiscal_year=2569, status="เบิกจ่ายแล้ว"),
])
db.commit(); db.close()

a = nav_alerts()
by = {x["title"].split()[0]: x for x in a}
print("จำนวนแจ้งเตือน:", len(a), "(คาดหวัง 4 = ไม่รวมที่เบิกจ่ายแล้ว)")
for x in a:
    print(" ", x["level"], "|", x["reason"], "|", x["title"])
assert len(a) == 4, "ไม่ควรนับรายการที่เบิกจ่ายแล้ว"
assert a[0]["level"] == "urgent" and "เลยกำหนด" in a[0]["reason"], "ด่วนสุดต้องเป็นเลยกำหนด"
assert by["3/2569"]["level"] == "warn", "ใกล้ครบ = warn"
assert by["2/2569"]["reason"] == "รอตรวจรับ"
assert by["1/2569"]["level"] == "info" and "ร่าง" in by["1/2569"]["reason"]
print("\nOK: ระดับแจ้งเตือนถูกต้อง + เรียงด่วนสุดก่อน + ข้ามรายการที่เสร็จแล้ว")
print("(เหลือข้อมูลตัวอย่าง 5 เรื่องไว้ให้ดูกระดิ่งทำงานจริง: เปิด http://127.0.0.1:8000)")
