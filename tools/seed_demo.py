# -*- coding: utf-8 -*-
"""
seed_demo.py - สร้าง "โรงเรียนสาธิต" สำหรับถ่ายคลิป/สอนงาน โดยไม่แตะข้อมูลโรงเรียนจริง

ทำไมปลอดภัย
  ระบบแยกฐานข้อมูลรายโรงเรียน (data/schools/<id>/school.db) สคริปต์นี้สร้าง tenant
  ใหม่ที่ slug = "demo" แล้วเขียนเฉพาะฐานของ tenant นั้น ไม่เคยเปิดฐานของโรงเรียนอื่น
  และจะหยุดทันทีถ้าพบว่า slug demo ไปชนกับ tenant ที่มีข้อมูลจริงอยู่

วิธีใช้
  python tools/seed_demo.py              # สร้าง/เติมข้อมูลสาธิต (ถ้ามีอยู่แล้วจะเตือน)
  python tools/seed_demo.py --reset      # ล้างฐานสาธิตแล้วสร้างใหม่ (ถ่ายพลาดก็รันซ้ำได้)
  python tools/seed_demo.py --password xxxxx   # ตั้งรหัสผ่านเอง (ไม่ระบุ = สุ่มให้)
  python tools/seed_demo.py --remove     # ลบโรงเรียนสาธิตทิ้งทั้งหมด (ใช้หลังถ่ายเสร็จ)

ข้อมูลที่ได้ ครอบคลุมทุกหน้าจอที่ต้องถ่าย
  ตั้งค่าโรงเรียนครบ (ชื่อ ที่อยู่ ผอ. เจ้าหน้าที่พัสดุ หัวหน้าเจ้าหน้าที่)
  บุคลากร 8 คน · ผู้ขาย 3 ราย
  ครุภัณฑ์ 12 รายการ สภาพคละกัน (ใช้งาน/ชำรุด/เสื่อมสภาพ/สูญไป/ไม่ใช้) รวมลอตเลขช่วง
  วัสดุ 6 รายการ มีรับเข้า-จ่ายออกทั้งปี · ใบเบิก 2 ใบ
  เรื่องจัดซื้อ 2 เรื่อง (ตรวจรับเสร็จแล้ว 1 · กำลังดำเนินการ 1)
  สำนวนจำหน่ายพัสดุ 1 เรื่อง กรอกครบถึงขั้นรอลงจ่าย (กดปุ่มลงจ่ายสดในคลิปได้)
"""
import argparse
import random
import secrets
import shutil
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEMO_SLUG = "demo"
DEMO_NAME = "โรงเรียนบ้านตัวอย่าง (สาธิต)"
DEMO_USER = "demo"


def _fail(msg):
    print("\n[หยุด] " + msg)
    sys.exit(1)


# ------------------------------------------------------------------ tenant
def _find_or_make_tenant(reset: bool, password: str | None):
    from app import accounts as ac
    from app.accounts import Account, Tenant, acc_session, hash_password
    from app.modules import ALL_MODULES_CSV

    with acc_session() as s:
        t = s.query(Tenant).filter_by(slug=DEMO_SLUG).first()
        if t and t.name != DEMO_NAME:
            _fail(f'slug "{DEMO_SLUG}" ถูกใช้โดย "{t.name}" ซึ่งไม่ใช่โรงเรียนสาธิต\n'
                  "       ไม่แตะข้อมูลนี้ - เปลี่ยน slug ของโรงเรียนนั้นก่อน แล้วรันใหม่")
        if t is None:
            t = Tenant(name=DEMO_NAME, slug=DEMO_SLUG, active=True, plan="member",
                       max_users=5, modules=ALL_MODULES_CSV, docs_limit=0,
                       policy_accepted_at=datetime.now(), policy_version="demo")
            s.add(t)
            s.flush()
            print(f"  สร้างโรงเรียนสาธิต  id={t.id}")
        else:
            t.active = True
            t.modules = ALL_MODULES_CSV
            t.docs_limit = 0
            t.expiry_date = None
            print(f"  ใช้โรงเรียนสาธิตเดิม id={t.id}")
        tid = t.id

        pw = password or ("demo" + "".join(
            random.choice(string.digits) for _ in range(4)))
        a = s.query(Account).filter_by(username=DEMO_USER).first()
        if a and a.tenant_id != tid:
            _fail(f'ไอดี "{DEMO_USER}" เป็นของโรงเรียนอื่นอยู่แล้ว - ไม่แตะข้อมูลนี้')
        if a is None:
            a = Account(tenant_id=tid, username=DEMO_USER, display_name="ผู้ดูแล (สาธิต)",
                        role="user", is_owner=True, active=True, welcomed=True,
                        verified=True, must_change_password=False)
            s.add(a)
        a.password_hash = hash_password(pw)
        a.must_change_password = False
        a.active = True
        s.commit()
    return tid, pw


