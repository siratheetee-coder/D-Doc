from datetime import datetime
from pathlib import Path
import os
import pytest
from app import models as m
from app.services import payment_date_edit as edit
from tests.test_subsidy import db,env


def setup(db):
    a=m.FinanceAccount(name='เงินอุดหนุน',deposit_type='bank')
    p=m.Project(name='พัฒนาครูและบุคลากร',plan_year=2569,budget=2000)
    db.add_all([a,p]);db.flush()
    memo=m.DisburseMemo(fiscal_year=2570,project_id=p.id,memo_no='228/2569',subject='ค่าสถานที่',
        date=datetime(2026,10,5),amount=1000,account_id=a.id,status='จ่ายแล้ว',proc_kind='ค่าใช้จ่ายอื่น')
    db.add(memo);db.flush()
    t=m.FinanceTxn(account_id=a.id,disburse_id=memo.id,fiscal_year=2570,date=datetime(2026,10,12),
        amount=1000,kind='out',note='ค่าสถานที่',ref='228/2569')
    db.add(t);db.flush()
    receipt=m.Receipt(txn_id=t.id,account_id=a.id,fiscal_year=2570,date=t.date,amount=1000,kind='จ่าย',receipt_no='R1')
    db.add(receipt);db.commit()
    return a,p,memo,t,receipt


def test_changes_actual_date_and_receipt_only_and_projects_follow(db):
    a,p,memo,t,r=setup(db);memo.date=datetime(2026,10,9);db.commit()
    old_count=db.query(m.FinanceTxn).count()
    edit.save(db,memo,t,'05/10/2569',edit.token(db,t));db.commit()
    assert t.date==r.date==datetime(2026,10,5)
    assert memo.date==datetime(2026,10,9) and t.amount==memo.amount==r.amount==1000
    assert db.query(m.FinanceTxn).count()==old_count and t.disburse_id==memo.id
    from app.services.project_activity import activity_groups
    row=activity_groups(db,p,[],[memo])[0]['docs'][0]
    assert row['payments'][0]['date'].startswith('5 ') and row['date'].startswith('9 ')


@pytest.mark.parametrize('value',['','bad','05/10/2568','30/02/2569'])
def test_invalid_or_cross_year_dates_preserve_ledger(db,value):
    a,p,memo,t,r=setup(db)
    with pytest.raises(ValueError):edit.save(db,memo,t,value,edit.token(db,t))
    db.rollback();assert t.date==datetime(2026,10,12) and r.date==t.date


def test_stale_version_and_wrong_memo_cannot_modify_payment(db):
    a,p,memo,t,r=setup(db);old=edit.token(db,t);t.note='แก้จากอีกหน้าจอ';db.commit()
    with pytest.raises(ValueError,match='เปลี่ยนแปลง'):edit.save(db,memo,t,'05/10/2569',old)
    other=m.DisburseMemo(fiscal_year=2570);db.add(other);db.commit()
    with pytest.raises(ValueError,match='ไม่ได้เป็น'):edit.save(db,other,t,'05/10/2569',edit.token(db,t))
    assert t.date==datetime(2026,10,12)


@pytest.mark.parametrize('link',['lunch','check','certificate','memo_certificate','loan'])
def test_protected_sources_block_date_change(db,link):
    a,p,memo,t,r=setup(db)
    if link=='lunch':db.add(m.LunchLedger(program_id=1,finance_txn_id=t.id))
    if link=='check':db.add(m.CheckPayment(txn_id=t.id,fiscal_year=2570))
    if link=='certificate':db.add(m.WithholdingCertificate(txn_id=t.id))
    if link=='memo_certificate':db.add(m.WithholdingCertificate(memo_id=memo.id))
    if link=='loan':t.loan_id=1
    db.commit()
    with pytest.raises(ValueError):edit.save(db,memo,t,'05/10/2569',edit.token(db,t))
    assert t.date==datetime(2026,10,12)


def test_split_and_linked_existing_change_only_selected_payment(db):
    a,p,memo,t,r=setup(db);t.linked_existing=True
    other=m.FinanceTxn(account_id=a.id,disburse_id=memo.id,fiscal_year=2570,date=t.date,amount=200,kind='out')
    db.add(other);db.commit()
    edit.save(db,memo,t,'05/10/2569',edit.token(db,t));db.commit()
    assert t.linked_existing and t.disburse_id==memo.id
    assert other.date==datetime(2026,10,12) and other.amount==200


def test_http_original_228_date_changes_without_reposting(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p,memo,t,r=setup(db);mid,tid=memo.id,t.id
        response=env.get(f'/finance/disburse/{mid}');assert response.status_code==200
        assert 'แก้วันที่จ่ายจริง' in response.text and 'ใช้วันที่บันทึกขอเบิก 05/10/2569' in response.text
        out=Path(os.environ['PAY_DATE_CAPTURE']);(out/'before.html').write_text(response.text,encoding='utf-8')
        url=f'/finance/disburse/{mid}/payments/{tid}/date'
        response=env.post(url,data={'paid_date':'05/10/2569','version':edit.token(db,t)},follow_redirects=False)
        assert response.status_code==303 and 'payment_date_saved=1' in response.headers['location'],response.text
        response=env.get(response.headers['location']);assert response.status_code==200
        (out/'after.html').write_text(response.text,encoding='utf-8')
        db.expire_all();assert db.get(m.FinanceTxn,tid).date==datetime(2026,10,5)
        assert db.query(m.FinanceTxn).filter_by(disburse_id=mid).count()==1
        response=env.get(f'/projects/{p.id}');assert response.status_code==200
        assert f'#t{tid}' in response.text
        assert env.post(f'/finance/disburse/{mid}/payments/999999/date').status_code==404
    finally:db.close()
