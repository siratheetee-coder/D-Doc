"""เงินยืมผูกโครงการ/กิจกรรม: ยืมแล้วกันงบเต็มยอด ส่งใช้แล้วนับเฉพาะใบสำคัญ เงินสดที่คืนกลับเป็นงบเหลือ"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_loan_counts_receipts_and_open_amount(env):
    from app.models import Project, ProjectActivity, MoneyLoan, LoanReturn, FinanceTxn, FinanceAccount
    from app.services.budget import project_money_summary
    with _db() as s:
        pj = Project(name="อบรมครู", plan_year=2569, budget=10000); s.add(pj); s.flush()
        act = ProjectActivity(project_id=pj.id, name="ไปอบรม", budget=6000); s.add(act); s.commit()
        pid, aid = pj.id, act.id

    # ทำสัญญาจากปุ่มในกิจกรรม: ฟอร์มเลือกโครงการ/กิจกรรมไว้ให้
    form = env.get(f"/finance/loans?project={pid}&activity={aid}").text
    assert f'<option value="{pid}" selected>' in form and f'data-selected="{aid}"' in form
    env.post("/finance/loans", data={"fiscal_year": "2570", "borrower": "ครูเอ", "amount": "5000",
                                     "purpose": "ไปอบรมที่ขอนแก่น", "date": "02/11/2569", "receive_date": "02/11/2569",
                                     "within_days": "15", "project_id": str(pid), "activity_id": str(aid)})
    with _db() as s:
        ln = s.query(MoneyLoan).one()
        assert (ln.project_id, ln.activity_id) == (pid, aid)
        lid = ln.id
        # ยังไม่ส่งใช้: กันงบเต็ม 5,000 เป็นรอจ่าย
        m = project_money_summary(s.get(Project, pid))
        assert (m["paid"], m["waiting"]) == (0, 5000)
        # รายการจ่ายเงินยืมในทะเบียนคุมเงิน (เลือกโครงการไว้ด้วย) ต้องไม่นับซ้ำ
        acc = FinanceAccount(name="เงินรายได้"); s.add(acc); s.flush()
        s.add(FinanceTxn(account_id=acc.id, fiscal_year=2570, kind="out", amount=5000, loan_id=lid, project_id=pid,
                         date=datetime(2026, 11, 2)))
        s.commit()
        assert project_money_summary(s.get(Project, pid))["used"] == 5000

        # ส่งใช้: ใบสำคัญ 4,200 + เงินสดคืน 800 -> ใช้จริง 4,200 งบเหลือเพิ่ม
        s.add_all([LoanReturn(loan_id=lid, kind="ใบสำคัญ", amount=4200, date=datetime(2026, 11, 10)),
                   LoanReturn(loan_id=lid, kind="เงินสด", amount=800, date=datetime(2026, 11, 10))])
        s.commit()
        m = project_money_summary(s.get(Project, pid))
        assert (m["paid"], m["waiting"], m["used"]) == (4200, 0, 4200)

    page = env.get(f"/projects/{pid}").text
    blk = page.split(f'data-act="{aid}"')[1]
    assert "เงินยืม" in blk and "ไปอบรมที่ขอนแก่น" in blk and "4,200.00" in blk and "คืนเงินสด 800.00" in blk
    assert f'href="/finance/loans?project={pid}&activity={aid}#new"' in page

    # ย้ายออกจากกิจกรรม แล้วเปลี่ยนโครงการจากหน้าเงินยืม
    env.post(f"/projects/{pid}/assign", data={"kind": "loan", "doc_id": str(lid), "activity_id": ""})
    with _db() as s:
        assert s.get(MoneyLoan, lid).activity_id is None
    env.post(f"/finance/loans/{lid}/project", data={"project_id": "", "activity_id": str(aid)})
    with _db() as s:
        ln = s.get(MoneyLoan, lid)
        assert ln.project_id is None and ln.activity_id is None
        assert project_money_summary(s.get(Project, pid))["used"] == 0
