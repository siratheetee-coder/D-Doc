# -*- coding: utf-8 -*-
"""
procurement_setup.py - รายการเริ่มต้นงานพัสดุ (หน้าหลักพัสดุ)

แบบเดียวกับงานการเงิน (finance_setup.py): ติ๊กจากข้อมูลจริง ขั้นถัดไปขั้นเดียว ครบแล้วหายเอง
ลำดับตามที่เอกสารต้องใช้: ข้อมูลโรงเรียนและผู้ลงนาม > บุคลากรไว้แต่งตั้งกรรมการ
> ผู้ขาย/ผู้รับจ้าง > แผนจัดซื้อจัดจ้างประจำปี (ระเบียบฯ ข้อ 11 ต้องประกาศต้นปีงบ) > เรื่องแรก
"""
from app.models import Person, Procurement, ProcurementPlan, Vendor

# ช่องที่เอกสารพัสดุทุกฉบับใช้ ไม่กรอกแล้วเอกสารมีช่องว่าง
SCHOOL_FIELDS = [("name", "ชื่อโรงเรียน"), ("director_name", "ชื่อผู้อำนวยการ"),
                 ("officer_name", "เจ้าหน้าที่พัสดุ"), ("head_officer_name", "หัวหน้าเจ้าหน้าที่พัสดุ")]
MIN_PERSONS = 1          # ซื้อวงเงินเล็กใช้ผู้ตรวจรับคนเดียวได้ โรงเรียนเล็กมีครูไม่ถึง 3 (เจ้าของเลือก)


def setup_steps(db, fy, school) -> dict:
    missing = [label for key, label in SCHOOL_FIELDS if not (getattr(school, key, "") or "").strip()]
    n_person = db.query(Person).filter(Person.active.isnot(False)).count()
    n_vendor = db.query(Vendor).count()
    n_plan = db.query(ProcurementPlan).filter_by(fiscal_year=fy).count()
    n_proc = db.query(Procurement).filter_by(fiscal_year=fy).count()
    steps = [
        dict(title="กรอกข้อมูลโรงเรียนและผู้ลงนาม", done=not missing,
             detail=("ชื่อโรงเรียน ผู้อำนวยการ และเจ้าหน้าที่พัสดุครบแล้ว" if not missing
                     else "ยังไม่ได้กรอก: " + ", ".join(missing) + " · ไม่กรอกแล้วเอกสารที่ออกจะมีช่องว่าง"),
             href="/settings", cta="ไปตั้งค่าโรงเรียน"),
        dict(title="เพิ่มรายชื่อบุคลากร", done=n_person >= MIN_PERSONS,
             detail=(f"มี {n_person} คน" if n_person >= MIN_PERSONS
                     else "ยังไม่มีรายชื่อ เพิ่มครูไว้เลือกเป็นผู้ตรวจรับหรือกรรมการ "
                          "เช่น ครูสมชาย ครูสมหญิง นำเข้าจาก Excel ได้"),
             href="/masters", cta="เพิ่มบุคลากร"),
        dict(title="เพิ่มผู้ขายหรือผู้รับจ้าง", done=n_vendor > 0,
             detail=(f"มี {n_vendor} ราย" if n_vendor
                     else "ร้านที่ซื้อของหรือจ้างประจำ เช่น ร้านเครื่องเขียน กรอกครั้งเดียว ใช้ซ้ำได้ทุกเรื่อง"),
             href="/vendors", cta="เพิ่มผู้ขาย"),
        dict(title=f"ทำแผนจัดซื้อจัดจ้างปีงบ {fy}", done=n_plan > 0,
             detail=(f"มี {n_plan} รายการในแผน" if n_plan
                     else "ระเบียบกำหนดให้ประกาศแผนต้นปีงบ เช่น จัดซื้อวัสดุสำนักงาน 30,000 บาท "
                          "ระบบออกประกาศเผยแพร่แผนให้"),
             href=f"/procurement/plan?year={fy}", cta="ทำแผนจัดซื้อจัดจ้าง"),
        dict(title="ทำเรื่องจัดซื้อจัดจ้างเรื่องแรก", done=n_proc > 0,
             detail=(f"ปีงบ {fy} มี {n_proc} เรื่อง" if n_proc
                     else "เลือกซื้อหรือจ้าง กรอกรายการ ระบบออกเอกสารให้ครบชุด"),
             href="/procurement/new", cta="สร้างเรื่องใหม่",
             extra=[("ไม่แน่ใจว่าต้องใช้วิธีไหน? ให้ระบบช่วยเลือก", "/procurement/wizard")]),
    ]
    for n, s in enumerate(steps, 1):
        s["n"] = n
        s.setdefault("extra", [])
    nxt = next((s for s in steps if not s["done"]), None)
    done = sum(1 for s in steps if s["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)
