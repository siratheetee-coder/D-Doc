# -*- coding: utf-8 -*-
"""เชื่อมเงินอาหารกลางวันกับทะเบียนคุมเงิน (ตามแผนที่เจ้าของกำหนด)

การเงินลงรับก่อนเสมอ · บัญชีแยกของอาหารกลางวัน · หน้าอาหารกลางวันดึงรายการรับมาเอง
ปีการศึกษาตามวันที่รับ (16 พ.ค. ถึง 15 พ.ค.) เปลี่ยนได้รายรายการ · รายการจ่ายลงบัญชีที่เลือก
ย้ายรายการเดิมต้องยืนยันก่อน · เตือนลงรับซ้ำ · รายการที่คัดลอกไปแก้ที่หน้าอาหารกลางวัน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_lunch_finance_link.py
"""
from datetime import date, datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import (FinanceAccount, FinanceTxn, LunchClass, LunchHireRound, LunchLedger,
                        LunchProgram)
from app.services import lunch_finance as lf


def test_academic_year_boundary_is_16_may():
    assert lf.lunch_year_of(date(2026, 5, 15)) == 2568
    assert lf.lunch_year_of(date(2026, 5, 16)) == 2569
    assert lf.lunch_year_of(datetime(2027, 3, 1)) == 2569
    assert lf.year_range_text(2569) == '16 พ.ค. 2569 ถึง 15 พ.ค. 2570'


def _sid():
    import app.tenancy as tn
    return next(iter(tn._engines))


def _prog(s, **kw):
    p = LunchProgram(year=2569, operate_mode='hire', rate_per_head=36, days=200, **kw); s.add(p); s.flush()
    s.add(LunchClass(program_id=p.id, level='ป.1', num_students=10)); s.flush()
    return p


def test_setup_form_preselects_the_schools_own_lunch_account(env):
    import app.tenancy as tn
    with tn.session_for(_sid()) as s:
        auto = FinanceAccount(name='อาหารกลางวัน', note='เชื่อมอัตโนมัติจากงานอาหารกลางวัน')
        own = FinanceAccount(name='เงินอุดหนุนอาหารกลางวัน อบต.')
        s.add_all([auto, own]); s.commit(); oid = own.id
    html = env.get('/lunch/setup').text
    assert 'บัญชีเงินอาหารกลางวัน' in html and f'<option value="{oid}" selected>' in html


def test_income_comes_from_the_account_with_year_choice(env):
    import app.tenancy as tn
    with tn.session_for(_sid()) as s:
        acc = FinanceAccount(name='เงินอาหารกลางวันทดสอบ'); s.add(acc); s.flush()
        p = _prog(s, finance_account_id=acc.id)
        t = FinanceTxn(account_id=acc.id, fiscal_year=2570, kind='in', amount=128400,
                       date=datetime(2026, 11, 1), note='รับเงินอุดหนุนรอบ 1 เทอม 2')
        early = FinanceTxn(account_id=acc.id, fiscal_year=2569, kind='in', amount=5000,
                           date=datetime(2026, 5, 10), note='เงินปีก่อน')
        s.add_all([t, early]); s.commit(); pid, tid = p.id, t.id
    html = env.get(f'/lunch/{pid}').text
    assert 'รับเงินอุดหนุนรอบ 1 เทอม 2' in html and 'จากทะเบียนคุมเงิน' in html
    assert 'เงินปีก่อน' not in html, 'รับก่อน 16 พ.ค. เป็นของปีการศึกษาก่อนหน้า'
    assert 'ใช้กับโครงการปีการศึกษา' in html and '<option value="2569" selected>ปีการศึกษา 2569</option>' in html
    assert '16 พ.ค. 2569 ถึง 15 พ.ค. 2570' in html and 'รับ: <b>128,400.00</b>' in html
    env.post(f'/lunch/{pid}/income/{tid}/year', data={'lunch_year': '2570'})
    assert 'รับเงินอุดหนุนรอบ 1 เทอม 2' not in env.get(f'/lunch/{pid}').text, 'ย้ายไปใช้กับปีอื่นแล้ว'
    with tn.session_for(_sid()) as s:
        assert s.get(FinanceTxn, tid).lunch_year == 2570
    env.post(f'/lunch/{pid}/income/{tid}/year', data={'lunch_year': '2569'})
    with tn.session_for(_sid()) as s:
        assert s.get(FinanceTxn, tid).lunch_year is None, 'กลับมาตรงกับวันที่รับ = ไม่ต้องเก็บค่า'
    assert env.get(f'/lunch/{pid}/income/{tid}/official-receipt.docx').status_code == 200


