# -*- coding: utf-8 -*-
"""หน้าทะเบียนคุมเงินต้องมีทางไปโครงการเสมอ

เดิมลิงก์ไปโครงการขึ้นเฉพาะหมวดที่จัดสรรแล้ว และซ่อนในส่วนที่ต้องกดเปิด
เจ้าของถามว่า "ไม่เห็นมีปุ่มลิงก์จากหน้าทะเบียนคุมไปที่โครงการเลย"
รัน: .venv\Scripts\python.exe -m pytest tests/test_ledger_project_links.py
"""
from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import FinanceAccount, AccountItem


def _setup(sid):
    import app.tenancy as tn
    with tn.session_for(sid) as s:
        a = FinanceAccount(name='เงินอุดหนุน'); s.add(a); s.flush()
        s.add(AccountItem(account_id=a.id, fiscal_year=2570, name='กิจกรรม', opening_balance=50000))
        s.commit()
        return a.id


def test_ledger_always_leads_to_projects(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    aid = _setup(sid)
    url = f'/finance/accounts/{aid}?year=2570'

    html = env.get(url).text
    assert 'href="/projects">โครงการทั้งหมด' in html
    # เลิกจัดสรรเงินให้โครงการล่วงหน้าแล้ว ทะเบียนคุมเงินแสดงแค่เงินจริง
    assert 'plan-budget' not in html and 'ยังไม่จัดสรร' not in html
