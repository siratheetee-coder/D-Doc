# -*- coding: utf-8 -*-
"""รายงานการจัดสรรเงินโครงการของโรงเรียนหนึ่ง (อ่านอย่างเดียว ไม่แก้ข้อมูล)

รันบนเซิร์ฟเวอร์ด้วยผู้ใช้ ddoc เสมอ (root เปิดฐานโหมด WAL แล้วแอปจะเปิดฐานไม่ได้):
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.plan_report "บ้านหินลาด"
"""
import sys

from sqlalchemy import func

from app.accounts import acc_session, Tenant
from app.tenancy import session_for


def money(v):
    return "{:,.2f}".format(float(v or 0))


def main(name):
    with acc_session() as adb:
        ts = adb.query(Tenant).filter(Tenant.name.like(f"%{name}%"), Tenant.plan != "sandbox").all()
        found = [(t.id, t.name, t.plan) for t in ts]
    if len(found) != 1:
        print("พบโรงเรียน", len(found), "แห่ง:", found)
        return
    tid, tname, plan = found[0]
    print(f"โรงเรียน: {tname} (id {tid}, แผน {plan})")

    from app.models import School, Project, ProjectFunding, PlanBudget, AccountItem
    from app.services import plan_funding as pf
    from app.services.budget import current_plan_year, project_budget, project_spent_in_system
    from app.services.asset_utils import item_remaining_asof
    db = session_for(tid)
    try:
        school = db.query(School).first()
        cur = current_plan_year(school)
        print("ปีแผนปัจจุบัน:", cur, "| แผนที่มี:",
              [(p.year, p.mode, str(p.start_date.date())) for p in db.query(PlanBudget).order_by(PlanBudget.year)])
        for year in sorted({cur} | {p.year for p in db.query(PlanBudget)}):
            p = pf.plan(db, year)
            print(f"\n===== ปีแผน {year} =====")
            if p:
                s = pf.summary(db, p)
                print(f"เงินในแผน {money(s['total'])} จัดสรรแล้ว {money(s['allocated'])} ยังไม่จัดสรร {money(s['remaining'])}")
                for r in s["rows"]:
                    src = r["source"]
                    item = db.get(AccountItem, src.account_item_id) if src.account_item_id else None
                    real = item_remaining_asof(item) if item else None
                    print(f"  [{src.id}] {src.name} ({src.kind}) แผน {money(src.amount)} จัดสรร {money(r['allocated'])}"
                          f" เงินจริงในหมวดตอนนี้ {money(real) if real is not None else '-'}"
                          f"{' ยอดต้นทางเปลี่ยน' if r['changed'] else ''}")
            else:
                print("ยังไม่ได้นำเงินเข้าแผน")
            pjs = db.query(Project).filter(Project.plan_year == year, Project.active == True).order_by(Project.name).all()  # noqa: E712
            print(f"โครงการ {len(pjs)} โครงการ")
            print("  งบ | ใช้ไปก่อนเริ่มระบบ | จ่ายในระบบ | จัดสรรแล้ว | ชื่อ")
            for pj in pjs:
                funds = db.query(ProjectFunding).filter_by(project_id=pj.id).all()
                alloc = sum(a.amount or 0 for a in funds)
                print(f"  {money(project_budget(pj))} | {money(pj.spent_before)} | {money(project_spent_in_system(pj))}"
                      f" | {money(alloc)}{'' if len(funds) < 2 else ' (หลายรายการ)'} | {pj.name}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('ใช้: python -m tools.plan_report "ชื่อโรงเรียน"')
    main(sys.argv[1])
