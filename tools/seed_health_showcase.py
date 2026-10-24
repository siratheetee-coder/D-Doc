# -*- coding: utf-8 -*-
"""ข้อมูลตัวอย่างที่ทำให้หน้าตรวจสุขภาพข้อมูลการเงินขึ้นครบทุกข้อ (ใช้ตรวจคำและลิงก์ของแต่ละข้อ)

ใช้กับฐานทดลองเท่านั้น ห้ามรันกับข้อมูลโรงเรียนจริง
- ปีงบปัจจุบัน: เกือบทุกข้อ (โรงเรียนเริ่มใช้ระบบกลางทางด้วยยอดยกมา)
- ปีงบปัจจุบัน - 2: "ยอดยกมาไม่ตรงยอดสิ้นปีก่อน" (ขึ้นพร้อม "รายการก่อนเริ่มใช้ระบบ" ในปีเดียวกันไม่ได้)
- "ใกล้สิ้นปีงบ ใช้เงินน้อย" ขึ้นเฉพาะ ก.ค. ถึง ก.ย. จึงไม่อยู่ในชุดนี้

ใช้ในเทสต์ (tests/test_finance_health.py) และเปิดดูบนเซิร์ฟเวอร์ทดลอง: seed(db) แล้วเปิด /finance/health
"""
import json
from datetime import datetime, timedelta


