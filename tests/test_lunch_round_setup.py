# -*- coding: utf-8 -*-
"""ขั้นตอนในหน้ารอบ อาหารกลางวัน แยกตามรูปแบบ: จ้างเหมา / ซื้อวัตถุดิบ / จ้างแม่ครัว
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_lunch_round_setup.py
"""
import re
from datetime import datetime

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import LunchClass, LunchHireRound, LunchInstallment, LunchProgram, Vendor


def _titles(html):
    box = html.partition('id="setup-lround')[2].split('</ol>')[0]
    return re.findall(r'class="fs-name">\d\. ([^<]+)<', box)


def _next(html):
    m = re.search(r'class="fs-step is-next">.*?class="fs-name">\d\. ([^<]+)<', html, re.S)
    return m.group(1).strip() if m else None


@pytest.fixture
def make(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))

    def _make(mode, **rk):
        with tn.session_for(sid) as s:
            p = LunchProgram(year=2569, operate_mode=mode, rate_per_head=36, days=200); s.add(p); s.flush()
            s.add(LunchClass(program_id=p.id, level='ป.1', num_students=20))
            r = LunchHireRound(program_id=p.id, seq=1, **rk); s.add(r); s.commit()
            return sid, p.id, r.id
    return _make


@pytest.mark.parametrize('mode,expected', [
    ('hire', ['ตั้งช่วงเวลาและวงเงิน', 'เลือกผู้รับจ้าง', 'แต่งตั้งกรรมการ', 'ใส่เมนูอาหารครบทุกวัน',
              'ตกลงจ้าง (เลขที่ใบสั่งจ้าง)', 'แบ่งงวดจ่ายเงิน', 'ส่งมอบ ตรวจรับ และจ่ายครบทุกงวด']),
    ('ingredient', ['ตั้งช่วงเวลา', 'แต่งตั้งกรรมการ', 'ใส่เมนูอาหารครบทุกวัน', 'กรอกวัตถุดิบรายวัน',
                    'ส่งใช้เงินยืมและปิดรอบ']),
    ('person', ['ตั้งช่วงเวลาและค่าจ้างแม่ครัว', 'เลือกแม่ครัว (ผู้รับจ้าง)', 'แต่งตั้งกรรมการ',
                'ใส่เมนูอาหารครบทุกวัน', 'กรอกวัตถุดิบรายวัน', 'ตกลงจ้าง (เลขที่ใบสั่งจ้าง)', 'เบิกจ่ายและปิดรอบ']),
])
def test_each_mode_has_its_own_steps(env, make, mode, expected):
    _, _, rid = make(mode)
    html = env.get(f'/lunch/round/{rid}/plan').text
    titles = [t for t in _titles(html) if t != 'กรอกเลขที่หนังสือ']     # มีเฉพาะรูปแบบที่มีเอกสารให้ใส่เลข
    assert titles == expected
    word = 'รอบจัดซื้อ' if mode == 'ingredient' else 'รอบจัดจ้าง'
    assert f'ขั้นตอนของ{word}ที่ 1' in html


def test_hire_round_moves_forward_with_real_data(env, make):
    import app.tenancy as tn
    sid, pid, rid = make('hire')
    page = lambda: env.get(f'/lunch/round/{rid}/plan').text          # noqa: E731
    assert _next(page()) == 'ตั้งช่วงเวลาและวงเงิน'
    with tn.session_for(sid) as s:
        r = s.get(LunchHireRound, rid)
        r.start_date, r.end_date, r.days, r.amount = datetime(2026, 5, 18), datetime(2026, 5, 22), 5, 3600
        v = Vendor(name='ร้านอาหารทดสอบ'); s.add(v); s.flush(); r.vendor_id = v.id; s.commit()
    html = page()
    assert _next(html) == 'แต่งตั้งกรรมการ' and 'ยังไม่มีกรรมการ' in html
    with tn.session_for(sid) as s:
        r = s.get(LunchHireRound, rid)
        r.order_no, r.order_date = '12/2569', datetime(2026, 5, 15)
        s.add(LunchInstallment(round_id=rid, seq=1, amount=3600, status='จ่ายแล้ว')); s.commit()
    html = page()
    done = re.findall(r'class="fs-step is-done">.*?class="fs-name">\d\. ([^<]+)<', html, re.S)
    assert {'ตั้งช่วงเวลาและวงเงิน', 'เลือกผู้รับจ้าง', 'ตกลงจ้าง (เลขที่ใบสั่งจ้าง)', 'แบ่งงวดจ่ายเงิน',
            'ส่งมอบ ตรวจรับ และจ่ายครบทุกงวด'} <= set(done)


def test_ingredient_over_budget_is_not_done(env, make):
    from app.services.module_setup import lunch_round_steps
    import app.tenancy as tn
    sid, pid, rid = make('ingredient', start_date=datetime(2026, 5, 18), days=5)
    with tn.session_for(sid) as s:
        r = s.get(LunchHireRound, rid)
        st = lunch_round_steps(r, committees={}, com_labels={}, doc_rows=[], menu_days=[],
                               ing_total=5000, ing_remaining=-200)
    ing = next(x for x in st['steps'] if x['title'] == 'กรอกวัตถุดิบรายวัน')
    assert not ing['done'] and 'เกินงบ 200.00 บาท' in ing['detail']


def test_page_has_anchor_targets(env, make):
    _, _, rid = make('hire', start_date=datetime(2026, 5, 18), end_date=datetime(2026, 5, 22), days=5)
    html = env.get(f'/lunch/round/{rid}/plan').text
    for anchor in ('id="committee"', 'id="menus"', 'id="installments"'):
        assert anchor in html, anchor


def test_hire_last_step_waits_for_every_installment(env, make):
    import app.tenancy as tn
    sid, pid, rid = make('hire')
    with tn.session_for(sid) as s:
        s.add_all([LunchInstallment(round_id=rid, seq=1, amount=100, status='จ่ายแล้ว'),
                   LunchInstallment(round_id=rid, seq=2, amount=100, status='ตรวจรับแล้ว')]); s.commit()
    from app.services.module_setup import lunch_round_steps
    with tn.session_for(sid) as s:
        st = lunch_round_steps(s.get(LunchHireRound, rid), committees={}, com_labels={}, doc_rows=[],
                               menu_days=[], ing_total=0, ing_remaining=0)
    last = st['steps'][-1]
    assert last['title'] == 'ส่งมอบ ตรวจรับ และจ่ายครบทุกงวด'
    assert not last['done'] and last['detail'] == 'จ่ายแล้ว 1 จาก 2 งวด'
