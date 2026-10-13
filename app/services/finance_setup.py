# -*- coding: utf-8 -*-
"""
finance_setup.py - รายการเริ่มต้นงานการเงินและโครงการ (หน้าหลักการเงิน)

งานเงินกับโครงการต้องทำตามลำดับ ข้ามขั้นแล้วหน้าถัดไปขึ้น 0 หรือว่างเปล่า
(เจ้าของเจอเอง: ดึงเงินเข้าแผนได้ 0 เพราะยอดยกมายังเป็น 0 ทุกหมวด)
คู่มือแก้ไม่ได้เพราะคนไม่อ่านก่อนลงมือ จึงให้ระบบบอกเองว่าอยู่ขั้นไหน ขั้นต่อไปคืออะไร

กติกา
  - ติ๊กจากข้อมูลจริงเท่านั้น ไม่มีปุ่ม "ทำแล้ว" ติ๊กแล้วข้อมูลจึงครบจริงเสมอ
  - ขั้นถัดไปมีขั้นเดียว (ขั้นแรกที่ยังไม่เสร็จ) พร้อมปุ่มพาไปหน้านั้น
  - ครบทุกขั้นแล้วกล่องหายเอง
"""
from datetime import datetime

from app.models import AccountItem, FinanceAccount, FinanceTxn, PlanBudget, Project

try:
    from app.models import PlanFunding, ProjectFunding
except ImportError:                                   # pragma: no cover
    PlanFunding = ProjectFunding = None


def _plans_for(db, fy):
    """แผนที่ช่วงวันที่ซ้อนกับปีงบนี้ (แผนปีการศึกษาคร่อมสองปีงบ ดูเลขปีอย่างเดียวไม่ได้)"""
    start, end = datetime(fy - 544, 10, 1), datetime(fy - 543, 9, 30)
    return (db.query(PlanBudget).filter(PlanBudget.start_date <= end, PlanBudget.end_date >= start)
            .order_by(PlanBudget.start_date).all())