def _close_engine(tid):
    """ปิด engine ของ tenant นี้ก่อนแตะไฟล์ - บน Windows ลบไฟล์ที่ยังเปิดอยู่ไม่ได้"""
    from app import tenancy as tn
    pair = tn._engines.pop(tid, None)
    if pair:
        try:
            pair[0].dispose()
        except Exception:
            pass


def _reset_db(tid):
    from app import tenancy as tn
    path = tn.school_db_path(tid)
    _close_engine(tid)
    for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                _fail(f"ลบไฟล์ {p.name} ไม่ได้ เพราะมีโปรแกรมอื่นเปิดค้างอยู่\n"
                      "       ปิดเซิร์ฟเวอร์ (uvicorn) ก่อนแล้วรันใหม่")
    print(f"  ล้างฐานข้อมูลสาธิตแล้ว: {path}")


# ------------------------------------------------------------------ seed
PERSONS = [
    ("นายเอนก สมมุติชัย", "ผู้อำนวยการโรงเรียน"),
    ("นางสาวปราณี พัสดุงาม", "ครูชำนาญการ"),
    ("นายวิชัย ครุภัณฑ์ดี", "ครู"),
    ("นางสมศรี ตรวจสอบดี", "ครูชำนาญการ"),
    ("นายสมชาย นับของครบ", "ครู"),
    ("นางมาลี บันทึกงาน", "ครู"),
    ("นายประเมิน ราคาเป็น", "ครูชำนาญการ"),
    ("นางวรรณา ขายคล่อง", "ครูชำนาญการ"),
]
VENDORS = [
    ("ร้านตัวอย่างการค้า", "3301234567890", "เลขที่ 12 ถ.มิตรภาพ ต.ในเมือง อ.เมือง จ.นครราชสีมา",
     "044-111222", "นายสมมติ ค้าขาย"),
    ("หจก. สาธิตพาณิชย์", "3309876543210", "เลขที่ 88 ถ.สุรนารี ต.ในเมือง อ.เมือง จ.นครราชสีมา",
     "044-333444", "นางสาธิต มีสุข"),
    ("ร้านรับซื้อของเก่าสมชายพาณิชย์", "3305555555555",
     "เลขที่ 7 ถ.ราชสีมา ต.หนองบัว อ.เมือง จ.นครราชสีมา", "044-555666", "นายสมชาย เก่าไป"),
]
# (เลขครุภัณฑ์, ชื่อ, ประเภท, ยี่ห้อ/รุ่น, ราคาต่อหน่วย, จำนวน, หน่วย, สถานะ, สถานที่, ปีที่ได้มา)
ASSETS = [
    ("7440-001-0001/2569", "เครื่องปรับอากาศ แบบแยกส่วน 18,000 บีทียู", "ครุภัณฑ์สำนักงาน",
     "COOLMAX CM-18K", 25000.0, 1, "เครื่อง", "ใช้งาน", "ห้องธุรการ", 2569),
    ("7440-001-0002/2569", "เครื่องปรับอากาศ แบบแยกส่วน 18,000 บีทียู", "ครุภัณฑ์สำนักงาน",
     "COOLMAX CM-18K", 25000.0, 1, "เครื่อง", "ชำรุด", "ห้องวิชาการ", 2569),
    ("7440-002-0003/2567", "ตู้เหล็กเก็บเอกสาร 4 ลิ้นชัก", "ครุภัณฑ์สำนักงาน",
     "STEELPRO", 5500.0, 1, "ตู้", "เสื่อมสภาพ", "ห้องธุรการ", 2567),
    ("7440-002-0004/2567", "โต๊ะทำงานพร้อมเก้าอี้ ระดับ 3-6", "ครุภัณฑ์สำนักงาน",
     "OFFICEMATE", 4800.0, 1, "ชุด", "ใช้งาน", "ห้องธุรการ", 2567),
    ("7010-001-0005/2566", "เครื่องคอมพิวเตอร์ตั้งโต๊ะ สำหรับงานสำนักงาน", "ครุภัณฑ์คอมพิวเตอร์",
     "TECHNO T-500", 22000.0, 1, "เครื่อง", "ชำรุด", "ห้องคอมพิวเตอร์", 2566),
    ("7010-001-0006/2566", "เครื่องคอมพิวเตอร์ตั้งโต๊ะ สำหรับงานสำนักงาน", "ครุภัณฑ์คอมพิวเตอร์",
     "TECHNO T-500", 22000.0, 1, "เครื่อง", "สูญไป", "ห้องคอมพิวเตอร์", 2566),
    ("7010-002-0007/2565", "เครื่องพิมพ์เลเซอร์ ขาว-ดำ", "ครุภัณฑ์คอมพิวเตอร์",
     "PRINTEX PX-200", 7900.0, 1, "เครื่อง", "เสื่อมสภาพ", "ห้องธุรการ", 2565),
    # ลอตเลขช่วง - ไว้โชว์ปุ่ม "แยกเป็นรายชิ้น" ในคลิป
    ("บต/04/01/01-40/2564", "ชุดโต๊ะ-เก้าอี้นักเรียน ระดับประถมศึกษา", "ครุภัณฑ์การศึกษา",
     "ไม้ยางพารา โครงเหล็ก", 1450.0, 40, "ชุด", "ใช้งาน", "อาคารเรียน 2", 2564),
    ("บต/04/01/41-48/2564", "ชุดโต๊ะ-เก้าอี้นักเรียน ระดับประถมศึกษา", "ครุภัณฑ์การศึกษา",
     "ไม้ยางพารา โครงเหล็ก", 1450.0, 8, "ชุด", "ชำรุด", "อาคารเรียน 2", 2564),
    ("7440-003-0008/2563", "เครื่องขยายเสียงเคลื่อนที่ พร้อมลำโพง", "ครุภัณฑ์โฆษณาและเผยแพร่",
     "SOUNDPRO", 12800.0, 1, "ชุด", "ไม่ใช้", "ห้องโสตทัศนศึกษา", 2563),
    ("7440-004-0009/2562", "เครื่องตัดหญ้า แบบสะพายบ่า", "ครุภัณฑ์งานบ้านงานครัว (เครื่องจักรกล)",
     "GARDENMAX", 9500.0, 1, "เครื่อง", "ชำรุด", "อาคารพัสดุ", 2562),
    ("7440-005-0010/2568", "โทรทัศน์ แอล อี ดี ขนาด 55 นิ้ว", "ครุภัณฑ์โฆษณาและเผยแพร่",
     "VIEWTEC 55X", 18900.0, 1, "เครื่อง", "ใช้งาน", "ห้องประชุม", 2568),
]
# (ชื่อ, หน่วย, หมวด, ราคาต่อหน่วย, รับเข้า, จ่ายออก)
MATERIALS = [
    ("กระดาษถ่ายเอกสาร A4 80 แกรม", "รีม", "วัสดุสำนักงาน", 120.0, 200, 145),
    ("หมึกพิมพ์เลเซอร์ รุ่น PX-200", "กล่อง", "วัสดุคอมพิวเตอร์", 2400.0, 12, 8),
    ("น้ำยาทำความสะอาดพื้น", "ขวด", "วัสดุงานบ้านงานครัว", 85.0, 60, 41),
    ("ปากกาลูกลื่น สีน้ำเงิน", "ด้าม", "วัสดุสำนักงาน", 7.0, 300, 220),
    ("แฟ้มสันกว้าง 3 นิ้ว", "แฟ้ม", "วัสดุสำนักงาน", 95.0, 50, 22),
    ("สีทาอาคาร ชนิดทาภายนอก", "ถัง", "วัสดุก่อสร้าง", 1850.0, 8, 5),
]


