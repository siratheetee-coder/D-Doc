# -*- coding: utf-8 -*-
"""อาหารกลางวัน: "รอบ" กับ "งวด" ฟังเหมือนกันว่าช่วงเวลา ผู้ใช้งง

เจ้าของเลือกคำ "รอบจัดจ้าง" (ทำเรื่อง 1 ครั้ง) กับ "งวดจ่ายเงิน" (แบ่งจ่ายในรอบ)
โหมดซื้อวัตถุดิบเป็นการจัดซื้อ จึงใช้ "รอบจัดซื้อ" · งวดมีเฉพาะจ้างเหมา
และเลิกให้เลือกรอบ รายวัน/สัปดาห์/เดือน (ไม่ได้ใช้คำนวณหรือออกเอกสาร ช่วงวันที่บอกอยู่แล้ว)
รัน: .venv\Scripts\python.exe -m pytest tests/test_lunch_wording.py
"""
from datetime import datetime

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import LunchProgram, LunchHireRound


@pytest.fixture
def make(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))

    def _make(mode):
        with tn.session_for(sid) as s:
            p = LunchProgram(year=2569, operate_mode=mode); s.add(p); s.flush()
            r = LunchHireRound(program_id=p.id, seq=1, period_type="week", start_date=datetime(2026, 5, 18),
                               end_date=datetime(2026, 6, 30), days=30, amount=66000)
            s.add(r); s.commit()
            return p.id, r.id
    return _make


def test_hire_mode_explains_round_and_installment(env, make):
    pid, rid = make('hire')
    html = env.get(f'/lunch/{pid}/rounds').text
    assert 'รอบจัดจ้างทั้งหมด' in html and 'งวดจ่ายเงิน' in html and 'ตัวอย่าง: ภาคเรียนที่ 1' in html
    assert 'name="period_type"' not in html and 'รายสัปดาห์' not in html, "เลิกให้เลือกรายวัน/สัปดาห์/เดือนแล้ว"
    page = env.get(f'/lunch/round/{rid}/plan').text
    assert 'รอบจัดจ้างที่ 1' in page and 'งวดจ่ายเงินทั้งหมด' in page and 'แบ่งงวดจ่ายเงินอัตโนมัติ' in page
    assert 'งวดงาน' not in page and 'สัญญาจ้างเหมา รอบที่' not in page


@pytest.mark.parametrize('mode,word', [('person', 'รอบจัดจ้าง'), ('ingredient', 'รอบจัดซื้อ')])
def test_modes_without_installments_never_mention_them(env, make, mode, word):
    pid, rid = make(mode)
    html = env.get(f'/lunch/{pid}/rounds').text
    assert f'{word}ทั้งหมด' in html and 'ไม่มีงวด' in html
    assert 'งวดจ่ายเงิน' not in html
    page = env.get(f'/lunch/round/{rid}/plan').text
    assert f'{word}ที่ 1' in page and 'แบ่งงวดจ่ายเงินอัตโนมัติ' not in page


def test_editing_a_round_keeps_its_old_period_type(env, make):
    import app.tenancy as tn
    pid, rid = make('hire')
    env.post(f'/lunch/round/{rid}/update', data={'start_date': '18/05/2569', 'days': '30',
                                                 'end_date': '30/06/2569', 'amount': '66000'})
    with tn.session_for(next(iter(tn._engines))) as s:
        assert s.get(LunchHireRound, rid).period_type == 'week'