def setup_steps(db, fy, school=None) -> dict:
    """คืน {steps: [...], done: n, total: n, complete: bool, next: step}

    step = {n, title, done, detail, href, cta, extra: [(ข้อความ, ลิงก์)]}
    """
    from app.services.budget import current_plan_year
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    items = db.query(AccountItem).filter_by(fiscal_year=fy).all()
    item_acc = sorted({i.account_id for i in items})
    first_acc = item_acc[0] if item_acc else (accounts[0].id if accounts else None)
    has_money = (any((i.opening_balance or 0) > 0 for i in items)
                 or db.query(FinanceTxn.id).filter(FinanceTxn.fiscal_year == fy,
                                                   FinanceTxn.item_id.isnot(None)).first() is not None)
    plans = _plans_for(db, fy)
    plan_year = plans[0].year if plans else current_plan_year(school)
    funds = []
    if PlanFunding is not None and plans:
        funds = db.query(PlanFunding).filter(PlanFunding.plan_id.in_([p.id for p in plans])).all()
    allocs = []
    if funds:
        allocs = db.query(ProjectFunding).filter(ProjectFunding.funding_id.in_([f.id for f in funds]),
                                                 ProjectFunding.amount > 0).all()
    n_projects = db.query(Project).filter(Project.plan_year == plan_year).count()
    in_plan = round(sum(f.amount or 0 for f in funds), 2)

    acc_href = f"/finance/accounts/{first_acc}?year={fy}" if first_acc else "/finance/accounts"
    steps = [
        dict(title="สร้างบัญชีเงิน", done=bool(accounts),
             detail=(f"มี {len(accounts)} บัญชี" if accounts
                     else "เช่น เงินอุดหนุนทั่วไป เงินรายได้สถานศึกษา แยกตามบัญชีที่โรงเรียนมีจริง"),
             href="/finance/accounts", cta="สร้างบัญชี"),
        dict(title="แยกหมวดในบัญชี", done=bool(items),
             detail=(f"มี {len(items)} หมวดในปีงบ {fy}" if items
                     else "เช่น เงินอุดหนุนแยกเป็น ค่าจัดการเรียนการสอน ค่ากิจกรรมพัฒนาผู้เรียน "
                          "มีปุ่มเพิ่มหมวดมาตรฐานให้ในหน้าบัญชี"),
             href=acc_href, cta="เพิ่มหมวด"),
        dict(title="กรอกยอดยกมาแยกหมวด", done=has_money,
             detail=("ระบบรู้แล้วว่าแต่ละหมวดมีเงินเท่าไร" if has_money
                     else f"ตอนนี้ยอดยกมาทุกหมวดของปีงบ {fy} ยังเป็น 0 กรอกเงินที่เหลือของแต่ละหมวด "
                          "เช่น ค่ากิจกรรม 50,000 ค่าจัดการเรียนการสอน 80,000"),
             href=acc_href, cta="กรอกยอดยกมา"),
        dict(title="นำเงินเข้าแผน", done=bool(funds),
             detail=(f"นำเข้าแผน {plan_year} แล้ว {in_plan:,.2f} บาท" if funds
                     else "เลือกว่าเงินหมวดไหนจะใช้ทำโครงการในแผนปีนี้ ระบบดึงยอดจากทะเบียนคุมเงินให้เอง"),
             href=f"/plan-budget/{plan_year}", cta="นำเงินเข้าแผน"),
        dict(title="เพิ่มโครงการและจัดสรรเงิน", done=bool(allocs),
             detail=(f"จัดสรรให้ {len({a.project_id for a in allocs})} โครงการแล้ว" if allocs
                     else ("เปิดแต่ละโครงการแล้วเลือกว่าใช้เงินจากหมวดไหน กี่บาท" if n_projects
                           else f"ยังไม่มีโครงการในแผน {plan_year} เพิ่มโครงการพร้อมงบ แล้วจัดสรรเงินให้")),
             href=f"/projects?year={plan_year}", cta="ไปที่โครงการ",
             extra=[("เพิ่งเริ่มใช้ระบบกลางปี? ตั้งยอดตั้งต้นโครงการ", f"/projects/start?year={plan_year}")]),
    ]
    for n, s in enumerate(steps, 1):
        s["n"] = n
        s.setdefault("extra", [])
    nxt = next((s for s in steps if not s["done"]), None)
    done = sum(1 for s in steps if s["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)


def project_steps(db, plan_year, year_label="ปีงบประมาณ") -> dict:
    """ชุดสั้นสำหรับหน้าโครงการ เมื่อผู้ใช้ไม่มีสิทธิ์งานการเงิน

    หน้าโครงการใช้ได้ฟรี แต่ทะเบียนคุมเงินกับหน้างบที่ใช้จัดทำแผนเป็นของงานการเงิน
    ชุด 5 ขั้นเต็มจะพาไปหน้าที่เข้าไม่ได้ จึงเหลือแค่เรื่องโครงการล้วน ๆ
    """
    from app.services.budget import project_budget
    rows = db.query(Project).filter(Project.plan_year == plan_year).order_by(Project.name).all()
    zero = [p for p in rows if project_budget(p) <= 0]
    no_owner = [p for p in rows if not (p.responsible or "").strip()]

    def names(ps):
        head = ", ".join(p.name for p in ps[:3])
        return head + (f" และอีก {len(ps) - 3} โครงการ" if len(ps) > 3 else "")

    steps = [
        dict(title="เพิ่มโครงการ", done=bool(rows),
             detail=(f"{year_label} {plan_year} มี {len(rows)} โครงการ" if rows
                     else "พิมพ์ทีละโครงการพร้อมงบ หรือนำเข้าจาก Excel ทีเดียวทั้งแผน"),
             href="#add-project", cta="เพิ่มโครงการ",
             extra=[("นำเข้าจาก Excel", "/projects/import")]),
        dict(title="ใส่งบให้ทุกโครงการ", done=bool(rows) and not zero,
             detail=("ทุกโครงการมีงบแล้ว" if rows and not zero
                     else (f"ยังมี {len(zero)} โครงการที่งบเป็น 0: {names(zero)} · เปิดโครงการแล้วใส่งบในช่องด้านบนได้เลย "
                           "ไม่นับเป็นการปรับงบ" if zero else "เพิ่มโครงการก่อน")),
             href=(f"/projects/{zero[0].id}" if zero else "#add-project"), cta="ใส่งบโครงการ",
             extra=[("ใส่งบ กับ ปรับงบ ต่างกันยังไง", "#budget-help")]),
        dict(title="ระบุฝ่ายที่รับผิดชอบ", done=bool(rows) and not no_owner,
             detail=("ทุกโครงการระบุฝ่ายแล้ว" if rows and not no_owner
                     else (f"ยังไม่ระบุ {len(no_owner)} โครงการ: {names(no_owner)} · เลือกฝ่ายในตารางด้านล่างได้เลย "
                           "ใช้ในรายงานผลโครงการ" if no_owner else "เพิ่มโครงการก่อน")),
             href="#project-list", cta="ไปที่ตารางโครงการ"),
    ]
    for n, s in enumerate(steps, 1):
        s["n"] = n
        s.setdefault("extra", [])
    nxt = next((s for s in steps if not s["done"]), None)
    done = sum(1 for s in steps if s["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)
