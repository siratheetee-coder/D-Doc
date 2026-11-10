# -*- coding: utf-8 -*-
"""
finance_setup.py - รายการเริ่มต้นงานการเงินและโครงการ (หน้าหลักการเงิน)

งานเงินกับโครงการต้องทำตามลำดับ ข้ามขั้นแล้วหน้าถัดไปขึ้น 0 หรือว่างเปล่า
(เจ้าของเจอเอง: ทะเบียนคุมเงินขึ้น 0 ทุกหมวด เพราะยังไม่ได้กรอกยอดยกมา)
คู่มือแก้ไม่ได้เพราะคนไม่อ่านก่อนลงมือ จึงให้ระบบบอกเองว่าอยู่ขั้นไหน ขั้นต่อไปคืออะไร

กติกา
  - ติ๊กจากข้อมูลจริงเท่านั้น ไม่มีปุ่ม "ทำแล้ว" ติ๊กแล้วข้อมูลจึงครบจริงเสมอ
  - ขั้นถัดไปมีขั้นเดียว (ขั้นแรกที่ยังไม่เสร็จ) พร้อมปุ่มพาไปหน้านั้น
  - ครบทุกขั้นแล้วกล่องหายเอง
"""
from datetime import datetime

from app.models import AccountOpening, AccountItem, FinanceAccount, FinanceTxn, PlanBudget, Project


def _plans_for(db, fy):
    """แผนที่ช่วงวันที่ซ้อนกับปีงบนี้ (แผนปีการศึกษาคร่อมสองปีงบ ดูเลขปีอย่างเดียวไม่ได้)"""
    start, end = datetime(fy - 544, 10, 1), datetime(fy - 543, 9, 30)
    return (db.query(PlanBudget).filter(PlanBudget.start_date <= end, PlanBudget.end_date >= start)
            .order_by(PlanBudget.start_date).all())


