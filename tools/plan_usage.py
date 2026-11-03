# -*- coding: utf-8 -*-
"""นับว่าโรงเรียนไหนใช้ "นำเงินเข้าแผน / จัดสรรเงินให้โครงการ" อยู่บ้าง (อ่านอย่างเดียว ไม่แก้ข้อมูล)

ใช้ตัดสินก่อนเลิกการจัดสรรล่วงหน้า: โรงเรียนที่ขึ้นในรายงานนี้คือโรงเรียนที่ต้องแจ้งก่อน deploy

รันบนเซิร์ฟเวอร์ด้วยผู้ใช้ ddoc เสมอ (root เปิดฐานโหมด WAL แล้วแอปจะเปิดฐานไม่ได้):
    cd /opt/ddoc && sudo -u ddoc .venv/bin/python -m tools.plan_usage
"""
from app.accounts import acc_session, Tenant
from app.tenancy import session_for


def money(v):
    return "{:,.2f}".format(float(v or 0))


def main():
    with acc_session() as adb:
        tenants = [(t.id, t.name) for t in adb.query(Tenant).filter(Tenant.plan != "sandbox").order_by(Tenant.id)]

    from app.models import PlanBudget, PlanFunding, ProjectFunding
    from app.services import plan_funding as pf
    used, period_only, errors = [], [], []
    for tid, name in tenants:
        try:
            db = session_for(tid)
        except Exception as e:                      # noqa: BLE001 โรงเรียนที่เปิดฐานไม่ได้ ข้ามไปแต่แจ้งไว้
            errors.append((tid, name, str(e)[:80]))
            continue
        try:
            plans = db.query(PlanBudget).all()
            if not plans:
                continue
            funds = db.query(PlanFunding).count()
            allocs = db.query(ProjectFunding).filter(ProjectFunding.amount > 0).all()
            # ช่วงปีที่ไม่ตรงค่าเริ่มต้น (เช่นปีการศึกษาเริ่ม 16 พ.ค.) ยังต้องเก็บไว้แม้เลิกจัดสรร
            custom = [p.year for p in plans if (p.start_date, p.end_date) != pf.defaults(p.year, p.mode)]
            row = dict(tid=tid, name=name, plans=[(p.year, p.mode) for p in plans], funds=funds,
                       projects=len({a.project_id for a in allocs}), amount=sum(a.amount or 0 for a in allocs),
                       custom=custom)
            (used if funds or allocs else period_only).append(row)
        except Exception as e:                      # noqa: BLE001
            errors.append((tid, name, str(e)[:80]))
        finally:
            db.close()

    print(f"โรงเรียนทั้งหมด (ไม่นับระบบตัวอย่าง) {len(tenants)} แห่ง")
    print(f"\n== ใช้นำเงินเข้าแผน/จัดสรร {len(used)} แห่ง ==")
    print("  id | เงินในแผน (รายการ) | โครงการที่จัดสรร | ยอดจัดสรรรวม | ช่วงปีกำหนดเอง | ชื่อ")
    for r in sorted(used, key=lambda r: -r["projects"]):
        print(f"  {r['tid']} | {r['funds']} | {r['projects']} | {money(r['amount'])} | {r['custom'] or '-'} | {r['name']}")
    print(f"\n== ตั้งช่วงปีแผนอย่างเดียว ไม่ได้จัดสรร {len(period_only)} แห่ง ==")
    for r in period_only:
        print(f"  {r['tid']} | แผน {r['plans']} | ช่วงปีกำหนดเอง {r['custom'] or '-'} | {r['name']}")
    if errors:
        print(f"\n== เปิดไม่ได้ {len(errors)} แห่ง ==")
        for tid, name, e in errors:
            print(f"  {tid} | {name} | {e}")


if __name__ == "__main__":
    main()
