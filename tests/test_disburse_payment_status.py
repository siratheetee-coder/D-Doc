from tests.test_subsidy import env
from app.models import FinanceAccount, FinanceTxn, DisburseMemo


def test_payment_status_follows_ledger(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a = FinanceAccount(name='payment-test'); db.add(a); db.flush()
        m = DisburseMemo(fiscal_year=2570, memo_no='900/2570', account_id=a.id, amount=100, status='อนุมัติ')
        db.add(m); db.commit(); mid, aid = m.id, a.id
    url = f'/finance/disburse/{mid}'
    form = dict(memo_no='900/2570', amount='100', account_id=str(aid), status='จ่ายแล้ว')
    assert env.post(url+'/update', data=form).status_code == 200
    with tn.session_for(sid) as db:
        assert db.get(DisburseMemo, mid).status == 'อนุมัติ'
        assert not db.query(FinanceTxn).filter_by(disburse_id=mid).first()
    # Legacy inconsistent status must not hide the posting button.
    with tn.session_for(sid) as db:
        db.get(DisburseMemo, mid).status = 'จ่ายแล้ว'; db.commit()
    assert f'action="{url}/post"' in env.get(url).text
    for _ in range(2):
        assert env.post(url+'/post').status_code == 200
    with tn.session_for(sid) as db:
        rows = db.query(FinanceTxn).filter_by(disburse_id=mid).all()
        assert len(rows) == 1
        tid = rows[0].id
    form['status'] = 'ร่าง'
    env.post(url+'/update', data=form)
    with tn.session_for(sid) as db:
        assert db.get(DisburseMemo, mid).status == 'จ่ายแล้ว'
    env.post(f'/finance/txn/{tid}/delete')
    with tn.session_for(sid) as db:
        assert db.get(DisburseMemo, mid).status == 'อนุมัติ'
        assert db.get(FinanceTxn, tid) is None
    assert f'action="{url}/post"' in env.get(url).text


def test_post_without_account_does_not_report_success(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    with tn.session_for(sid) as db:
        m = DisburseMemo(fiscal_year=2570, amount=100, status='ร่าง')
        db.add(m); db.commit(); mid = m.id
    response = env.post(f'/finance/disburse/{mid}/post', follow_redirects=False)
    assert 'payment_error=account' in response.headers['location']
    with tn.session_for(sid) as db:
        assert db.get(DisburseMemo, mid).status == 'ร่าง'
        assert not db.query(FinanceTxn).filter_by(disburse_id=mid).first()
