from tests.test_subsidy import env, db
from app.models import FinanceAccount, FinanceTxn, DisburseMemo, Procurement, LunchLedger, LunchProgram
from app.services import disburse_payments as pay
import pytest


def seed(db):
    a=FinanceAccount(name='audit'); db.add(a); db.flush()
    p=Procurement(fiscal_year=2570, subject='test purchase', total_amount=1000); db.add(p); db.flush()
    m=DisburseMemo(fiscal_year=2570, account_id=a.id, procurement_id=p.id, amount=400)
    db.add(m); db.commit()
    return a,p,m


def test_partial_and_update_limit(db):
    a,p,m=seed(db)
    t=FinanceTxn(account_id=a.id, fiscal_year=2570, kind='out', amount=400, disburse_id=m.id)
    db.add(t); db.flush()
    m2=DisburseMemo(fiscal_year=2570, account_id=a.id, procurement_id=p.id, amount=600)
    db.add(m2); db.flush()
    pay.validate_new(db,m2)
    m2.amount=601
    with pytest.raises(ValueError): pay.validate_new(db,m2)
    m.amount=1000
    pay.validate_new(db,m,excluding=t.id)
    m.amount=float('nan')
    with pytest.raises(ValueError): pay.validate_new(db,m,excluding=t.id)


def test_lunch_counted_once_and_no_second_post(db):
    a,p,m=seed(db)
    prog=LunchProgram(year=2570);db.add(prog);db.flush()
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=400,disburse_id=m.id)
    db.add(t);db.flush()
    db.add(LunchLedger(program_id=prog.id,procurement_id=p.id,finance_txn_id=t.id,kind='out',amount=400));db.flush()
    assert pay.summary(db,m)['paid']==400
    with pytest.raises(ValueError):pay.validate_new(db,m)


def test_link_and_delete_preserve_original(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a,p,m=seed(db)
        t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=400,note='original',ref='manual')
        db.add(t);db.commit();mid,tid,aid=m.id,t.id,a.id
    url=f'/finance/disburse/{mid}'
    assert 'เคยบันทึกจ่ายเงินไว้แล้ว' in env.get(url).text
    assert 'linked=1' in env.post(url+'/link-payment',data={'txn_id':tid},follow_redirects=False).headers['location']
    with tn.session_for(sid) as db:
        t=db.get(FinanceTxn,tid);assert t.linked_existing and t.disburse_id==mid
    # Repeated linking never creates another payment.
    assert 'payment_message=' in env.post(url+'/link-payment',data={'txn_id':tid},follow_redirects=False).headers['location']
    result=env.post(url+'/update',data={'account_id':aid,'amount':500},follow_redirects=False)
    assert 'payment_message=' in result.headers['location']
    with tn.session_for(sid) as db:
        assert db.get(FinanceTxn,tid).amount==400
        assert db.get(DisburseMemo,mid).amount==400
    env.post(url+'/unlink-payment')
    with tn.session_for(sid) as db:
        assert db.get(FinanceTxn,tid).disburse_id is None
    env.post(url+'/link-payment',data={'txn_id':tid})
    env.post(url+'/delete')
    with tn.session_for(sid) as db:
        t=db.get(FinanceTxn,tid)
        assert t and t.disburse_id is None and t.ref=='manual' and t.note=='original'


def test_second_memo_cannot_overpay(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a,p,m=seed(db);mid=m.id
        other=DisburseMemo(fiscal_year=2570,account_id=a.id,procurement_id=p.id,amount=700)
        db.add(other);db.commit();oid=other.id
    env.post(f'/finance/disburse/{mid}/post')
    result=env.post(f'/finance/disburse/{oid}/post',follow_redirects=False)
    assert 'payment_message=' in result.headers['location']
    with tn.session_for(sid) as db:
        assert not db.query(FinanceTxn).filter_by(disburse_id=oid).first()


def test_wrong_account_year_amount_or_existing_link_rejected(db):
    a,p,m=seed(db)
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=400)
    db.add(t);db.flush()
    assert pay.compatible(db,m,t)
    for field,value in [('account_id',a.id+1),('fiscal_year',2569),('amount',401),('kind','in'),('disburse_id',m.id),('item_id',999)]:
        old=getattr(t,field);setattr(t,field,value)
        assert not pay.compatible(db,m,t)
        setattr(t,field,old)



def test_lunch_source_changes_release_link(db):
    from app.routers.lunch import _mirror_finance, _unmirror_finance
    a,p,m=seed(db)
    prog=LunchProgram(year=2570,finance_account_id=a.id);db.add(prog);db.flush()
    led=LunchLedger(program_id=prog.id,procurement_id=p.id,kind='out',amount=400)
    db.add(led);db.flush();_mirror_finance(db,led)
    t=db.get(FinanceTxn,led.finance_txn_id)
    t.disburse_id=m.id;t.linked_existing=True;m.status='จ่ายแล้ว';db.flush()
    led.amount=500;_mirror_finance(db,led)
    assert t.disburse_id is None and m.status=='อนุมัติ'
    t.disburse_id=m.id;t.linked_existing=True;m.status='จ่ายแล้ว';db.flush()
    _unmirror_finance(db,led);db.flush()
    assert m.status=='อนุมัติ' and led.finance_txn_id is None


def test_schema_upgrade_preserves_old_transactions():
    from sqlalchemy import create_engine
    from app.database import run_migrations
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE finance_txn (id INTEGER PRIMARY KEY, amount FLOAT)')
        conn.exec_driver_sql('INSERT INTO finance_txn (id,amount) VALUES (1,250)')
    run_migrations(engine)
    run_migrations(engine)
    with engine.connect() as conn:
        assert tuple(conn.exec_driver_sql('SELECT amount, linked_existing FROM finance_txn').one()) == (250,0)
    engine.dispose()