def setup_steps(db, fy, school=None, *, selected_plan_year=None) -> dict:
    """คืน {steps: [...], done: n, total: n, complete: bool, next: step}

    step = {n, title, done, detail, href, cta, extra: [(ข้อความ, ลิงก์)]}
    """
    from app.services.budget import current_plan_year
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    items = db.query(AccountItem).filter_by(fiscal_year=fy).all()
    item_acc = sorted({i.account_id for i in items})
    first_acc = item_acc[0] if item_acc else (accounts[0].id if accounts else None)
    # ข้อ 3 เสร็จเมื่อทุกบัญชีที่มีหมวด แบ่งยอดยกมาเข้าหมวดครบเท่ายอดของบัญชี
    # (ครูเจอกล่องเตือน "ยอดยกมาทุกหมวดยังเป็น 0" ทั้งที่กรอกยอดบัญชีแล้ว ไม่รู้ว่าติดตรงไหน)
    from app.services.asset_utils import opening_for
    acc_by_id = {a.id: a for a in accounts}
    short = []   # (บัญชี, ยอดยกมา, แบ่งแล้ว)
    for aid in item_acc:
        a = acc_by_id.get(aid)
        if not a:
            continue
        total = round(opening_for(a, fy), 2)
        split = round(sum((i.opening_balance or 0) for i in items if i.account_id == aid), 2)
        if abs(total - split) >= 0.01:
            short.append((a, total, split))
    split_done = not short and bool(accounts)
    if short:
        a0 = short[0][0]
        split_href = f"/finance/accounts/{a0.id}?year={fy}"
        split_detail = "\n".join(
            f"บัญชี{a.name} ยกมา {t:,.2f} แบ่งเข้าหมวดแล้ว {sp:,.2f} ยังไม่แบ่ง {t - sp:,.2f}"
            for a, t, sp in short[:3])
        if len(short) > 3:
            split_detail += f"\nและอีก {len(short) - 3} บัญชี"
    elif items:
        split_href, split_detail = f"/finance/accounts/{first_acc}?year={fy}", "แบ่งยอดยกมาเข้าหมวดครบทุกบัญชีแล้ว"
    else:
        split_href, split_detail = "/finance/accounts", ("ไม่ได้แยกหมวด ไม่ต้องทำข้อนี้" if accounts else "สร้างบัญชีก่อน")
    plans = (_plans_for(db, fy) if selected_plan_year is None else
             db.query(PlanBudget).filter_by(year=selected_plan_year).all())
    plan_year = selected_plan_year if selected_plan_year is not None else (plans[0].year if plans else current_plan_year(school))
    n_projects = db.query(Project).filter(Project.plan_year == plan_year).count()

    acc_href = f"/finance/accounts/{first_acc}?year={fy}" if first_acc else "/finance/accounts"
    steps = [
        dict(title="สร้างบัญชีเงิน", done=bool(accounts),
             detail=(f"มี {len(accounts)} บัญชี" if accounts
                     else "เช่น เงินอุดหนุนทั่วไป เงินรายได้สถานศึกษา แยกตามบัญชีที่โรงเรียนมีจริง"),
             href="/finance/accounts", cta="สร้างบัญชี"),
        dict(title="แยกหมวดในบัญชี (ข้ามได้)", done=bool(items),
             detail=(f"มี {len(items)} หมวดในปีงบ {fy}" if items
                     else "ถ้าตั้งบัญชีแยกประเภทเงินแล้ว ไม่ต้องแยกหมวดก็ได้ กดข้ามได้ "
                          "ถ้าเงินหลายประเภทอยู่บัญชีเดียว ค่อยแยกหมวด มีปุ่มเพิ่มหมวดมาตรฐานให้ในหน้าบัญชี"),
             href=acc_href, cta="เพิ่มหมวด"),
        dict(title="แบ่งยอดยกมาเข้าหมวด", done=split_done,
             detail=split_detail, href=split_href, cta="แบ่งยอดยกมา"),
        dict(title="เพิ่มโครงการพร้อมงบ", done=bool(n_projects),
             detail=(f"แผน {plan_year} มี {n_projects} โครงการ" if n_projects
                     else f"ยังไม่มีโครงการในแผน {plan_year} เพิ่มโครงการพร้อมงบ หรือนำเข้าจาก Excel"),
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
        dict(title="ใส่งบให้โครงการ (ข้ามได้ถ้าไม่ใช้งบ)", done=bool(rows) and not zero,
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


def project_detail_steps(project, procs, memos, reports) -> dict:
    """ขั้นตอนของโครงการเดียว (หน้าโครงการ) แบบเดียวกับกล่องเริ่มต้นของงานอื่น: ติ๊กเองจากข้อมูลจริง

    เดิมหน้าโครงการมีแค่คำอธิบาย "ใส่งบ กับ ปรับงบ" ไม่บอกว่าต้องทำอะไรต่อ (เจ้าของขอให้เหมือนงานอื่น)
    """
    from app.services.budget import project_budget, project_money_summary
    pid, money = project.id, project_money_summary(project)
    year = project.plan_year or ""
    steps = [
        dict(title="ใส่งบโครงการ", done=project_budget(project) > 0,
             detail="ใส่งบตามแผนปฏิบัติการ ใช้คำนวณงบเหลือทำเรื่องใหม่", href="#setBudget", cta="ใส่งบ"),
        dict(title="ใช้เงินไปก่อนเริ่มใช้ระบบ (ข้ามได้)", done=float(project.spent_before or 0) > 0,
             detail="ถ้าโรงเรียนใช้เงินโครงการนี้ไปบ้างแล้วก่อนมาใช้ระบบ กรอกว่าตอนนี้เหลือเท่าไร ถ้าไม่มีกดข้าม",
             href=f"/projects/start?year={year}", cta="ตั้งยอดตั้งต้น"),
        dict(title="ทำเรื่องใช้เงิน", done=bool(procs or memos),
             detail="ซื้อของหรือจ้าง ทำเรื่องจัดซื้อ/จัดจ้าง ค่าใช้จ่ายอื่นทำบันทึกขอเบิกจ่ายได้เลย",
             href=f"/procurement/new?project={pid}", cta="ทำเรื่องจัดซื้อ/จัดจ้าง",
             extra=[("บันทึกขอเบิกค่าอื่น", f"/finance/disburse?project={pid}")]),
        dict(title="ลงจ่ายเงิน", done=money["paid"] > 0,
             detail="ผอ. อนุมัติบันทึกขอเบิกแล้ว กดลงจ่าย ระบบตัดเงินในทะเบียนคุมเงินและนับเป็นจ่ายจริงของโครงการ",
             href="#activities", cta="ดูเรื่องที่รอจ่าย"),
        dict(title="รายงานผลโครงการ (ข้ามได้)", done=bool(reports),
             detail="ทำโครงการเสร็จแล้ว เขียนรายงานผลแล้วพิมพ์ Word", href="#project-report", cta="ไปเขียนรายงานผล"),
    ]
    for n, st in enumerate(steps, 1):
        st["n"] = n
        st.setdefault("extra", [])
    nxt = next((st for st in steps if not st["done"]), None)
    done = sum(1 for st in steps if st["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)
