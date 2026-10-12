# -*- coding: utf-8 -*-
"""โรงเรียนที่เริ่มใช้ระบบกลางแผน: ดึงเงินเข้าแผนแล้วได้ 0

แผนปีการศึกษา 2569 เริ่ม พ.ค. 2569 ระบบหาเงินเหลือ ณ ก่อนเริ่มแผน ซึ่งอยู่ในปีงบ 2569
แต่โรงเรียนเริ่มใช้ระบบ ต.ค. 2569 กรอกยอดยกมาไว้ที่ปีงบ 2570 หน้าตรวจยอดเลยว่างเปล่า
และไม่บอกเหตุผล (เจ้าของเจอเองบนเครื่องจริง) ตอนนี้ระบบใช้ยอดยกมาต้นปีงบ 2570 แทน
และหน้าตรวจยอดบอกว่าไปหาเงินจากปีงบไหน
รัน: .venv\Scripts\python.exe -m pytest tests/test_plan_joined.py
"""
import pathlib
from datetime import datetime

import pytest

from tests.test_subsidy import db, env  # noqa: F401  (fixtures)
from tests.test_plan_funding import make_plan, import_all
from app.models import FinanceAccount, AccountItem, FinanceTxn, Project
from app.services import plan_funding as pf

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _items(db, fy, **amounts):
    a = FinanceAccount(name='เงินอุดหนุน'); db.add(a); db.flush()
    out = {}
    for name, v in amounts.items():
        i = AccountItem(account_id=a.id, fiscal_year=fy, name=name, opening_balance=v); db.add(i); db.flush()
        out[name] = i
    db.commit()
    return out


def test_joined_mid_plan_uses_the_next_fiscal_year_opening(db):
    p = make_plan(db, 2569, 'academic')                  # 1 พ.ค. 2569 ถึง 30 เม.ย. 2570
    _items(db, 2570, กิจกรรม=50000, การสอน=80000)          # เริ่มใช้ระบบ 1 ต.ค. 2569
    data = pf.preview(db, p, 'opening')
    assert sorted(r['amount'] for r in data['rows']) == [50000, 80000]
    assert data['info']['joined'] == 2570 and not data['info']['has_data']
    assert all('ยอดยกมาต้นปีงบ 2570' in r['name'] for r in data['rows'])
    import_all(db, p, 'opening')
    assert pf.summary(db, p)['total'] == 130000
    src = pf.sources(db, p)[0]
    assert not pf.changed(db, p, src), "ยอดไม่เปลี่ยน ต้องไม่ขึ้นเตือน"
    db.get(AccountItem, src.account_item_id).opening_balance = 45000; db.commit()
    assert pf.changed(db, p, src), "แก้ยอดยกมาแล้ว หน้าแผนต้องเตือนให้อัปเดต"


def test_school_already_using_the_system_keeps_the_old_rule(db):
    """มีข้อมูลปีงบ 2569 แล้ว (แม้ยอดเป็น 0 แต่มีรายการรับจ่าย) ห้ามไปหยิบยอดปีงบ 2570 มานับซ้ำ"""
    p = make_plan(db, 2569, 'academic')
    old = _items(db, 2569, กิจกรรม=0)['กิจกรรม']
    db.add(FinanceTxn(account_id=old.account_id, item_id=old.id, fiscal_year=2569,
                      date=datetime(2026, 6, 1), kind='in', amount=9000))
    _items(db, 2570, กิจกรรม=50000)
    data = pf.preview(db, p, 'opening')
    assert data['info']['joined'] is None and data['info']['has_data']
    assert all('2570' not in r['name'] for r in data['rows'])


def test_budget_year_plan_is_unchanged(db):
    p = make_plan(db, 2570, 'budget')
    _items(db, 2570, กิจกรรม=50000)
    data = pf.preview(db, p, 'opening')
    assert [r['amount'] for r in data['rows']] == [50000] and data['info']['joined'] is None


def test_allocation_leaves_out_what_was_spent_before_the_system(db):
    p = make_plan(db, 2569, 'academic')
    _items(db, 2570, กิจกรรม=50000)
    import_all(db, p, 'opening')
    pj = Project(name='กีฬาสี', plan_year=2569, budget=30000, spent_before=8000); db.add(pj); db.commit()
    fid = str(pf.sources(db, p)[0].id)
    with pytest.raises(ValueError, match='22,000.00'):
        pf.allocate(db, p, pj, {fid: '30000'}, pf.allocation_token(db, p, pj))
    db.rollback()
    pf.allocate(db, p, pj, {fid: '22000'}, pf.allocation_token(db, p, pj)); db.commit()
    assert pf.project_allocated(db, pj.id) == 22000


def test_review_page_explains_where_it_looked(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    assert env.post('/plan-budget/2569/period', data=dict(mode='academic', start='18/05/2569',
                                                           end='30/04/2570')).status_code == 200
    html = env.get('/plan-budget/2569/review?kind=opening').text
    assert 'ปีงบ 2569' in html and '17 พฤษภาคม 2569' in html, "ว่างเปล่าต้องบอกว่าไปหาเงินจากปีงบไหน วันไหน"
    assert '/finance/accounts?year=2569' in html
    with tn.session_for(sid) as s:
        _items(s, 2570, กิจกรรม=50000)
    html = env.get('/plan-budget/2569/review?kind=opening').text
    assert 'ยอดยกมาต้นปีงบ 2570' in html and '50,000.00' in html
    assert '/projects/start?year=2569' in html


def test_project_page_does_not_call_pre_system_spending_unallocated(env):
    """กีฬาสี งบ 30,000 ใช้ไปก่อนเริ่มใช้ระบบ 8,000 จัดสรร 22,000 = ครบแล้ว ไม่ใช่ "ยังไม่ได้จัดสรร 8,000" """
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    env.post('/plan-budget/2569/period', data=dict(mode='academic', start='18/05/2569', end='30/04/2570'))
    with tn.session_for(sid) as s:
        _items(s, 2570, กิจกรรม=50000)
        p = pf.plan(s, 2569); import_all(s, p, 'opening')
        pj = Project(name='กีฬาสี', plan_year=2569, budget=30000, spent_before=8000); s.add(pj); s.commit()
        pid, fid = pj.id, str(pf.sources(s, p)[0].id)
        pf.allocate(s, p, pj, {fid: '22000'}, pf.allocation_token(s, p, pj)); s.commit()
    html = env.get(f'/projects/{pid}').text
    assert 'ใช้ไปก่อนเริ่มใช้ระบบ <b>8,000.00</b> (ไม่ต้องจัดสรร)' in html
    assert 'จัดสรรครบแล้ว' in html and 'ยังไม่ได้จัดสรร <b>' not in html
