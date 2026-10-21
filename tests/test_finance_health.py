# -*- coding: utf-8 -*-
"""ตรวจสุขภาพข้อมูลการเงิน: จำลองปัญหาที่เจอจริง (บ้านหินลาด 2569-10) แล้วดูว่าหน้าตรวจจับได้ครบ พร้อมลิงก์ถูกหน้า
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_finance_health.py
"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _seed():
    """เริ่มใช้ระบบที่ปีงบปัจจุบันด้วยยอดยกมา แต่ข้อมูลมีปัญหาแบบที่เจอจริงทุกข้อ"""
    from app.models import (School, FinanceAccount, AccountItem, AccountOpening, FinanceTxn, Project,
                            Procurement, DisburseMemo)
    from app.thai_utils import current_fiscal_year, current_academic_year
    fy, ay = current_fiscal_year(), current_academic_year()
    ce = fy - 544                                     # ปีงบ fy เริ่ม 1 ต.ค. ค.ศ. ce
    db = _db()
    try:
        db.query(School).first().project_year_mode = "academic"
        sub = FinanceAccount(name="เงินอุดหนุนทั่วไป")
        lunch = FinanceAccount(name="อาหารกลางวัน")
        db.add_all([sub, lunch]); db.flush()
        teach = AccountItem(account_id=sub.id, fiscal_year=fy, name="ค่าจัดการเรียนการสอน", budget=263360, opening_balance=263360)
        book = AccountItem(account_id=sub.id, fiscal_year=fy, name="ค่าหนังสือเรียน", budget=80512.2, opening_balance=80512.2)
        db.add_all([teach, book, AccountOpening(account_id=sub.id, fiscal_year=fy, amount=343872.2)]); db.flush()
        meal = AccountItem(account_id=lunch.id, fiscal_year=fy, name="ค่าอาหาร", budget=0, opening_balance=100)
        db.add_all([meal, AccountOpening(account_id=lunch.id, fiscal_year=fy, amount=100)]); db.flush()
        db.add_all([
            # จ่ายไปก่อนเริ่มใช้ระบบ แต่ลงในปีงบก่อน (ทำให้เตือนยกยอดติดลบ)
            FinanceTxn(account_id=lunch.id, fiscal_year=fy - 1, kind="out", amount=127200, date=datetime(ce, 9, 10),
                       note="จ้างเหมาอาหารกลางวัน รอบ 2"),
            # ลงปีงบนี้ แต่วันที่อยู่ปีงบก่อน
            FinanceTxn(account_id=sub.id, item_id=teach.id, fiscal_year=fy, kind="out", amount=500, date=datetime(ce, 9, 20),
                       note="ค่าวัสดุ"),
            # หมวดติดลบ
            FinanceTxn(account_id=lunch.id, item_id=meal.id, fiscal_year=fy, kind="out", amount=900, date=datetime(ce, 10, 5),
                       note="ค่าอาหารเสริม"),
        ])
        pj = Project(name="โครงการอาหารกลางวัน", budget=0, plan_year=ay)
        ok = Project(name="โครงการวันสำคัญ", budget=15000, plan_year=ay)
        db.add_all([pj, ok]); db.flush()
        db.add_all([
            Procurement(fiscal_year=fy - 1, memo_no="10/x", subject="จ้างเหมาอาหาร", proc_type="จ้าง", total_amount=132000,
                        order_date=datetime(ay - 543, 5, 18), project_id=pj.id),
            Procurement(fiscal_year=fy - 1, memo_no="3/x", subject="วัสดุวันสำคัญ", proc_type="ซื้อ", total_amount=4990,
                        order_date=datetime(ay - 544, 11, 12), project_id=ok.id),
        ])
        over = Procurement(fiscal_year=fy, memo_no="20/x", subject="วัสดุสำนักงาน", proc_type="ซื้อ", total_amount=1000,
                           order_date=datetime(ce, 10, 8))
        db.add(over); db.flush()
        db.add_all([DisburseMemo(fiscal_year=fy, memo_no="1/x", subject="วัสดุสำนักงาน", amount=800, procurement_id=over.id),
                    DisburseMemo(fiscal_year=fy, memo_no="2/x", subject="วัสดุสำนักงาน", amount=800, procurement_id=over.id)])
        db.commit()
        return fy, ay, sub.id, lunch.id
    finally:
        db.close()


def test_detects_real_problems_with_fix_links(env):
    fy, ay, sub_id, lunch_id = _seed()
    from app.services.finance_health import run
    db = _db()
    try:
        h = run(db, fy)
    finally:
        db.close()
    fix = {i["key"]: i for i in h["fix"]}
    assert set(fix) == {"opening_equals_budget", "before_start", "txn_wrong_year", "negative_balance",
                        "project_no_budget", "project_wrong_year", "memo_over_procurement"}, fix.keys()
    assert "carry_mismatch" not in fix, "เริ่มใช้กลางทาง: ห้ามแนะนำให้กดยกยอด"
    assert fix["opening_equals_budget"]["href"] == f"/finance/accounts/{sub_id}?year={fy}#opening-form"
    pre = fix["before_start"]["rows"]
    assert len(pre) == 1 and pre[0]["amount"] == 127200 and pre[0]["href"].startswith(f"/finance/accounts/{lunch_id}?year={fy - 1}#t")
    assert fix["project_wrong_year"]["href"] == f"/projects/realign?year={ay}"
    assert fix["project_no_budget"]["rows"][0]["text"] == "โครงการอาหารกลางวัน"
    assert fix["memo_over_procurement"]["rows"][0]["amount"] == 600
    assert fix["negative_balance"]["rows"][0]["amount"] == -800
    assert "ยอดยกมาตรงกับยอดคงเหลือสิ้นปีก่อน" in h["passed"]
    from app.services.finance_health import CHECKS
    assert sum(len(h[k]) for k in ("fix", "check", "notice")) + len(h["passed"]) == len(CHECKS), \
        "ทุกข้อตรวจรันจบ (ข้อที่พังจะหายไปทั้งจากปัญหาและจากผ่านแล้ว)"

    html = env.get(f"/finance/health?year={fy}").text
    for word in ("สิ่งที่ควรแก้", "สิ่งที่ควรเช็ค", "สิ่งที่ควรสังเกต", "ไปแก้ยอดยกมา", "ไปตรวจและย้าย", "ไปใส่งบ", "ผ่านแล้ว"):
        assert word in html, word
    assert f'href="/finance/accounts/{sub_id}?year={fy}#opening-form"' in html
    dash = env.get(f"/finance?year={fy}").text
    assert f'href="/finance/health?year={fy}"' in dash and "ควรแก้ 7" in dash
    assert "ยกยอดจากปีงบ" not in dash, "เริ่มใช้กลางทาง: กล่องสีส้มชวนยกยอดติดลบต้องไม่ขึ้น"
    from app.services.finance_openings import carry_status
    db = _db()
    try:
        assert carry_status(db, fy) == []
    finally:
        db.close()
    ledger = env.get(f"/finance/accounts/{lunch_id}?year={fy - 1}").text
    assert f'id="{pre[0]["href"].split("#")[1]}"' in ledger, "ลิงก์ไปถึงแถวรายการนั้นในทะเบียน"


def test_clean_data_all_ok(env):
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    html = env.get(f"/finance/health?year={fy}").text
    assert "ข้อมูลการเงินปีงบ" in html and "เรียบร้อยดี" in html
    assert "ข้อมูลเรียบร้อย" in env.get(f"/finance?year={fy}").text


def test_one_broken_check_does_not_break_page(env, monkeypatch):
    import app.services.finance_health as fh

    def boom(db, fy, today):
        raise RuntimeError("x")
    monkeypatch.setattr(fh, "CHECKS", [("fix", "ข้อพัง", boom)] + fh.CHECKS[1:])
    from app.thai_utils import current_fiscal_year
    r = env.get(f"/finance/health?year={current_fiscal_year()}")
    assert r.status_code == 200 and "ข้อพัง" not in r.text


def test_check_and_notice_levels(env):
    from datetime import timedelta
    from app.models import (FinanceAccount, AccountItem, FinanceTxn, Project, Procurement, DisburseMemo, Vendor,
                            MoneyLoan, CheckPayment)
    from app.thai_utils import current_fiscal_year, current_academic_year
    from app.services.finance_health import run
    fy, ay = current_fiscal_year(), current_academic_year()
    now = datetime.now()
    db = _db()
    try:
        from app.models import School
        db.query(School).first().project_year_mode = "academic"
        a = FinanceAccount(name="เงินรายได้สถานศึกษา", deposit_type="bank"); db.add(a); db.flush()
        db.add(AccountItem(account_id=a.id, fiscal_year=fy, name="ทั่วไป", budget=0, opening_balance=50000))
        v = Vendor(name="ร้านไม่มีเลขภาษี"); db.add(v)
        pj = Project(name="โครงการเกินงบ", budget=1000, plan_year=ay); db.add(pj); db.flush()
        db.add(Procurement(fiscal_year=fy, subject="ของแพง", total_amount=1500, project_id=pj.id, vendor_id=v.id,
                           order_date=datetime(ay - 543, 6, 1)))
        old = now - timedelta(days=60)
        db.add(DisburseMemo(fiscal_year=fy, memo_no="5/x", subject="ค้างจ่าย", amount=300, status="อนุมัติ", date=old,
                            payee="ร้านไม่มีเลขภาษี", wht=3))
        d = now - timedelta(days=2)
        db.add_all([FinanceTxn(account_id=a.id, fiscal_year=fy, kind="out", amount=250, date=d, note="ซื้อน้ำ"),
                    FinanceTxn(account_id=a.id, fiscal_year=fy, kind="out", amount=250, date=d, note="ซื้อน้ำ")])
        db.add(MoneyLoan(fiscal_year=fy, borrower="นายยืม ไม่คืน", amount=2000, due_date=now - timedelta(days=10)))
        db.add(CheckPayment(fiscal_year=fy - 1, pay_method="เช็ค", check_no="0001", payee="ร้าน ก", amount=700,
                            date=now - timedelta(days=170)))
        db.commit()
        h = run(db, fy, now)
    finally:
        db.close()
    chk = {i["key"] for i in h["check"]}
    assert {"project_over_budget", "memo_unpaid_long", "loans_overdue", "duplicate_payments",
            "wht_vendor_no_tax_id", "checks_not_cleared"} <= chk, chk
    note = {i["key"] for i in h["notice"]}
    assert "txn_without_item" in note, note
    if now.month != 10:      # เดือนแรกของปีงบ เดือนที่แล้วเป็นปีงบก่อน ไม่ตรวจ
        assert "bank_recon_missing" in note
