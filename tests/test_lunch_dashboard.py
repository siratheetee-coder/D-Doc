"""Overview selects one program and reads actual workflow state without posting money."""
from datetime import date, datetime
import json

from tests.test_subsidy import db, env  # noqa: F401
from app.models import (LunchProgram, LunchClass, LunchHireRound, LunchInstallment,
                        LunchLedger, LunchMenu, MoneyLoan, LoanReturn)
from app.services.lunch_dashboard import overview, round_card


def program(db, mode='hire', year=2569, students=20):
    p = LunchProgram(year=year, operate_mode=mode, rate_per_head=36, days=10)
    p.classes.append(LunchClass(level='ป.1', num_students=students))
    db.add(p); db.flush()
    return p


def hire_round(db, p, statuses):
    r = LunchHireRound(program=p, seq=1, status='ร่าง', start_date=datetime(2026, 11, 16),
                       end_date=datetime(2026, 11, 20), amount=3600, days=5)
    for n, status in enumerate(statuses, 1):
        r.installments.append(LunchInstallment(seq=n, status=status, days=5, amount=1800,
            start_date=r.start_date, end_date=r.end_date,
            calendar_dates=json.dumps(['2026-11-16','2026-11-17','2026-11-18','2026-11-19','2026-11-20'])))
    db.add(r); db.flush()
    return r


def test_paid_installments_do_not_reappear_as_pending_when_round_is_still_draft(db):
    p = program(db); r = hire_round(db, p, ['จ่ายแล้ว', 'จ่ายแล้ว'])
    c = round_card(db, r)
    assert c['complete'] and c['task'] is None and c['caption'] == 'จ่ายครบ 2/2 งวด'
    assert r.status == 'ร่าง', 'Rendering must not update contract or payment state'


def test_overview_is_one_program_not_sum_of_duplicate_school_rolls(db):
    p = program(db); other = program(db, 'person', students=20)
    pool = program(db, students=900); pool.pool = 1
    old = program(db, year=2568)
    db.add(LunchMenu(program=p, date=datetime(2026, 11, 18), main='เมนูโครงการที่เลือก'))
    db.add(LunchMenu(program=other, date=datetime(2026, 11, 18), main='คนละโครงการ'))
    db.flush()
    result = overview(db, 2569, pid=p.id, today=date(2026, 11, 18))
    assert result['program'].id == p.id and result['program'].total_students == 20
    assert {x.id for x in result['programs']} == {p.id, other.id}
    assert [m.main for m in result['menus']] == ['เมนูโครงการที่เลือก']
    historical = overview(db, 2569, year=2568, pid=p.id)
    assert historical['program'].id == old.id


def test_paid_amount_subtracts_cash_return_not_all_income(db):
    p = program(db)
    db.add_all([LunchLedger(program=p, kind='out', amount=2200),
                LunchLedger(program=p, kind='out', amount=1400),
                LunchLedger(program=p, kind='in', amount=200, loan_return_id=1),
                LunchLedger(program=p, kind='in', amount=50000)])
    db.flush()
    assert overview(db, 2569, pid=p.id)['paid'] == 3400


def test_hire_next_action_and_finance_access(db):
    p = program(db); r = hire_round(db, p, ['จ่ายแล้ว', 'ตรวจรับแล้ว'])
    finance = round_card(db, r, can_finance=True)
    assert finance['task']['href'].endswith('lunch_inst=' + str(r.installments[1].id))
    lunch_only = round_card(db, r)
    assert lunch_only['task']['href'] == f'/lunch/round/{r.id}/plan#inst-{r.installments[1].id}'
    r.pay_mode = 'round'; r.installments[0].status = 'ส่งมอบแล้ว'
    whole = round_card(db, r, can_finance=True)
    assert whole['task']['href'].endswith('#inst-' + str(r.installments[0].id))
    r.installments[0].status = 'ตรวจรับแล้ว'
    assert round_card(db, r, True)['task']['href'].endswith('lunch_round=' + str(r.id))


def test_closed_cook_round_still_reports_unreturned_loan(db):
    p = program(db, 'person')
    loan = MoneyLoan(fiscal_year=2570, amount=2200, receive_date=datetime(2026, 11, 16))
    db.add(loan); db.flush()
    r = LunchHireRound(program=p, status='จ่ายแล้ว', loan_id=loan.id, cook_wage=1400)
    db.add(r); db.flush()
    c = round_card(db, r)
    assert not c['complete'] and c['status'] == 'รอส่งใช้เงินยืม'
    assert c['task']['href'].endswith('#repay')


def test_empty_year_does_not_show_another_year_or_invent_a_menu(db):
    program(db, year=2568)
    result = overview(db, 2569, year=2570)
    assert result['program'] is None and result['menus'] == [] and result['tasks'] == []
    assert overview(db, 2569)['year'] == 2568


def test_dashboard_http_empty_and_selected_program_are_read_only(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as session:
        p = program(session)
        hire_round(session, p, ['ส่งมอบแล้ว'])
        session.add(LunchMenu(program=p, date=datetime(2026, 11, 18), main='<script>not markup</script>'))
        session.commit(); pid = p.id
        before = session.query(LunchLedger).count()
    page = env.get(f'/lunch?year=2569&pid={pid}')
    assert page.status_code == 200
    assert 'ภาพรวมอาหารกลางวัน' in page.text and 'งานที่ต้องทำต่อ' in page.text
    assert 'รอตรวจรับ' in page.text and '/static/lunch-dashboard.css' in page.text
    assert '<script>not markup</script>' not in page.text
    empty = env.get('/lunch?year=2570')
    assert empty.status_code == 200 and 'สร้างโครงการอาหารกลางวัน' in empty.text
    with tn.session_for(next(iter(tn._engines))) as session:
        assert session.query(LunchLedger).count() == before
        assert session.get(LunchProgram, pid).rounds[0].status == 'ร่าง'