def test_manual_income_is_refused_once_linked(env):
    import app.tenancy as tn
    with tn.session_for(_sid()) as s:
        acc = FinanceAccount(name='เงินอาหารกลางวันทดสอบ 2'); s.add(acc); s.flush()
        p = _prog(s, finance_account_id=acc.id); s.commit(); pid = p.id
    r = env.post(f'/lunch/{pid}/ledger/add', data={'kind': 'in', 'amount': '100', 'detail': 'x'},
                 follow_redirects=False)
    assert 'err=' in r.headers['location']
    with tn.session_for(_sid()) as s:
        assert s.query(LunchLedger).filter_by(program_id=pid).count() == 0
    assert '<option value="in">' not in env.get(f'/lunch/{pid}').text


def test_round_payment_goes_to_chosen_account_and_no_auto_account(env):
    import app.tenancy as tn
    with tn.session_for(_sid()) as s:
        s.query(FinanceAccount).filter_by(name='อาหารกลางวัน').delete(); s.commit()
        acc = FinanceAccount(name='เงินอาหารกลางวันทดสอบ 3'); s.add(acc); s.flush()
        p = _prog(s, finance_account_id=acc.id)
        r = LunchHireRound(program_id=p.id, seq=1, days=10, amount=3600); s.add(r); s.commit()
        rid, aid = r.id, acc.id
    env.post(f'/lunch/round/{rid}/status', data={'status': 'จ่ายแล้ว'})
    with tn.session_for(_sid()) as s:
        led = s.query(LunchLedger).filter_by(round_id=rid).one()
        assert s.get(FinanceTxn, led.finance_txn_id).account_id == aid
        assert s.query(FinanceAccount).filter_by(name='อาหารกลางวัน').count() == 0
        tid = led.finance_txn_id
    html = env.get(f'/finance/accounts/{aid}').text
    assert 'แก้ที่หน้าอาหารกลางวัน' in html
    env.post(f'/finance/txn/{tid}/delete')
    with tn.session_for(_sid()) as s:
        assert s.get(FinanceTxn, tid) is not None, 'ลบที่การเงินไม่ได้ ต้องแก้ที่หน้าอาหารกลางวัน'


def test_switching_account_asks_before_moving_old_entries(env):
    import app.tenancy as tn
    with tn.session_for(_sid()) as s:
        p = _prog(s); s.commit(); pid = p.id
    env.post(f'/lunch/{pid}/ledger/add', data={'kind': 'in', 'amount': '1000', 'detail': 'รับเก่า',
                                               'date': '01/06/2569'})
    env.post(f'/lunch/{pid}/ledger/add', data={'kind': 'out', 'amount': '300', 'detail': 'จ่ายเก่า',
                                               'date': '02/06/2569'})
    with tn.session_for(_sid()) as s:
        new = FinanceAccount(name='เงินอาหารกลางวันใหม่'); s.add(new); s.commit(); nid = new.id
        p = s.get(LunchProgram, pid)
        form = {'pid': pid, 'year': 2569, 'days': 200, 'operate_mode': 'hire', 'finance_account_id': nid,
                'level': 'ป.1', 'num': 10}
    r = env.post('/lunch/save', data=form, follow_redirects=False)
    assert r.headers['location'] == f'/lunch/{pid}/finance-account?to={nid}'
    html = env.get(r.headers['location']).text
    assert '2 รายการ' in html and '1,000.00' in html and '300.00' in html
    with tn.session_for(_sid()) as s:
        assert s.get(LunchProgram, pid).finance_account_id is None, 'ยังไม่ยืนยัน ยังไม่เปลี่ยน'
    env.post(f'/lunch/{pid}/finance-account', data={'to': nid})
    with tn.session_for(_sid()) as s:
        assert s.get(LunchProgram, pid).finance_account_id == nid
        ids = [l.finance_txn_id for l in s.query(LunchLedger).filter_by(program_id=pid)]
        assert {s.get(FinanceTxn, i).account_id for i in ids} == {nid}


def test_duplicate_income_is_flagged():
    a = ('รับรอบ 1', datetime(2026, 11, 1), 128400.0)
    assert lf.duplicates([a, ('รับซ้ำ', datetime(2026, 11, 6), 128400.0)])
    assert not lf.duplicates([a, ('คนละก้อน', datetime(2026, 11, 20), 128400.0)])
    assert not lf.duplicates([a, ('ยอดต่าง', datetime(2026, 11, 2), 99.0)])
