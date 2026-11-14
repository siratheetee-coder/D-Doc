from datetime import datetime,timedelta
from pathlib import Path
import os
from tests.test_subsidy import db,env
from app.models import (School,FinanceAccount,FinanceTxn,DisburseMemo,Procurement,Approval,MoneyLoan,
    LunchHireRound,LunchInstallment,LunchLedger,LunchDisburseLink)
from app.services.finance_overview import overview,claim_requests
from app.services.dashboard_tasks import finance_tasks
from app.services import approval
from app.thai_utils import thai_today

def test_ready_count_uses_actual_payments_and_selected_fiscal_year(db):
    a=FinanceAccount(name='บัญชีทดสอบ');db.add(a);db.flush()
    rows=[DisburseMemo(fiscal_year=fy,memo_no=no,subject=no,status=status,amount=1000,account_id=a.id)
        for fy,no,status in [(2570,'READY','อนุมัติ'),(2570,'DRAFT','ร่าง'),(2570,'ACTUALLY_PAID','ร่าง'),
                              (2570,'FLAG_WITHOUT_PAYMENT','จ่ายแล้ว'),(2569,'OLD_YEAR','อนุมัติ')]]
    db.add_all(rows);db.flush()
    db.add(FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=1000,disburse_id=rows[2].id));db.commit()
    before=(db.query(FinanceTxn).count(),db.query(DisburseMemo).count())
    data=overview(db,2570,finance_tasks(db,2570))
    assert data['ready']==1
    assert data['statuses'][rows[2].id]['code']=='paid'
    assert data['statuses'][rows[3].id]['code']=='review'
    assert rows[4].id not in data['statuses'] and rows[4] not in data['recent']
    assert before==(db.query(FinanceTxn).count(),db.query(DisburseMemo).count())

def test_approval_pending_and_stale_do_not_count_as_ready(db):
    db.query(School).first().approval_on=True
    a=FinanceAccount(name='ทดสอบ');db.add(a);db.flush()
    m=DisburseMemo(fiscal_year=2570,amount=1000,account_id=a.id,status='อนุมัติ');db.add(m);db.flush()
    sent=approval.send(db,'disburse',m.id,'ผู้ส่ง');db.commit()
    assert overview(db,2570,finance_tasks(db,2570))['ready']==0
    sent.status='approved';db.commit()
    assert overview(db,2570,finance_tasks(db,2570))['ready']==1
    m.amount=1200;db.commit()
    data=overview(db,2570,finance_tasks(db,2570));assert data['ready']==0
    assert data['statuses'][m.id]['label']=='รอแก้ไข'

def test_inspected_sources_exclude_claimed_paid_and_other_year(db):
    rows=[Procurement(fiscal_year=year,subject=name,status='ตรวจรับแล้ว',paid_before_system=paid,total_amount=1000)
        for year,name,paid in [(2570,'WAITING',False),(2570,'CLAIMED',False),(2570,'LEGACY_PAID',True),(2569,'OLD',False)]]
    db.add_all(rows);db.flush()
    db.add(DisburseMemo(fiscal_year=2570,amount=1000,procurement_id=rows[1].id));db.commit()
    result=claim_requests(db,2570)
    assert [x['title'] for x in result]==['WAITING']

def test_wrong_kind_and_incomplete_payments_are_reviewed(db):
    a=FinanceAccount(name='ทดสอบ');db.add(a);db.flush()
    incoming=DisburseMemo(fiscal_year=2570,amount=1000,account_id=a.id,status='อนุมัติ')
    partial=DisburseMemo(fiscal_year=2570,amount=2000,account_id=a.id,status='อนุมัติ')
    db.add_all([incoming,partial]);db.flush()
    db.add_all([FinanceTxn(account_id=a.id,fiscal_year=2570,kind='in',amount=1000,disburse_id=incoming.id),
                FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=1000,disburse_id=partial.id)])
    db.commit();data=overview(db,2570,finance_tasks(db,2570))
    assert data['ready']==0
    assert all(data['statuses'][m.id]['code']=='review' for m in [incoming,partial])

def test_lunch_requests_respect_payment_mode_claim_links_and_legacy_ledgers(db):
    from tests.test_shared_school_calendar import setup
    p,cls,r,a,b=setup(db);a.status=b.status='ตรวจรับแล้ว';db.commit()
    assert len(claim_requests(db,2570))==2
    m=DisburseMemo(fiscal_year=2570,amount=7632);db.add(m);db.flush()
    db.add(LunchDisburseLink(source_key=f'i:{a.id}',round_id=r.id,installment_id=a.id,memo_id=m.id,fingerprint='old'))
    db.add(LunchLedger(program_id=p.id,installment_id=b.id,kind='out',amount=7632));db.commit()
    assert claim_requests(db,2570)==[]
    db.query(LunchDisburseLink).delete();db.query(LunchLedger).delete();r.pay_mode='round';db.commit()
    assert len(claim_requests(db,2570))==1 and 'lunch_round=' in claim_requests(db,2570)[0]['href']

