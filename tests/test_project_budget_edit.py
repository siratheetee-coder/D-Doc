# -*- coding: utf-8 -*-
"""หน้าโครงการ: ใส่งบตรง ๆ + ปรับงบให้เชื่อมกับการจัดสรรเงิน

1. งบเป็น 0 ใส่ได้เลย / มีงบแล้วกด "แก้งบ" ได้ ตราบใดที่ยังไม่เคยปรับงบ (เจ้าของเลือกแบบมีปุ่มแก้งบ)
   เดิมทางเดียวคือ "ปรับงบ ครั้งที่ 1" ทั้งที่แค่ใส่งบครั้งแรก
2. ปรับงบเพิ่ม: พาไปช่องจัดสรร เติมยอดใหม่ไว้ให้ (ปรับงบเปลี่ยนแค่ตัวเลขแผน เงินผูกผ่านการจัดสรร)
3. ปรับงบลดต่ำกว่าที่จัดสรร: กลับหน้าเดิมพร้อมบอกวิธีแก้ (เดิมเด้งไปหน้าข้อผิดพลาด 409)
รัน: .venv\Scripts\python.exe -m pytest tests/test_project_budget_edit.py
"""
import pathlib
import re
from urllib.parse import unquote

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)
from tests.test_plan_funding import import_all
from app.models import FinanceAccount, AccountItem, Project, ProjectBudgetRevision
from app.services import plan_funding as pf

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def world(env):
    """แผนปีงบ 2570 มีเงินหมวดกิจกรรม 50,000 นำเข้าแผนแล้ว · กีฬาสี งบ 30,000 จัดสรรครบ · ค่าย งบ 0"""
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    env.post('/plan-budget/2570/period', data=dict(mode='budget', start='01/10/2569', end='30/09/2570'))
    with tn.session_for(sid) as s:
        a = FinanceAccount(name='เงินอุดหนุน'); s.add(a); s.flush()
        s.add(AccountItem(account_id=a.id, fiscal_year=2570, name='กิจกรรม', opening_balance=50000)); s.commit()
        p = pf.plan(s, 2570); import_all(s, p, 'opening')
        sport = Project(name='กีฬาสี', plan_year=2570, budget=30000)
        camp = Project(name='ค่าย', plan_year=2570, budget=0)
        s.add_all([sport, camp]); s.commit()
        fid = pf.sources(s, p)[0].id
        pf.allocate(s, p, sport, {str(fid): '30000'}, pf.allocation_token(s, p, sport)); s.commit()
        return dict(sid=sid, sport=sport.id, camp=camp.id, fid=fid)


def _proj(w, pid):
    import app.tenancy as tn
    with tn.session_for(w['sid']) as s:
        p = s.get(Project, pid)
        return float(p.budget or 0), [(r.seq, r.amount) for r in p.revisions]


def test_zero_budget_can_be_entered_directly(env, world):
    html = env.get(f"/projects/{world['camp']}").text
    assert 'โครงการนี้ยังไม่ได้ใส่งบ' in html and f'action="/projects/{world["camp"]}/set-budget"' in html
    env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '25,000'})
    assert _proj(world, world['camp']) == (25000, []), "ใส่งบครั้งแรกต้องไม่นับเป็นการปรับงบ"
    html = env.get(f"/projects/{world['camp']}").text
    assert 'โครงการนี้ยังไม่ได้ใส่งบ' not in html and '>แก้งบ</button>' in html


def test_edit_button_goes_away_once_revised(env, world):
    env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '25000'})
    env.post(f"/projects/{world['camp']}/revise", data={'amount': '27000', 'reason': 'แผนเปลี่ยน'})
    html = env.get(f"/projects/{world['camp']}").text
    assert '>แก้งบ</button>' not in html and 'id="setBudget"' not in html
    r = env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '1'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and _proj(world, world['camp'])[0] == 25000


@pytest.mark.parametrize('value', [25000, 32000, 90000])
def test_budget_revisions_do_not_reserve_or_require_source_amounts(env, world, value):
    import app.tenancy as tn
    from app.models import ProjectFunding
    with tn.session_for(world['sid']) as db:
        before=pf.summary(db,pf.plan(db,2570))['remaining']
        ids=[a.funding_id for a in db.query(ProjectFunding).filter_by(project_id=world['sport'])]
    r=env.post(f"/projects/{world['sport']}/revise",data={'amount':str(value),'reason':'ปรับแผน'},follow_redirects=False)
    assert r.status_code==303 and 'err=' not in r.headers['location'] and 'grew=' not in r.headers['location']
    assert _proj(world,world['sport'])[1][-1][1]==value
    with tn.session_for(world['sid']) as db:
        assert pf.summary(db,pf.plan(db,2570))['remaining']==before==50000
        assert [a.funding_id for a in db.query(ProjectFunding).filter_by(project_id=world['sport'])]==ids
    html=env.get(r.headers['location']).text
    assert 'var assigned' not in html and 'data-funding-amount' not in html
    assert 'type="checkbox" name="fund_' in html