def seed(tid):
    from app.models import (Asset, MaterialItem, MaterialTxn, Person, Procurement,
                            ProcurementItem, School, Vendor)
    from app.tenancy import session_for

    db = session_for(tid)
    if db.query(Asset).count() or db.query(Procurement).count():
        db.close()
        _fail("ฐานข้อมูลสาธิตมีข้อมูลอยู่แล้ว - ใช้ --reset ถ้าต้องการล้างแล้วสร้างใหม่")

    sc = db.query(School).first() or School()
    if sc.id is None:
        db.add(sc)
    sc.name = "โรงเรียนบ้านตัวอย่าง"
    sc.address = "เลขที่ 99 หมู่ 5 ต.ในเมือง อ.เมือง จ.นครราชสีมา 30000"
    sc.district = "เมือง"
    sc.province = "นครราชสีมา"
    sc.area_office = "สำนักงานเขตพื้นที่การศึกษาประถมศึกษานครราชสีมา เขต 1"
    sc.director_name = "นายเอนก สมมุติชัย"
    sc.head_officer_name = "นางสาวปราณี พัสดุงาม"
    sc.officer_name = "นายวิชัย ครุภัณฑ์ดี"
    sc.doc_prefix = "ศธ"
    sc.academic_year = 2569

    for name, pos in PERSONS:
        db.add(Person(name=name, position=pos, active=True))
    vendors = []
    for name, tax, addr, phone, owner in VENDORS:
        v = Vendor(name=name, tax_id=tax, address=addr, phone=phone, owner_name=owner)
        db.add(v)
        vendors.append(v)
    db.flush()

    for code, name, cat, brand, cost, qty, unit, status, loc, year in ASSETS:
        db.add(Asset(asset_code=code, name=name, category=cat, brand_model=brand,
                     cost=cost, quantity=qty, unit=unit, status=status, location=loc,
                     useful_life=8, salvage_value=1.0, fund_type="เงินงบประมาณ",
                     acquire_method="วิธีเฉพาะเจาะจง", vendor_name=vendors[0].name,
                     doc_ref=f"ใบส่งของเลขที่ {year - 2500}/{year}",
                     acquired_date=datetime(year - 543, 8, 31)))

    for name, unit, cat, price, qin, qout in MATERIALS:
        m = MaterialItem(name=name, unit=unit, category=cat)
        db.add(m)
        db.flush()
        db.add(MaterialTxn(material_id=m.id, kind="in", qty=qin, unit_price=price,
                           ref="ใบส่งของ 12/2569", date=datetime(2025, 11, 14)))
        db.add(MaterialTxn(material_id=m.id, kind="out", qty=qout,
                           note="นางสาวปราณี พัสดุงาม", ref="ใบเบิก 30/2569",
                           date=datetime(2026, 3, 9)))

    # ---- เรื่องจัดซื้อ 2 เรื่อง ----
    p1 = Procurement(
        fiscal_year=2569, subject="ซื้อวัสดุสำนักงาน", proc_type="ซื้อ",
        method="เฉพาะเจาะจง", proc_case="normal", budget_source="เงินอุดหนุนรายหัว",
        department="งานบริหารทั่วไป", purpose="ใช้ในงานสำนักงานของโรงเรียน",
        total_amount=28400.0, vendor_id=vendors[0].id, status="ตรวจรับแล้ว",
        memo_no="ศธ 04166.05/120", request_date=datetime(2025, 11, 4),
        quotation_date=datetime(2025, 11, 6), order_date=datetime(2025, 11, 10),
        delivery_date=datetime(2025, 11, 14), inspect_date=datetime(2025, 11, 14),
        delivery_days=7, vat_mode="include")
    db.add(p1)
    db.flush()
    for nm, q, u, up in [("กระดาษถ่ายเอกสาร A4 80 แกรม", 200, "รีม", 120.0),
                         ("ปากกาลูกลื่น สีน้ำเงิน", 300, "ด้าม", 7.0),
                         ("แฟ้มสันกว้าง 3 นิ้ว", 50, "แฟ้ม", 95.0)]:
        db.add(ProcurementItem(procurement_id=p1.id, name=nm, quantity=q, unit=u,
                               unit_price=up))
    p2 = Procurement(
        fiscal_year=2569, subject="ซื้อครุภัณฑ์โฆษณาและเผยแพร่", proc_type="ซื้อ",
        method="เฉพาะเจาะจง", proc_case="normal", budget_source="เงินอุดหนุนรายหัว",
        department="งานบริหารทั่วไป", purpose="ใช้ในห้องประชุมของโรงเรียน",
        total_amount=18900.0, vendor_id=vendors[1].id, status="รายงานขอซื้อ",
        memo_no="ศธ 04166.05/175", request_date=datetime(2026, 6, 2), delivery_days=15)
    db.add(p2)
    db.flush()
    db.add(ProcurementItem(procurement_id=p2.id, name="โทรทัศน์ แอล อี ดี ขนาด 55 นิ้ว",
                           quantity=1, unit="เครื่อง", unit_price=18900.0))
    db.commit()
    n_asset = db.query(Asset).count()
    n_mat = db.query(MaterialItem).count()
    db.close()
    return n_asset, n_mat


