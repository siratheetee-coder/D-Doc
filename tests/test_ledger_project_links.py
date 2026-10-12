# -*- coding: utf-8 -*-
"""หน้าทะเบียนคุมเงินต้องมีทางไปโครงการเสมอ

เดิมลิงก์ไปโครงการขึ้นเฉพาะหมวดที่จัดสรรแล้ว และซ่อนในส่วนที่ต้องกดเปิด
เจ้าของถามว่า "ไม่เห็นมีปุ่มลิงก์จากหน้าทะเบียนคุมไปที่โครงการเลย"
รัน: .venv\Scripts\python.exe -m pytest tests/test_ledger_project_links.py
"""
from tests.test_subsidy import env  # noqa: F401  (fixture)
from tests.test_plan_funding import import_all
from app.models import FinanceAccount, AccountItem, Project
from app.services import plan_funding as pf


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

    html = env.get(url).text                                   # 1. ยังไม่มีแผน
    assert 'ยังไม่ได้ตั้งแผนให้โครงการใช้เงินบัญชีนี้' in html and 'href="/plan-budget/' in html
    assert 'href="/projects">โครงการทั้งหมด' in html

    env.post('/plan-budget/2569/period', data=dict(mode='academic', start='18/05/2569', end='30/04/2570'))
    html = env.get(url).text                                   # 2. มีแผน แต่ยังไม่นำเงินบัญชีนี้เข้า
    assert 'แผนปีการศึกษา 2569' in html and 'เงินบัญชีนี้ยังไม่ได้นำเข้าแผน' in html
    assert 'href="/plan-budget/2569"' in html

    with tn.session_for(sid) as s:
        p = pf.plan(s, 2569); import_all(s, p, 'opening')
    html = env.get(url).text                                   # 3. นำเข้าแล้ว ยังไม่จัดสรร
    assert 'นำเข้าแผนแล้ว 50,000.00 ยังไม่ได้จัดสรรให้โครงการ' in html
    assert 'href="/projects?year=2569">ไปจัดสรรให้โครงการ' in html

    with tn.session_for(sid) as s:
        p = pf.plan(s, 2569)
        pj = Project(name='กีฬาสี', plan_year=2569, budget=30000); s.add(pj); s.commit()
        pf.allocate(s, p, pj, {str(pf.sources(s, p)[0].id): '30000'}, pf.allocation_token(s, p, pj)); s.commit()
        pid = pj.id
    html = env.get(url).text                                   # 4. จัดสรรแล้ว: ชื่อโครงการเห็นได้ทันที
    assert 'จัดสรรให้ 1 โครงการ 30,000.00 จาก 50,000.00' in html
    assert '<details class="al-detail" open>' in html and f'href="/projects/{pid}">กีฬาสี' in html
