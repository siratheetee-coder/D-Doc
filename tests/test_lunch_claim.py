from datetime import datetime
from pathlib import Path
import os,json,re
import pytest
from tests.test_subsidy import env
from tests.test_shared_school_calendar import setup
from app.models import (LunchHireRound,LunchInstallment,LunchLedger,LunchDisburseLink,
    DisburseMemo,FinanceTxn,FinanceAccount,AccountItem,Vendor)

def session():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))

def make(env,whole=False,ready=True):
    with session() as s:
        p,cls,r,a,b=setup(s)
        acc=FinanceAccount(name='เงินอาหารกลางวันทดสอบ');v=Vendor(name='ผู้รับจ้างทดสอบ');s.add_all([acc,v]);s.flush()
        p.finance_account_id=acc.id;r.vendor_id=v.id
        a.status='ตรวจรับแล้ว' if ready else 'ร่าง';b.status='ตรวจรับแล้ว'
        if whole:r.pay_mode='round'
        s.commit();return dict(pid=p.id,rid=r.id,iid=a.id,bid=b.id,aid=acc.id,
            amount=15264 if whole else 7632,source={'lunch_round':str(r.id)} if whole else {'lunch_inst':str(a.id)})

def create(env,x):
    response=env.post('/finance/disburse',data={**x['source'],'fiscal_year':'2570','memo_no':'121/2570',
        'date':'15/12/2570' if False else '15/12/2569','subject':'ค่าจ้างอาหารกลางวัน','payee':'ผู้รับจ้างทดสอบ',
        'amount':str(x['amount']),'wht':str(round(x['amount']*.01,2)),'fine':'0','account_id':str(x['aid'])},follow_redirects=False)
    assert response.status_code==303,response.text
    mid=int(re.search(r'/finance/disburse/(\d+)',response.headers['location']).group(1));return mid

@pytest.mark.parametrize('whole',[False,True])
def test_source_prefill_deduplicate_pay_and_cancel(env,whole):
    x=make(env,whole)
    query='&'.join(f'{k}={v}' for k,v in x['source'].items())
    page=env.get('/finance/disburse?'+query)
    assert page.status_code==200 and 'ผู้รับจ้างทดสอบ' in page.text and str(x['amount']) in page.text
    assert 'name="lunch_' in page.text and 'ยอดเงิน' in page.text
    mid=create(env,x)
    assert create(env,x)==mid
    redirect=env.get('/finance/disburse?'+query,follow_redirects=False)
    assert redirect.headers['location']==f'/finance/disburse/{mid}'
    with session() as s:
        assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==0
        assert s.query(LunchDisburseLink).count()==1
    page=env.get(f'/finance/disburse/{mid}');assert page.status_code==200 and 'วันที่จ่ายเงินจริง' in page.text
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'23/12/2569'})
    with session() as s:
        assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==1
        txn=s.query(FinanceTxn).one();ledger=s.query(LunchLedger).one()
        assert txn.id==ledger.finance_txn_id and txn.amount==ledger.amount==x['amount']
        assert txn.date==ledger.date==datetime(2026,12,22)
        assert s.get(DisburseMemo,mid).date==datetime(2026,12,15)
        assert (s.get(LunchHireRound,x['rid']).status if whole else s.get(LunchInstallment,x['iid']).status)=='จ่ายแล้ว'
    page=env.get(f'/lunch/round/{x["rid"]}/plan');assert page.status_code==200 and 'lf-flow' in page.text
    # A raw lunch status change/delete must not erase a finance-owned payment.
    env.post(f'/lunch/installment/{x["iid"]}/update',data={'status':'ร่าง'})
    env.post(f'/lunch/round/{x["rid"]}/delete')
    env.post(f'/finance/disburse/{mid}/delete')
    with session() as s:assert s.query(FinanceTxn).count()==1 and s.get(LunchHireRound,x['rid']) is not None
    response=env.post(f'/finance/disburse/{mid}/lunch-cancel-payment',follow_redirects=False);assert response.status_code==303
    with session() as s:
        assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==0
        assert s.get(DisburseMemo,mid) is not None
        assert (s.get(LunchHireRound,x['rid']).status if whole else s.get(LunchInstallment,x['iid']).status)==('จ้างแล้ว' if whole else 'ตรวจรับแล้ว')