def seed_disposal(tid):
    """สำนวนจำหน่ายพัสดุ กรอกครบถึงขั้น "รอลงจ่าย" - ในคลิปกดปุ่มลงจ่ายสดได้เลย"""
    import json

    from app.models import Asset, AssetDisposal, AssetDisposalItem
    from app.tenancy import session_for

    db = session_for(tid)
    mem = {
        "fact": [("นางสมศรี ตรวจสอบดี", "ครูชำนาญการ", "ประธานกรรมการ"),
                 ("นายสมชาย นับของครบ", "ครู", "กรรมการ"),
                 ("นางมาลี บันทึกงาน", "ครู", "กรรมการและเลขานุการ")],
        "price": [("นายประเมิน ราคาเป็น", "ครูชำนาญการ", "ประธานกรรมการ"),
                  ("นายสมชาย นับของครบ", "ครู", "กรรมการ"),
                  ("นางมาลี บันทึกงาน", "ครู", "กรรมการ")],
        "sale": [("นางวรรณา ขายคล่อง", "ครูชำนาญการ", "ประธานกรรมการ"),
                 ("นายวิชัย ครุภัณฑ์ดี", "ครู", "กรรมการ"),
                 ("นางมาลี บันทึกงาน", "ครู", "กรรมการ")],
        "destroy": [("นายสมชาย นับของครบ", "ครู", "ประธานกรรมการ"),
                    ("นายวิชัย ครุภัณฑ์ดี", "ครู", "กรรมการ"),
                    ("นางมาลี บันทึกงาน", "ครู", "กรรมการ")],
        "auction": [("นางวรรณา ขายคล่อง", "ครูชำนาญการ", "ประธานกรรมการ"),
                    ("นายวิชัย ครุภัณฑ์ดี", "ครู", "กรรมการ"),
                    ("นางมาลี บันทึกงาน", "ครู", "กรรมการ")],
    }
    members = json.dumps(
        {k: [{"name": n, "position": p, "role": r} for n, p, r in v]
         for k, v in mem.items()}, ensure_ascii=False)
    dp = AssetDisposal(
        year=2569, stage="sell", sale_mode="auction", members=members,
        fact_memo_no="ศธ 04166.05/205", fact_memo_date=datetime(2026, 10, 2),
        fact_order_no="65/2569", fact_order_date=datetime(2026, 10, 3), fact_days=7,
        fact_report_no="ศธ 04166.05/215", fact_report_date=datetime(2026, 10, 10),
        fact_start=datetime(2026, 10, 5), fact_end=datetime(2026, 10, 9),
        fact_found="ครุภัณฑ์ชำรุดเสื่อมสภาพจากการใช้งานตามปกติ จำนวน 4 รายการ "
                   "และเครื่องคอมพิวเตอร์สูญหาย 1 เครื่อง จากเหตุอุทกภัยเมื่อเดือนตุลาคม 2568",
        fact_opinion="ครุภัณฑ์ที่ชำรุดมีอายุการใช้งานเกินกำหนดแล้ว หากซ่อมแซมจะไม่คุ้มค่า "
                     "ส่วนเครื่องคอมพิวเตอร์ที่สูญหายเกิดจากภัยธรรมชาติ ไม่ปรากฏตัวผู้รับผิด",
        req_memo_no="ศธ 04166.05/220", req_memo_date=datetime(2026, 10, 12),
        order_no="68/2569", order_date=datetime(2026, 10, 12),
        auction_order_no="69/2569", auction_order_date=datetime(2026, 10, 13),
        notice_date=datetime(2026, 10, 14),
        view_date=datetime(2026, 10, 24), view_time="09.00 - 12.00 น.",
        auction_date=datetime(2026, 10, 27), auction_time="10.00 น.",
        auction_place="อาคารอเนกประสงค์ โรงเรียนบ้านตัวอย่าง",
        auction_report_no="ศธ 04166.05/232", auction_report_date=datetime(2026, 10, 28),
        price_memo_no="ศธ 04166.05/225", price_memo_date=datetime(2026, 10, 20),
        buyer_name="ร้านรับซื้อของเก่าสมชายพาณิชย์",
        buyer_address="เลขที่ 7 ถ.ราชสีมา ต.หนองบัว อ.เมือง จ.นครราชสีมา",
        buyer_taxid="3305555555555", sale_total=18500.0,
        bidders="ร้านรับซื้อของเก่าสมชายพาณิชย์|18500\n"
                "นายประมูล ซื้อขายดี|16200\nห้างหุ้นส่วนจำกัด รีไซเคิลไทย|15000",
        destroy_memo_no="ศธ 04166.05/236", destroy_memo_date=datetime(2026, 10, 30),
        destroy_date=datetime(2026, 10, 29), destroy_way="ทุบและฝังกลบ",
        wo_memo_no="ศธ 04166.05/238", wo_memo_date=datetime(2026, 10, 30),
        wo_reason="เครื่องคอมพิวเตอร์สูญหายจากเหตุอุทกภัย ไม่ปรากฏตัวผู้รับผิด "
                  "และไม่มีตัวพัสดุเหลืออยู่ จึงไม่สามารถจำหน่ายตามวิธีในข้อ 215 ได้",
        wo_no_liable=True,
        area_no="ศธ 04166.05/245", sao_no="ศธ 04166.05/246",
        sao_kind="จังหวัด", sao_region="นครราชสีมา", mof_no="ศธ 04166.05/247",
        revenue_kind="แผ่นดิน", remit_no="ศธ 04166.05/248",
        contact_phone="044-255100")
    db.add(dp)
    db.flush()
    PLAN = {
        "7440-001-0002/2569": ("ขาย", "ใช้งานมา 7 ปี คอมเพรสเซอร์เสีย ซ่อมไม่คุ้มค่า", 4000.0),
        "7440-002-0003/2567": ("ขาย", "สนิมกัดกร่อน รางลิ้นชักหัก", 800.0),
        "7010-001-0005/2566": ("ขาย", "เมนบอร์ดเสียหายจากไฟกระชาก", 1500.0),
        "7440-004-0009/2562": ("ขาย", "เครื่องยนต์เสีย ใช้งานมานาน", 1200.0),
        "7440-003-0008/2563": ("ขาย", "ล้าสมัย โรงเรียนไม่มีความจำเป็นต้องใช้แล้ว", 3000.0),
        "บต/04/01/41-48/2564": ("ทำลาย", "ไม้ผุ โครงเหล็กหัก ไม่สามารถซ่อมได้", 0.0),
        "7010-001-0006/2566": ("จำหน่ายเป็นสูญ", "สูญหายจากเหตุอุทกภัย ตุลาคม 2568", 0.0),
    }
    n = 0
    for a in db.query(Asset).all():
        if a.asset_code in PLAN:
            act, cause, mid = PLAN[a.asset_code]
            db.add(AssetDisposalItem(disposal_id=dp.id, asset_id=a.id, action=act,
                                     cause=cause, price_mid=mid,
                                     receipt_no="ร.15/2569" if act == "ขาย" else ""))
            n += 1
    db.commit()
    db.close()
    return n


