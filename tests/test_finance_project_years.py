from tests.test_subsidy import env
from app.models import Project, Procurement, DisburseMemo, FinanceAccount, AccountItem


def test_previous_year_disbursement_and_project_options(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        old=Project(name='โครงการเก่าปิดแล้ว',plan_year=2569,active=False)
        new=Project(name='โครงการใหม่',plan_year=2570,active=True)
        legacy=Project(name='โครงการไม่ระบุปี',active=True)
        db.add_all([old,new,legacy]);db.flush()
        proc=Procurement(subject='ซื้อของปีเก่า',fiscal_year=2569,project_id=old.id,total_amount=100)
        account=FinanceAccount(name='บัญชีทดสอบ');db.add_all([proc,account]);db.flush()
        item=AccountItem(account_id=account.id,fiscal_year=2569,name='หมวดเก่า')
        db.add(item);db.commit();pid,procid,aid,iid=old.id,proc.id,account.id,item.id
    page=env.get('/finance/disburse?year=2569')
    assert page.status_code==200
    assert 'name="fiscal_year" value="2569"' in page.text
    assert 'ซื้อของปีเก่า' in page.text and 'โครงการเก่าปิดแล้ว' in page.text
    direct=env.get(f'/finance/disburse?proc={procid}')
    assert 'name="fiscal_year" value="2569"' in direct.text
    assert f'value="{pid}" selected' in direct.text
    assert env.get(f'/finance/disburse?year=2570&proc={procid}').status_code==400
    result=env.post('/finance/disburse',data=dict(fiscal_year='2569',subject='เบิกย้อนหลัง',project_id=pid,amount='100',account_id=aid,item_id=iid,procurement_id=procid),follow_redirects=False)
    assert result.status_code==303
    detail=env.get(result.headers['location'])
    assert f'value="{pid}" selected' in detail.text
    with tn.session_for(sid) as db:
        memo=db.query(DisburseMemo).filter_by(subject='เบิกย้อนหลัง').one()
        assert (memo.fiscal_year,memo.project_id,memo.item_id)==(2569,pid,iid)
    for year in [2569,2570]:
        ledger=env.get(f'/finance/accounts/{aid}?year={year}')
        assert all(name in ledger.text for name in ['โครงการเก่าปิดแล้ว','โครงการใหม่','โครงการไม่ระบุปี'])