def test_legacy_paid_links_exact_original_without_second_payment(env):
    x=make(env)
    env.post(f'/lunch/installment/{x["iid"]}/update',data={'status':'จ่ายแล้ว'})
    with session() as s:tid=s.query(FinanceTxn).one().id
    mid=create(env,x)
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:assert s.query(FinanceTxn).count()==1 and s.query(FinanceTxn).one().disburse_id is None
    env.post(f'/finance/disburse/{mid}/link-payment',data={'txn_id':str(tid)})
    with session() as s:
        t=s.get(FinanceTxn,tid);assert t.disburse_id==mid and t.linked_existing
        assert s.query(LunchLedger).one().finance_txn_id==tid
    env.post(f'/finance/disburse/{mid}/unlink-payment')
    with session() as s:
        assert s.query(FinanceTxn).count()==1 and s.get(FinanceTxn,tid).disburse_id is None
        assert s.get(LunchInstallment,x['iid']).status=='จ่ายแล้ว'

def test_block_wrong_source_stale_snapshot_and_refresh(env):
    x=make(env,ready=False)
    assert env.get('/finance/disburse?lunch_inst='+str(x['iid'])).status_code==400
    assert env.get('/finance/disburse?lunch_inst=999999').status_code==404
    assert env.get('/finance/disburse?lunch_inst='+str(x['iid'])+'&proc=1').status_code==400
    with session() as s:s.get(LunchInstallment,x['iid']).status='ตรวจรับแล้ว';s.commit()
    mid=create(env,x)
    with session() as s:s.get(LunchInstallment,x['iid']).amount=7000;s.commit()
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:assert s.query(FinanceTxn).count()==0
    page=env.get(f'/finance/disburse/{mid}');assert 'ปรับข้อมูลจากงวดล่าสุด' in page.text
    env.post(f'/finance/disburse/{mid}/lunch-refresh')
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:assert s.query(FinanceTxn).one().amount==7000

@pytest.mark.parametrize('date',['','bad','22/09/2569'])
def test_payment_date_required_and_same_fiscal_year(env,date):
    x=make(env);mid=create(env,x)
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':date})
    with session() as s:assert s.query(FinanceTxn).count()==0

def test_other_installment_ledger_not_candidate_and_wrong_amount_rejected(env):
    x=make(env);mid=create(env,x)
    env.post(f'/lunch/installment/{x["bid"]}/update',data={'status':'จ่ายแล้ว'})
    with session() as s:tid=s.query(FinanceTxn).one().id
    env.post(f'/finance/disburse/{mid}/link-payment',data={'txn_id':str(tid)})
    with session() as s:assert s.get(FinanceTxn,tid).disburse_id is None

def test_capture_flow_and_finance(env):
    x=make(env)
    out=Path(os.environ['LUNCH_FLOW_CAPTURE'])
    response=env.get('/finance/disburse?lunch_inst='+str(x['iid']));assert response.status_code==200
    (out/'finance-source.html').write_text(response.text,encoding='utf-8')
    mid=create(env,x)
    with session() as s:
        s.get(LunchInstallment,x['bid']).status='ส่งมอบแล้ว'
        s.add(LunchInstallment(round_id=x['rid'],seq=3,start_date=datetime(2026,12,21),end_date=datetime(2026,12,23),days=3,amount=7632,status='ร่าง'))
        s.commit()
    for name,url in [('lunch',f'/lunch/round/{x["rid"]}/plan'),('finance',f'/finance/disburse/{mid}')]:
        response=env.get(url);assert response.status_code==200
        (out/f'{name}.html').write_text(response.text,encoding='utf-8')
    (out/'ids.json').write_text(json.dumps(x|{'mid':mid}),encoding='utf-8')

def test_approval_gate_and_refresh_invalidates_prior_approval(env):
    from app.models import School,Approval
    from app.services import approval
    x=make(env);mid=create(env,x)
    with session() as s:
        s.query(School).first().approval_on=True;s.commit()
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:
        assert s.query(FinanceTxn).count()==0
        m=s.get(DisburseMemo,mid)
        a=approval.send(s,'disburse',mid,'ผู้ส่งทดสอบ');a.status='approved';s.commit()
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:assert s.query(FinanceTxn).count()==1
    env.post(f'/finance/disburse/{mid}/lunch-cancel-payment')
    with session() as s:
        i=s.get(LunchInstallment,x['iid']);i.calendar_dates='["2026-12-11","2026-12-14","2026-12-16"]';s.commit()
    env.post(f'/finance/disburse/{mid}/lunch-refresh')
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:
        assert s.query(FinanceTxn).count()==0
        assert not approval.approved_for(s,'disburse',mid,s.get(DisburseMemo,mid))

