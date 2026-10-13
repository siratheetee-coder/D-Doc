# -*- coding: utf-8 -*-
"""หน้าโครงการ: รายการเริ่มต้น + คำอธิบาย ใส่งบ กับ ปรับงบ

มีสิทธิ์งานการเงิน = 5 ขั้นชุดเดียวกับหน้าการเงิน (ซ่อนแล้วซ่อนทั้งสองหน้า)
ไม่มีสิทธิ์ = ชุดสั้นเรื่องโครงการล้วน เพราะทะเบียนคุมเงิน/หน้างบแผน เป็นของงานการเงิน เข้าไม่ได้
รัน: .venv\Scripts\python.exe -m pytest tests/test_projects_setup.py
"""
import re

import pytest

from tests.test_subsidy import db, env  # noqa: F401  (fixtures)
from app.models import Project

PY = 2593


def _next_step(html):
    m = re.search(r'class="fs-step is-next">.*?class="fs-name">(\d)\. ([^<]+)<', html, re.S)
    return (int(m.group(1)), m.group(2).strip()) if m else None


def test_project_only_steps_walk_in_order(db):
    from app.services.finance_setup import project_steps
    st = project_steps(db, PY)
    assert st['next']['title'] == 'เพิ่มโครงการ' and st['done'] == 0
    a = Project(name='กีฬาสี', plan_year=PY, budget=0); b = Project(name='ค่าย', plan_year=PY, budget=20000,
                                                                 responsible='วิชาการ')
    db.add_all([a, b]); db.commit()
    st = project_steps(db, PY)
    assert st['next']['title'] == 'ใส่งบให้ทุกโครงการ'
    assert 'ยังมี 1 โครงการที่งบเป็น 0: กีฬาสี' in st['next']['detail'] and st['next']['href'] == f'/projects/{a.id}'
    a.budget = 30000; db.commit()
    st = project_steps(db, PY)
    assert st['next']['title'] == 'ระบุฝ่ายที่รับผิดชอบ' and 'กีฬาสี' in st['next']['detail']
    a.responsible = 'กิจการนักเรียน'; db.commit()
    assert project_steps(db, PY)['complete']


def test_user_with_finance_sees_the_same_list_as_the_finance_page(env):
    html = env.get(f'/projects?year={PY}').text
    assert 'id="setup-fin"' in html and 'เริ่มต้นงานการเงินและโครงการ' in html
    assert 'เลือกงบที่จะใช้ในแผน' in html


def test_user_without_finance_gets_the_short_list_and_no_locked_links(env, monkeypatch):
    import app.routers.pages as pages
    monkeypatch.setattr(pages, '_can_finance', lambda request: False)
    html = env.get(f'/projects?year={PY}').text
    assert 'id="setup-proj"' in html and 'เริ่มต้นวางแผนโครงการ' in html
    assert _next_step(html) == (1, 'เพิ่มโครงการ') and 'href="#add-project"' in html
    assert 'href="/plan-budget/' not in html and 'href="/finance' not in html.split('id="setup-proj"')[1].split('</ol>')[0]
    assert 'เลือกงบที่จะใช้ในแผน' not in html, "หน้างบที่ใช้จัดทำแผนเป็นของงานการเงิน ไม่มีสิทธิ์ก็ไม่ต้องโชว์"


def test_budget_help_is_on_both_pages(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as s:
        p = Project(name='ทดสอบคำอธิบาย', plan_year=PY, budget=1000); s.add(p); s.commit(); pid = p.id
    lst = env.get(f'/projects?year={PY}').text
    one = env.get(f'/projects/{pid}').text
    for html in (lst, one):
        assert 'id="budget-help"' in html and 'ใส่งบ กับ ปรับงบ ต่างกันยังไง' in html
        assert 'บันทึกเป็นปรับงบครั้งที่ 1' in html
    assert '<details class="bh" id="budget-help" open>' in one, "ยังไม่เคยปรับงบ กางคำอธิบายไว้ให้"


def test_project_page_hides_allocation_without_finance(env, monkeypatch):
    import app.tenancy as tn
    import app.routers.pages as pages
    with tn.session_for(next(iter(tn._engines))) as s:
        p = Project(name='ทดสอบไม่มีการเงิน', plan_year=PY, budget=1000); s.add(p); s.commit(); pid = p.id
    assert 'id="project-funding"' in env.get(f'/projects/{pid}').text
    monkeypatch.setattr(pages, '_can_finance', lambda request: False)
    html = env.get(f'/projects/{pid}').text
    assert 'id="project-funding"' not in html and 'href="/plan-budget/' not in html
    assert 'id="budget-help"' in html, "คำอธิบายใส่งบ/ปรับงบ ยังต้องอยู่"
    assert 'class="bh-note"' not in html, "เรื่องจัดสรรเงินไม่เกี่ยวกับผู้ไม่มีสิทธิ์การเงิน"
