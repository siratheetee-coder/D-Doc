# -*- coding: utf-8 -*-
"""รายการเริ่มต้นงานการเงินและโครงการ บนหน้าหลักการเงิน

ระบบติ๊กเองจากข้อมูลจริง แสดงขั้นถัดไปขั้นเดียวพร้อมปุ่ม ครบแล้วกล่องหาย
(เจ้าของเจอเอง: ข้ามขั้นกรอกยอดยกมาแยกหมวด แล้วดึงเงินเข้าแผนได้ 0 โดยไม่รู้ว่าทำไม)
รัน: .venv\Scripts\python.exe -m pytest tests/test_finance_setup.py
"""
import pathlib
import re

from tests.test_subsidy import db, env  # noqa: F401  (fixtures)
from tests.test_plan_funding import import_all
from app.models import FinanceAccount, AccountItem, Project
from app.services import plan_funding as pf

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2570


def _next_step(html):
    m = re.search(r'class="fs-step is-next">.*?class="fs-name">(\d)\. ([^<]+)<', html, re.S)
    return (int(m.group(1)), m.group(2).strip()) if m else None


def test_checklist_walks_through_the_steps_in_order(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    page = lambda: env.get(f'/finance?year={FY}').text          # noqa: E731

    html = page()
    assert 'เริ่มต้นงานการเงินและโครงการ' in html and 'ทำแล้ว 0 จาก 5 ขั้น' in html
    assert _next_step(html) == (1, 'สร้างบัญชีเงิน')
    assert html.count('class="fs-step is-next"') == 1, "ขั้นถัดไปต้องมีขั้นเดียว"

    with tn.session_for(sid) as s:
        a = FinanceAccount(name='เงินอุดหนุน'); s.add(a); s.commit(); aid = a.id
    html = page()
    assert _next_step(html) == (2, 'แยกหมวดในบัญชี') and f'href="/finance/accounts/{aid}?year={FY}"' in html

    with tn.session_for(sid) as s:
        it = AccountItem(account_id=aid, fiscal_year=FY, name='กิจกรรม', opening_balance=0); s.add(it); s.commit()
        iid = it.id
    html = page()
    assert _next_step(html) == (3, 'กรอกยอดยกมาแยกหมวด')
    assert f'ยอดยกมาทุกหมวดของปีงบ {FY} ยังเป็น 0' in html, "ต้องบอกตรง ๆ ว่าทำไมยังไม่ผ่าน"

    with tn.session_for(sid) as s:
        s.get(AccountItem, iid).opening_balance = 50000; s.commit()
    env.post('/plan-budget/2570/period', data=dict(mode='budget', start='01/10/2569', end='30/09/2570'))
    html = page()
    assert _next_step(html) == (4, 'นำเงินเข้าแผน') and 'href="/plan-budget/2570"' in html

    with tn.session_for(sid) as s:
        import_all(s, pf.plan(s, 2570), 'opening')
    html = page()
    assert _next_step(html) == (5, 'เพิ่มโครงการและจัดสรรเงิน')
    assert 'ยังไม่มีโครงการในแผน 2570' in html and '/projects/start?year=2570' in html

    with tn.session_for(sid) as s:
        p = pf.plan(s, 2570)
        pj = Project(name='กีฬาสี', plan_year=2570, budget=30000); s.add(pj); s.commit()
        pf.allocate(s, p, pj, {str(pf.sources(s, p)[0].id): '30000'}, pf.allocation_token(s, p, pj)); s.commit()
    html = page()
    assert 'id="finSetup"' not in html, "ครบทุกขั้นแล้วกล่องต้องหายเอง"


def test_hide_is_per_browser_and_safe_without_storage():
    html = (ROOT / 'app/templates/finance_dashboard.html').read_text(encoding='utf-8')
    script = html[html.index("var KEY = 'finSetupHidden'"):]
    assert 'try { return localStorage.getItem' in script and 'catch (e)' in script


def test_academic_plan_is_found_from_the_fiscal_year(db):
    """แผนปีการศึกษา 2569 (พ.ค. 2569 ถึง เม.ย. 2570) ต้องเจอเมื่อดูปีงบ 2570 ปุ่มต้องพาไปแผน 2569"""
    from tests.test_plan_funding import make_plan
    from app.services.finance_setup import setup_steps
    make_plan(db, 2569, 'academic'); db.commit()
    st = setup_steps(db, 2570)
    assert st['steps'][3]['href'] == '/plan-budget/2569'
    assert st['steps'][4]['href'] == '/projects?year=2569'
