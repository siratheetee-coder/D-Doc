from datetime import datetime
from pathlib import Path
import os
import pytest
from app import models as m
from app.services import procurement_claims as claims,disburse_payments as payments
from app.services.payment_relationship import settled_elsewhere
from tests.test_subsidy import db,env


def source(db):
    a=m.FinanceAccount(name='เงินอุดหนุน',deposit_type='bank')
    p=m.Procurement(fiscal_year=2570,proc_type='จ้าง',subject='รถเดินทาง โครงการพัฒนาครู',memo_no='218/2569',total_amount=3100)
    db.add_all([a,p]);db.commit();return a,p


def duplicate_case(db):
    a,p=source(db)
    owner=m.DisburseMemo(fiscal_year=2570,procurement_id=p.id,memo_no='218/2569',subject=p.subject,
        date=datetime(2026,10,5),amount=3100,account_id=a.id,status='จ่ายแล้ว')
    duplicate=m.DisburseMemo(fiscal_year=2570,procurement_id=p.id,memo_no='218/2569',subject=p.subject,
        date=datetime(2026,10,5),amount=3100,account_id=a.id,status='ร่าง')
    db.add_all([owner,duplicate]);db.flush()
    txn=m.FinanceTxn(account_id=a.id,fiscal_year=2570,disburse_id=owner.id,kind='out',amount=3100,date=datetime(2026,11,3),ref='218/2569')
    db.add(txn);db.commit();return a,p,owner,duplicate,txn


def test_real_double_claim_alert_stays_and_actual_payment_stays_single(db):
    a,p,owner,duplicate,txn=duplicate_case(db)
    data=claims.state(db,p)
    assert data['claimed']==6200 and data['resume'].id==owner.id
    related=settled_elsewhere(db,duplicate,payments.summary(db,duplicate))
    assert related['overclaimed'] and related['href']==f'/finance/disburse/{owner.id}#payment-records'
    from app.services.finance_health import memo_over_procurement
    assert memo_over_procurement(db,2570,datetime(2026,11,16)) is not None
    from app.services.finance_overview import memo_status
    assert memo_status(db,duplicate,False,[])['code']=='review'
    assert db.query(m.FinanceTxn).count()==1 and txn.amount==3100 and txn.disburse_id==owner.id


def test_partial_claims_reserve_drafts_and_allow_remaining_only(db):
    a,p=source(db)
    m1=m.DisburseMemo(fiscal_year=2570,procurement_id=p.id,amount=1000);db.add(m1);db.commit()
    assert claims.validate(db,p,2100)['remaining']==2100
    with pytest.raises(ValueError):claims.validate(db,p,2100.01)
    m2=m.DisburseMemo(fiscal_year=2570,procurement_id=p.id,amount=2100);db.add(m2);db.commit()
    db.add(m.FinanceTxn(account_id=a.id,fiscal_year=2570,disburse_id=m1.id,kind='out',amount=1000));db.commit()
    assert claims.state(db,p)['resume'].id==m2.id
    with pytest.raises(ValueError):claims.validate(db,p,1)


def test_related_overpayment_or_similar_title_does_not_claim_settled_state(db):
    a,p,owner,duplicate,txn=duplicate_case(db)
    txn.amount=3200;db.commit()
    assert settled_elsewhere(db,duplicate,payments.summary(db,duplicate)) is None
    txn.amount=3100;txn.disburse_id=None;db.commit()
    assert settled_elsewhere(db,duplicate,payments.summary(db,duplicate)) is None


def test_http_existing_paid_source_resumes_owner_and_preserves_duplicates_for_review(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p,owner,duplicate,txn=duplicate_case(db)
        response=env.get(f'/finance/disburse?proc={p.id}&year=2570',follow_redirects=False)
        assert response.status_code==303 and f'/finance/disburse/{owner.id}?' in response.headers['location']
        response=env.get(f'/finance/disburse/{duplicate.id}');assert response.status_code==200,response.text[:200]
        assert 'เรื่องนี้จ่ายครบแล้วจากบันทึกอื่น' in response.text
        assert 'ขอเบิกรวม 6,200.00' in response.text
        assert 'ยังไม่ได้บันทึกจ่ายเงินจริง</h2>' not in response.text
        assert f'action="/finance/disburse/{duplicate.id}/post"' not in response.text
        out=Path(os.environ['CLAIM_CAPTURE']);(out/'duplicate-detail.html').write_text(response.text,encoding='utf-8')
        response=env.post('/finance/disburse',data={'fiscal_year':'2570','procurement_id':str(p.id),'memo_no':'999/2569','amount':'3100','subject':p.subject},follow_redirects=False)
        assert response.status_code==303 and f'/finance/disburse/{owner.id}?' in response.headers['location']
        db.expire_all();assert db.query(m.DisburseMemo).filter_by(procurement_id=p.id).count()==2
        assert db.query(m.FinanceTxn).count()==1 and db.get(m.FinanceTxn,txn.id).disburse_id==owner.id
        response=env.get('/finance/health?year=2570');assert response.status_code==200 and 'ขอเบิกเกินยอดของเรื่องพัสดุ' in response.text
    finally:db.close()


def test_http_second_submit_resumes_first_and_partial_create_uses_remaining(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p=source(db)
        payload={'fiscal_year':'2570','procurement_id':str(p.id),'memo_no':'301/2569','amount':'1000','account_id':str(a.id),'subject':'งวดแรก','claim_version':claims.state(db,p)['version']}
        first=env.post('/finance/disburse',data=payload,follow_redirects=False);assert first.status_code==303,first.text
        repeated=env.post('/finance/disburse',data=payload,follow_redirects=False)
        assert repeated.status_code==303 and 'claim_changed=1' in repeated.headers['location']
        assert db.query(m.DisburseMemo).filter_by(procurement_id=p.id).count()==1
        payload['claim_version']=claims.state(db,p)['version']
        page=env.get(f'/finance/disburse?proc={p.id}&year=2570');assert page.status_code==200
        assert 'เหลือทำขอเบิก 2,100.00' in page.text
        invalid=env.post('/finance/disburse',data=dict(payload,memo_no='302/2569',amount='3100'),follow_redirects=False)
        assert invalid.status_code==409
        second=env.post('/finance/disburse',data=dict(payload,memo_no='302/2569',amount='2100'),follow_redirects=False)
        assert second.status_code==303,second.text
        again=env.post('/finance/disburse',data=dict(payload,memo_no='303/2569',amount='2100'),follow_redirects=False)
        assert again.status_code==303
        db.expire_all();assert db.query(m.DisburseMemo).filter_by(procurement_id=p.id).count()==2
        assert claims.state(db,p)['claimed']==3100 and db.query(m.FinanceTxn).count()==0
    finally:db.close()