def remove_demo():
    from app.accounts import Account, Tenant, acc_session
    from app import tenancy as tn
    from app.database import get_data_dir

    with acc_session() as s:
        t = s.query(Tenant).filter_by(slug=DEMO_SLUG).first()
        if t is None:
            print("  ไม่พบโรงเรียนสาธิต - ไม่มีอะไรต้องลบ")
            return
        if t.name != DEMO_NAME:
            _fail(f'slug "{DEMO_SLUG}" เป็นของ "{t.name}" ซึ่งไม่ใช่โรงเรียนสาธิต - ไม่ลบ')
        tid = t.id
        s.query(Account).filter_by(tenant_id=tid).delete()
        s.delete(t)
        s.commit()
    _close_engine(tid)
    folder = get_data_dir() / "schools" / str(tid)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    print(f"  ลบโรงเรียนสาธิตแล้ว (id={tid}) พร้อมไฟล์ฐานข้อมูล")


def main():
    ap = argparse.ArgumentParser(description="สร้างโรงเรียนสาธิตสำหรับถ่ายคลิป")
    ap.add_argument("--reset", action="store_true",
                    help="ล้างฐานข้อมูลสาธิตแล้วสร้างใหม่")
    ap.add_argument("--remove", action="store_true", help="ลบโรงเรียนสาธิตทิ้งทั้งหมด")
    ap.add_argument("--password", help="ตั้งรหัสผ่านเอง (ไม่ระบุ = สุ่มให้)")
    args = ap.parse_args()

    print("\n=== ชุดข้อมูลสาธิต Easy Ekkasan ===")
    if args.remove:
        remove_demo()
        return

    tid, pw = _find_or_make_tenant(args.reset, args.password)
    if args.reset:
        _reset_db(tid)
    n_asset, n_mat = seed(tid)
    n_disp = seed_disposal(tid)

    print(f"  ครุภัณฑ์ {n_asset} รายการ · วัสดุ {n_mat} รายการ · "
          f"เรื่องจัดซื้อ 2 เรื่อง · สำนวนจำหน่าย 1 เรื่อง ({n_disp} รายการ)")
    print("\n  เข้าใช้งาน")
    print(f"     ไอดี      {DEMO_USER}")
    print(f"     รหัสผ่าน  {pw}")
    print(f"     ฐานข้อมูล data/schools/{tid}/school.db  (แยกจากโรงเรียนจริงคนละไฟล์)")
    print("\n  ถ่ายเสร็จแล้วลบทิ้งด้วย  python tools/seed_demo.py --remove\n")


if __name__ == "__main__":
    main()
