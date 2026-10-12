# -*- coding: utf-8 -*-
"""อาหารกลางวัน จ้างเหมา: สร้างรอบพร้อมแบ่งงวดในขั้นเดียว + งวดไหนถึงคิว ขั้นไหน

เดิมสร้างรอบแล้วต้องไปหาปุ่มแบ่งงวดอีกหน้า และตารางงวดไม่บอกว่าตอนนี้ค้างที่งวดไหน
รัน: .venv\Scripts\python.exe -m pytest tests/test_lunch_rounds_flow.py
"""
import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import LunchProgram, LunchHireRound, LunchInstallment


@pytest.fixture
def prog(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p = LunchProgram(year=2569, operate_mode='hire'); s.add(p); s.commit()
        return sid, p.id


def _round(sid, pid):
    import app.tenancy as tn
    with tn.session_for(sid) as s:
        r = s.query(LunchHireRound).filter_by(program_id=pid).one()
        return r.id, [(i.seq, i.days, i.amount, i.start_date, i.end_date, i.status) for i in r.installments]


def test_split_parts_spreads_the_remainder():
    from app.routers.lunch import _split_parts
    assert _split_parts(100, 3) == [34, 33, 33] and sum(_split_parts(97, 5)) == 97


def test_creating_a_round_can_split_it_right_away(env, prog):
    sid, pid = prog
    r = env.post(f'/lunch/{pid}/rounds/add', data={'start_date': '18/05/2569', 'days': '100',
                 'end_date': '09/10/2569', 'amount': '220000', 'n_inst': '3', 'status': 'ร่าง'},
                 follow_redirects=False)
    rid, inst = _round(sid, pid)
    assert r.headers['location'] == f'/lunch/round/{rid}/plan#installments', "แบ่งแล้วพาไปดูงวดเลย"
    assert [x[1] for x in inst] == [34, 33, 33]
    assert round(sum(x[2] for x in inst), 2) == 220000, "รวมทุกงวดต้องเท่าวงเงินรอบพอดี"
    for a, b in zip(inst, inst[1:]):  # noqa: B007
        assert b[3] > a[4], "งวดถัดไปเริ่มหลังงวดก่อนจบ ไม่ทับกัน"
    assert inst[0][3].weekday() < 5 and inst[-1][4].weekday() < 5


def test_uneven_amount_still_adds_up_to_the_cent(env, prog):
    """97 วัน 5 งวด วงเงิน 100,000 หารไม่ลงตัว งวดสุดท้ายต้องรับเศษสตางค์"""
    sid, pid = prog
    env.post(f'/lunch/{pid}/rounds/add', data={'start_date': '18/05/2569', 'days': '97', 'amount': '100000',
             'n_inst': '5', 'status': 'ร่าง'})
    inst = _round(sid, pid)[1]
    assert [x[1] for x in inst] == [20, 20, 19, 19, 19]
    assert round(sum(x[2] for x in inst), 2) == 100000


def test_blank_means_no_split(env, prog):
    sid, pid = prog
    r = env.post(f'/lunch/{pid}/rounds/add', data={'start_date': '18/05/2569', 'days': '20',
                 'amount': '44000', 'n_inst': '', 'status': 'ร่าง'}, follow_redirects=False)
    assert r.headers['location'] == f'/lunch/{pid}/rounds'
    assert _round(sid, pid)[1] == []


def test_split_field_only_for_hire_new_rounds(env, prog):
    import app.tenancy as tn
    sid, pid = prog
    assert 'name="n_inst"' in env.get(f'/lunch/{pid}/rounds').text
    with tn.session_for(sid) as s:
        s.get(LunchProgram, pid).operate_mode = 'person'; s.commit()
    assert 'name="n_inst"' not in env.get(f'/lunch/{pid}/rounds').text


def test_next_installment_and_its_next_step(env, prog):
    sid, pid = prog
    env.post(f'/lunch/{pid}/rounds/add', data={'start_date': '18/05/2569', 'days': '60', 'amount': '132000',
             'n_inst': '3', 'status': 'ร่าง'})
    rid, _ = _round(sid, pid)
    import app.tenancy as tn
    with tn.session_for(sid) as s:
        ids = [i.id for i in s.get(LunchHireRound, rid).installments]
    page = lambda: env.get(f'/lunch/round/{rid}/plan').text       # noqa: E731

    html = page()
    assert 'จ่ายแล้ว <b>0</b> จาก 3 งวด' in html and 'ถึงคิว: <b>งวดที่ 1</b>' in html
    assert 'ขั้นต่อไป: <b>ส่งมอบงาน</b>' in html and 'บันทึกว่าส่งมอบแล้ว' in html

    env.post(f'/lunch/installment/{ids[0]}/update', data={'status': 'ตรวจรับแล้ว'})
    html = page()
    assert 'ขั้นต่อไป: <b>ขอเบิกและจ่ายเงิน</b>' in html and f'/lunch/installment/{ids[0]}/disburse-doc' in html

    env.post(f'/lunch/installment/{ids[0]}/update', data={'status': 'จ่ายแล้ว'})
    html = page()
    assert 'จ่ายแล้ว <b>1</b> จาก 3 งวด' in html and 'ถึงคิว: <b>งวดที่ 2</b>' in html

    for i in ids[1:]:
        env.post(f'/lunch/installment/{i}/update', data={'status': 'จ่ายแล้ว'})
    assert 'จ่ายครบทุกงวดแล้ว' in page()