def seed(db, now=None) -> dict:
    from app.models import (School, FinanceAccount, AccountItem, AccountOpening, FinanceTxn, Project, Procurement,
                            ProcurementItem, DisburseMemo, Vendor, MoneyLoan, CheckPayment, Receipt, PlanBudget,
                            PlanFunding, LunchProgram, LunchClass, LunchHireRound, SubsidySnapshot,
                            SubsidyReceiptLink, SubsidyItemMapping)
    from app.thai_utils import current_fiscal_year, current_academic_year
    now = now or datetime.now()
    fy, ay = current_fiscal_year(now), current_academic_year(now)
    ce = fy - 544                                   # ปีงบ fy เริ่ม 1 ต.ค. ค.ศ. ce
    db.query(School).first().project_year_mode = "academic"

    # ---- เงินอุดหนุน: ยอดยกมากรอกเท่างบที่ตั้งไว้ทุกหมวด
    sub = FinanceAccount(name="เงินอุดหนุนทั่วไป")
    lunch_acc = FinanceAccount(name="อาหารกลางวัน")
    petty = FinanceAccount(name="เงินสดย่อย", deposit_type="cash")
    old = FinanceAccount(name="เงินรายได้สถานศึกษา")
    db.add_all([sub, lunch_acc, petty, old]); db.flush()
    teach = AccountItem(account_id=sub.id, fiscal_year=fy, name="ค่าจัดการเรียนการสอน", budget=263360, opening_balance=263360)
    book = AccountItem(account_id=sub.id, fiscal_year=fy, name="ค่าหนังสือเรียน", budget=80512.2, opening_balance=80512.2)
    meal = AccountItem(account_id=lunch_acc.id, fiscal_year=fy, name="ค่าอาหาร", opening_balance=100)
    db.add_all([teach, book, meal,
                AccountOpening(account_id=sub.id, fiscal_year=fy, amount=343872.2),
                AccountOpening(account_id=lunch_acc.id, fiscal_year=fy, amount=100),
                AccountOpening(account_id=petty.id, fiscal_year=fy, amount=3000)])
    db.flush()
    recent = now - timedelta(days=3)
    db.add_all([
        FinanceTxn(account_id=lunch_acc.id, fiscal_year=fy - 1, kind="out", amount=127200, date=datetime(ce, 9, 10),
                   note="จ้างเหมาอาหารกลางวัน รอบ 2"),                                      # ก่อนเริ่มใช้ระบบ
        FinanceTxn(account_id=sub.id, item_id=teach.id, fiscal_year=fy, kind="out", amount=500,
                   date=datetime(ce, 9, 20), note="ค่าวัสดุ (วันที่อยู่ปีงบก่อน)"),            # ลงผิดปีงบ
        FinanceTxn(account_id=lunch_acc.id, item_id=meal.id, fiscal_year=fy, kind="out", amount=900,
                   date=datetime(ce, 10, 5), note="ค่าอาหารเสริม"),                           # หมวดติดลบ
        FinanceTxn(account_id=sub.id, item_id=teach.id, fiscal_year=fy, kind="out", amount=250, date=recent,
                   note="ซื้อน้ำดื่ม"),
        FinanceTxn(account_id=sub.id, item_id=teach.id, fiscal_year=fy, kind="out", amount=250, date=recent,
                   note="ซื้อน้ำดื่ม"),                                                      # อาจลงซ้ำ
        FinanceTxn(account_id=sub.id, fiscal_year=fy, kind="out", amount=120, date=recent,
                   note="ค่าไปรษณีย์ (ไม่ได้เลือกหมวด)"),                                     # ไม่ระบุหมวด
    ])
    # ---- ปีงบ fy-2: ยอดยกมาไม่ตรงยอดสิ้นปีก่อน (ปีงบ fy-3 มีเงินเข้า 5,000 แต่ยกมาแค่ 1,000)
    db.add_all([FinanceTxn(account_id=old.id, fiscal_year=fy - 3, kind="in", amount=5000, date=datetime(ce - 3, 12, 1),
                           note="เงินบริจาค"),
                AccountOpening(account_id=old.id, fiscal_year=fy - 2, amount=1000)])

    # ---- เงินอุดหนุนรับเกินที่คำนวณไว้ (ภาคเรียนที่ 2 ของปีการศึกษา ay = ปีงบ fy)
    db.add(SubsidyItemMapping(fiscal_year=fy, item_key="teach", account_item_id=teach.id))
    got = FinanceTxn(account_id=sub.id, item_id=teach.id, fiscal_year=fy, kind="in", amount=200000,
                     date=datetime(ce, 10, 15), note="รับเงินอุดหนุนค่าจัดการเรียนการสอน ภาคเรียนที่ 2")
    db.add(got); db.flush()
    db.add(SubsidySnapshot(academic_year=ay, term=2, fiscal_year=fy, payload=json.dumps(
        {"token": "showcase", "result": {"rows": [{"key": "teach", "name": "ค่าจัดการเรียนการสอน",
                                                    "allocated": 150000, "full": 150000}]}})))
    db.add(SubsidyReceiptLink(txn_id=got.id, academic_year=ay, term=2, item_key="teach", round="first", amount=200000))

    # ---- โครงการ
    no_budget = Project(name="โครงการอาหารกลางวันและอาหารเสริมนม", budget=0, plan_year=ay)
    special = Project(name="โครงการวันสำคัญทางวิชาการ", budget=15000, plan_year=ay)
    over = Project(name="โครงการส่งเสริมความเป็นเลิศ", budget=1000, plan_year=ay)
    db.add_all([no_budget, special, over]); db.flush()
    shop = Vendor(name="ร้านรุ่งเรืองพาณิชย์")
    notax = Vendor(name="ร้านไม่มีเลขภาษี")
    db.add_all([shop, notax]); db.flush()
    db.add_all([
        Procurement(fiscal_year=fy - 1, memo_no="10/x", subject="จ้างเหมาประกอบอาหาร", proc_type="จ้าง",
                    total_amount=132000, order_date=datetime(ay - 543, 5, 18), project_id=no_budget.id),
        Procurement(fiscal_year=fy - 1, memo_no="3/x", subject="วัสดุวันสำคัญ", proc_type="ซื้อ", total_amount=4990,
                    order_date=datetime(ay - 544, 11, 12), project_id=special.id),           # นอกช่วงปีการศึกษา
        Procurement(fiscal_year=fy, memo_no="11/x", subject="ชุดอุปกรณ์แข่งขัน", proc_type="ซื้อ", total_amount=1500,
                    order_date=datetime(ay - 543, 6, 1), project_id=over.id, vendor_id=notax.id),
        Procurement(fiscal_year=fy, memo_no="1/s", subject="กระดาษ", vendor_id=shop.id, total_amount=9000,
                    order_date=datetime(ce, 11, 1)),
        Procurement(fiscal_year=fy, memo_no="2/s", subject="หมึกพิมพ์", vendor_id=shop.id, total_amount=9500,
                    order_date=datetime(ce, 11, 10)),                                         # แบ่งซื้อ?
    ])
    over_memo = Procurement(fiscal_year=fy, memo_no="20/x", subject="วัสดุสำนักงาน", total_amount=1000,
                            order_date=datetime(ce, 10, 8))
    nb = Procurement(fiscal_year=fy, memo_no="4/s", subject="โน้ตบุ๊ก", proc_type="ซื้อ", total_amount=22000,
                     order_date=datetime(ce, 10, 2), inspect_date=datetime(ce, 10, 9))
    db.add_all([over_memo, nb]); db.flush()
    db.add(ProcurementItem(procurement_id=nb.id, name="โน้ตบุ๊ก", quantity=1, unit_price=22000))
    db.add_all([
        DisburseMemo(fiscal_year=fy, memo_no="1/x", subject="วัสดุสำนักงาน", amount=800, procurement_id=over_memo.id),
        DisburseMemo(fiscal_year=fy, memo_no="2/x", subject="วัสดุสำนักงาน", amount=800, procurement_id=over_memo.id),
        DisburseMemo(fiscal_year=fy, memo_no="5/x", subject="ค่าซ่อมพัดลม", amount=3000, status="อนุมัติ",
                     date=now - timedelta(days=60), payee="ร้านไม่มีเลขภาษี", wht=30),
    ])

    # ---- เงินยืม เช็ค ใบเสร็จ
    db.add(MoneyLoan(fiscal_year=fy, contract_no="ย.3/" + str(fy), borrower="นายตัวอย่าง ยืมเงิน", amount=2000,
                     due_date=now - timedelta(days=10)))
    db.add(CheckPayment(fiscal_year=fy - 1, pay_method="เช็ค", check_no="0001234", payee="ร้านรุ่งเรืองพาณิชย์",
                        amount=700, date=now - timedelta(days=170)))
    db.add_all([Receipt(fiscal_year=fy, kind="รับ", receipt_no="12/" + str(fy), party="ผู้ปกครอง ก", amount=100, date=recent),
                Receipt(fiscal_year=fy, kind="รับ", receipt_no="12/" + str(fy), party="ผู้ปกครอง ข", amount=150, date=recent),
                Receipt(fiscal_year=fy, kind="รับ", receipt_no="10/" + str(fy), party="ผู้ปกครอง ค", amount=80, date=recent)])
    # ↑ 12 ซ้ำ + 11 ข้าม

    # ---- เงินในแผน: ไม่ตรงทะเบียน + ยังไม่ได้จัดสรร
    plan = PlanBudget(year=ay, mode="academic", start_date=datetime(ay - 543, 5, 16), end_date=datetime(ay - 542, 5, 15))
    db.add(plan); db.flush()
    db.add(PlanFunding(plan_id=plan.id, source_key=f"opening:showcase:{plan.id}", kind="opening",
                       name="เงินอุดหนุนทั่วไป / ค่าจัดการเรียนการสอน", amount=100000, account_item_id=teach.id))

    # ---- จ้างเหมาอาหารกลางวัน วงเงินเกินอัตรารายหัว (10 คน x 27 บาท x 20 วัน = 5,400)
    prog = LunchProgram(year=ay, rate_per_head=27, operate_mode="hire")
    db.add(prog); db.flush()
    db.add(LunchClass(program_id=prog.id, level="ป.1", num_students=10))
    db.add(LunchHireRound(program_id=prog.id, seq=1, start_date=datetime(ce, 11, 3), end_date=datetime(ce, 11, 28),
                          days=20, amount=10000))
    # ---- รายได้แผ่นดิน: ขายของเหลือใช้ได้เงินเกิน 10,000 บาท ยังไม่นำส่ง (ต้องส่งภายใน 3 วันทำการ)
    rev = FinanceAccount(name="เงินรายได้แผ่นดิน", fund_type="เงินรายได้แผ่นดิน")
    db.add(rev); db.flush()
    db.add(FinanceTxn(account_id=rev.id, fiscal_year=fy, kind="in", amount=12500, date=recent,
                      category="ค่าขายของเบ็ดเตล็ด", note="ขายพัสดุชำรุด"))
    db.commit()
    return dict(fy=fy, ay=ay, carry_year=fy - 2)
