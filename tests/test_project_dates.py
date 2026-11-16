from datetime import datetime
from pathlib import Path
import os
from app import models as m
from app.services.project_activity import activity_groups
from tests.test_subsidy import db,env


def sample(db):
    project=m.Project(name='โครงการพัฒนาครูและบุคลากร',budget=10000,plan_year=2569)
    account=m.FinanceAccount(name='เงินอุดหนุน',deposit_type='bank')
    db.add_all([project,account]);db.flush()
    proc=m.Procurement(project_id=project.id,fiscal_year=2570,proc_type='จ้าง',subject='รถเดินทาง',
        request_date=datetime(2026,10,5),order_date=datetime(2026,11,3),total_amount=3100,status='อนุมัติ')
    db.add(proc);db.flush()
    memo=m.DisburseMemo(project_id=project.id,procurement_id=proc.id,fiscal_year=2570,amount=3100,
        date=datetime(2026,10,5),subject='จ้างรถเดินทาง',account_id=account.id,status='จ่ายแล้ว')
    other=m.DisburseMemo(project_id=project.id,fiscal_year=2570,amount=2100,proc_kind='ค่าใช้จ่ายอื่น',
        date=datetime(2026,10,5),subject='ค่าอาหารว่าง',account_id=account.id,status='จ่ายแล้ว')
    db.add_all([memo,other]);db.flush()
    payment=m.FinanceTxn(account_id=account.id,disburse_id=memo.id,fiscal_year=2570,kind='out',
        date=datetime(2026,10,5),amount=3100,note='จ้างรถเดินทาง',ref='218/2569')
    second=m.FinanceTxn(account_id=account.id,disburse_id=other.id,fiscal_year=2570,kind='out',
        date=datetime(2026,11,2),amount=2100,note='ค่าอาหารว่าง',ref='229/2569')
    db.add_all([payment,second]);db.commit()
    return project,account,proc,memo,other,payment,second


def test_project_follows_actual_ledger_dates_without_rewriting_document_or_money(db):
    project,account,proc,memo,other,payment,second=sample(db)
    groups=activity_groups(db,project,[proc],[other]);docs=groups[0]['docs']
    assert 'พ.ย.' in docs[0]['date'] and 'ต.ค.' in docs[0]['payments'][0]['date']
    assert 'ต.ค.' in docs[1]['date'] and 'พ.ย.' in docs[1]['payments'][0]['date']
    assert docs[0]['payments'][0]['url'].endswith(f'#t{payment.id}')
    assert docs[1]['payments'][0]['url'].endswith(f'#t{second.id}')
    assert groups[0]['used']==5200
    second.date=datetime(2026,11,7);db.commit()
    updated=activity_groups(db,project,[proc],[other])[0]['docs'][1]
    assert updated['payments'][0]['date'].startswith('7 ') and updated['date'].startswith('5 ')
    assert db.query(m.FinanceTxn).count()==2 and second.amount==2100


def test_identical_text_project_or_reference_does_not_fake_a_payment_link(db):
    project,account,proc,memo,other,payment,second=sample(db)
    payment.disburse_id=None;payment.project_id=project.id;db.commit()
    docs=activity_groups(db,project,[proc],[other])[0]['docs']
    assert docs[0]['payments']==[]
    assert len(docs[1]['payments'])==1


def test_split_and_lunch_paths_deduplicate_same_cash_entry(db):
    project,account,proc,memo,other,payment,second=sample(db)
    db.add(m.LunchLedger(program_id=1,procurement_id=proc.id,finance_txn_id=payment.id))
    extra=m.FinanceTxn(account_id=account.id,disburse_id=memo.id,fiscal_year=2570,kind='out',
        amount=500,date=datetime(2026,10,6))
    db.add(extra);db.commit()
    payments=activity_groups(db,project,[proc],[other])[0]['docs'][0]['payments']
    assert {x['id'] for x in payments}=={payment.id,extra.id}


def test_http_dates_match_between_project_and_cash_history(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        project,account,proc,memo,other,payment,second=sample(db)
        r=env.get(f'/projects/{project.id}');assert r.status_code==200,r.text[:200]
        assert 'วันที่เอกสาร' in r.text and 'วันที่จ่ายเงินจริง' in r.text
        assert f'/finance/accounts/{account.id}?year=2570#t{payment.id}' in r.text
        assert f'/finance/accounts/{account.id}?year=2570#t{second.id}' in r.text
        out=Path(os.environ['PROJECT_DATES_CAPTURE'])
        (out/'project.html').write_text(r.text,encoding='utf-8')
        r=env.get(f'/finance/accounts/{account.id}?year=2570');assert r.status_code==200
        assert 'วันที่รับ/จ่ายเงินจริง' in r.text
        (out/'ledger.html').write_text(r.text,encoding='utf-8')
    finally:db.close()