def test_paid_memos_are_read_in_bulk(db):
    from sqlalchemy import event
    a=FinanceAccount(name='ทดสอบ');db.add(a);db.flush()
    for n in range(40):
        m=DisburseMemo(fiscal_year=2570,amount=1000,account_id=a.id,status='จ่ายแล้ว');db.add(m);db.flush()
        db.add(FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=1000,disburse_id=m.id))
    db.commit();queries=[]
    def count(conn,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',count)
    try:data=overview(db,2570,[])
    finally:event.remove(db.bind,'before_cursor_execute',count)
    assert data['ready']==0 and all(s['code']=='paid' for s in data['statuses'].values())
    assert len(queries)<15

def test_finance_dashboard_capture_and_all_tools_accessible(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        accounts=[FinanceAccount(name=name) for name in ['เงินอุดหนุนรายหัว','รายได้สถานศึกษา','เงินอาหารกลางวัน']]
        s.add_all(accounts);s.flush()
        for a,income in zip(accounts,[150000,50000,50000]):
            s.add(FinanceTxn(account_id=a.id,fiscal_year=2570,kind='in',amount=income,date=datetime(2026,11,1)))
        s.add_all([FinanceTxn(account_id=accounts[1].id,fiscal_year=2570,kind='out',amount=15000,date=datetime(2026,11,2)),
            FinanceTxn(account_id=accounts[2].id,fiscal_year=2570,kind='out',amount=33500,date=datetime(2026,11,2))])
        for n,amount in [(122,3500),(123,7000),(124,4000)]:
            s.add(DisburseMemo(fiscal_year=2570,memo_no=f'{n}/2570',date=datetime(2026,11,12),amount=amount,account_id=accounts[1].id,status='อนุมัติ',subject={122:'ค่าซ่อมเครื่องพิมพ์',123:'ค่าตอบแทนวิทยากร',124:'ค่าใช้จ่ายจัดกิจกรรม'}[n]))
        paid=DisburseMemo(fiscal_year=2570,memo_no='120/2570',date=datetime(2026,11,10),amount=4000,account_id=accounts[2].id,status='จ่ายแล้ว',subject='ค่าวัสดุสำนักงาน');s.add(paid);s.flush()
        s.add(FinanceTxn(account_id=accounts[2].id,fiscal_year=2570,kind='out',amount=4000,disburse_id=paid.id,date=datetime(2026,11,10)))
        s.add(DisburseMemo(fiscal_year=2569,memo_no='999/2569',subject='OLD_YEAR_HIDDEN',amount=500,status='อนุมัติ'))
        s.add(MoneyLoan(fiscal_year=2570,contract_no='1/2570',borrower='ครูตัวอย่าง',amount=5000,due_date=datetime.combine(thai_today()-timedelta(days=5),datetime.min.time())))
        for title in ['ซื้อวัสดุจัดกิจกรรม','จ้างซ่อมเครื่องใช้สำนักงาน']:
            s.add(Procurement(fiscal_year=2570,subject=title,status='ตรวจรับแล้ว',total_amount=1000))
        s.commit()
    page=env.get('/finance?year=2570');assert page.status_code==200
    assert '197,500.00' in page.text and '250,000.00' in page.text and '52,500.00' in page.text
    assert 'OLD_YEAR_HIDDEN' not in page.text
    assert 'id="fd-all-tools"' in page.text and 'id="fd-year-tools"' in page.text
    assert 'id="setup-fin"' in page.text and 'ข้ามขั้นตอนนี้' in page.text
    assert 'พร้อมลงบัญชีให้อัตโนมัติ' not in page.text
    for path in ['/finance/withholding?year=2570','/finance/subsidy','/finance/import','/finance/receipts','/finance/quarter','/finance/audit','/finance/checks','/finance/revenue','/finance/projects']:
        assert path in page.text
    out=Path(os.environ['FINANCE_DASH_CAPTURE']);(out/'dashboard.html').write_text(page.text,encoding='utf-8')
    assert env.get('/finance?year=99999').status_code==400

def test_empty_dashboard_keeps_onboarding_and_empty_states(env):
    page=env.get('/finance?year=2570');assert page.status_code==200
    assert 'ยังไม่มีบัญชีเงิน' in page.text and 'ไม่มีงานค้างในกลุ่มที่ติดตาม' in page.text
    assert 'id="fd-ready"' in page.text
    (Path(os.environ['FINANCE_DASH_CAPTURE'])/'dashboard-empty.html').write_text(page.text,encoding='utf-8')
