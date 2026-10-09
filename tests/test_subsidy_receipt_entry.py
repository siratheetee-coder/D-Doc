from tests.test_subsidy import env
from app.models import FinanceAccount, AccountItem, FinanceTxn


def test_prefill_receipt_and_return_to_same_term(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a=FinanceAccount(name='เงินอุดหนุนทดสอบ'); db.add(a); db.flush()
        i=AccountItem(account_id=a.id,fiscal_year=2570,name='ค่าจัดการเรียนการสอน',budget=0)
        db.add(i); db.commit(); aid,iid=a.id,i.id
    url=f'/finance/accounts/{aid}?year=2570&item={iid}&subsidy_year=2569&subsidy_term=2'
    page=env.get(url)
    assert page.status_code==200
    assert f'value="{iid}" selected' in page.text
    assert '/finance/subsidy?year=2569&term=2#sec-receipts' in page.text
    with tn.session_for(sid) as db:
        before=db.query(FinanceTxn).filter_by(account_id=aid).count()
    response=env.post(f'/finance/accounts/{aid}/txn',data=dict(kind='in',amount='700',fiscal_year='2570',item_id=str(iid),subsidy_year='2569',subsidy_term='2'),follow_redirects=False)
    assert response.status_code==303
    assert 'subsidy_year=2569&subsidy_term=2#txn-entry' in response.headers['location']
    assert 'กลับไปเชื่อมเงินอุดหนุน' in env.get(response.headers['location']).text
    with tn.session_for(sid) as db:
        assert db.query(FinanceTxn).filter_by(account_id=aid).count()==before+1
        txn=db.query(FinanceTxn).filter_by(account_id=aid).first()
        assert (txn.item_id,txn.amount,txn.kind,txn.fiscal_year)==(iid,700,'in',2570)
    invalid=env.get(f'/finance/accounts/{aid}?year=2570&item=999999&subsidy_year=2569&subsidy_term=9')
    assert 'กลับไปเชื่อมเงินอุดหนุน' not in invalid.text
    subsidy=env.get('/finance/subsidy?year=2569&term=2')
    assert subsidy.status_code==200
    assert 'id="receipt-empty"' in subsidy.text
    assert 'ยังไม่ได้เชื่อมรายการรับเงินกับเทอมนี้' in subsidy.text