def test_flow_step_validates_sequence_and_inspection_date(env):
    x=make(env,ready=False)
    url=f'/lunch/installment/{x["iid"]}/update'
    head={'X-Requested-With':'fetch'}
    response=env.post(url,data={'flow_action':'1','status':'ตรวจรับแล้ว'},headers=head)
    assert response.status_code==400
    response=env.post(url,data={'flow_action':'1','status':'ส่งมอบแล้ว','deliver_date':'15/12/2569'},headers=head)
    assert response.status_code==200
    response=env.post(url,data={'flow_action':'1','status':'ตรวจรับแล้ว','inspect_date':'14/12/2569'},headers=head)
    assert response.status_code==400
    response=env.post(url,data={'flow_action':'1','status':'ตรวจรับแล้ว','inspect_date':'15/12/2569'},headers=head)
    assert response.status_code==200
    with session() as s:assert s.get(LunchInstallment,x['iid']).status=='ตรวจรับแล้ว'

def test_paid_source_cannot_be_deleted_from_lunch_ledger_or_program(env):
    x=make(env);mid=create(env,x)
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:lid=s.query(LunchLedger).one().id
    env.post(f'/lunch/ledger/{lid}/delete');env.post(f'/lunch/{x["pid"]}/delete')
    with session() as s:assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==1

def test_known_legacy_memo_is_reopened_without_duplicate(env):
    x=make(env)
    env.post(f'/lunch/installment/{x["iid"]}/update',data={'status':'จ่ายแล้ว'})
    with session() as s:
        m=DisburseMemo(fiscal_year=2570,amount=7632,account_id=x['aid'],subject='บันทึกเดิม');s.add(m);s.flush()
        s.query(FinanceTxn).one().disburse_id=m.id;s.commit();mid=m.id
    response=env.get('/finance/disburse?lunch_inst='+str(x['iid']),follow_redirects=False)
    assert response.headers['location']==f'/finance/disburse/{mid}'
    assert create(env,x)==mid
    with session() as s:assert s.query(DisburseMemo).count()==1

def test_lunch_only_staff_sees_handoff_message_and_cannot_open_finance(env,monkeypatch):
    import app.main as main
    x=make(env);base=main.get_account_access(1)
    monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'modules':'lunch','person_id':123})
    page=env.get(f'/lunch/round/{x["rid"]}/plan');assert page.status_code==200
    assert 'รอเจ้าหน้าที่การเงินทำเรื่องขอเบิก' in page.text
    assert env.get('/finance/disburse?lunch_inst='+str(x['iid'])).status_code==403

def test_paid_memo_editor_preserves_actual_payment_and_rejects_amount_changes(env):
    x=make(env);mid=create(env,x)
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    form={'memo_no':'121/2570','date':'15/12/2569','subject':'ค่าจ้างอาหารกลางวัน','payee':'ผู้รับจ้างทดสอบ',
        'amount':'7632','wht':'76.32','fine':'0','account_id':str(x['aid']),'note':'บันทึกเพิ่มเติม'}
    env.post(f'/finance/disburse/{mid}/update',data={**form,'amount':'9999'})
    with session() as s:assert s.get(DisburseMemo,mid).amount==7632 and s.query(FinanceTxn).one().amount==7632
    env.post(f'/finance/disburse/{mid}/update',data=form)
    with session() as s:
        assert s.query(FinanceTxn).one().date==datetime(2026,12,22)
        assert s.get(DisburseMemo,mid).note=='บันทึกเพิ่มเติม'

def test_link_explicit_manual_payment_creates_only_lunch_view(env):
    x=make(env);mid=create(env,x)
    with session() as s:
        t=FinanceTxn(account_id=x['aid'],fiscal_year=2570,kind='out',amount=7632,date=datetime(2026,12,22));s.add(t);s.commit();tid=t.id
    env.post(f'/finance/disburse/{mid}/link-payment',data={'txn_id':str(tid)})
    with session() as s:
        assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==1
        assert s.query(LunchLedger).one().finance_txn_id==tid
        assert s.get(LunchInstallment,x['iid']).status=='จ่ายแล้ว'

def test_bound_receipt_prevents_payment_cancellation(env):
    from app.models import Receipt
    x=make(env);mid=create(env,x)
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    with session() as s:s.add(Receipt(txn_id=s.query(FinanceTxn).one().id,fiscal_year=2570));s.commit()
    env.post(f'/finance/disburse/{mid}/lunch-cancel-payment')
    with session() as s:assert s.query(FinanceTxn).count()==s.query(LunchLedger).count()==1
