from tests.test_subsidy import db, env
from app.models import FinanceAccount, FinanceTxn, CheckPayment
from app.services.check_money import eligible
from datetime import datetime


def seed(db):
    a=FinanceAccount(name='check-bank');db.add(a);db.flush()
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,date=datetime(2026,10,20),kind='out',amount=500)
    c=CheckPayment(account_id=a.id,fiscal_year=2570,date=datetime(2026,10,20),amount=500,pay_method='เช็ค')
    db.add_all([t,c]);db.commit();return a,t,c


def test_link_matching_and_no_reuse(db):
    a,t,c=seed(db)
    assert eligible(db,c,t)
    c.date=datetime(2026,10,21)
    assert not eligible(db,c,t)
    c.date=t.date
    other=CheckPayment(account_id=a.id,fiscal_year=2570,date=t.date,amount=500,txn_id=t.id)
    db.add(other);db.flush()
    assert not eligible(db,c,t)


def test_historical_outstanding_and_cash(db):
    from app.routers.finance import _outstanding_checks
    a,t,c=seed(db)
    assert not _outstanding_checks(db,2570,a.id,datetime(2026,10,19))[0]
    assert len(_outstanding_checks(db,2570,a.id,datetime(2026,10,20))[0])==1
    c.cleared=True;c.cleared_date=datetime(2026,10,23);db.flush()
    assert len(_outstanding_checks(db,2570,a.id,datetime(2026,10,22))[0])==1
    assert not _outstanding_checks(db,2570,a.id,datetime(2026,10,23))[0]
    c.cleared=False;c.pay_method='เงินสด';db.flush()
    assert not _outstanding_checks(db,2570,a.id,datetime(2026,10,22))[0]


def test_link_toggle_and_delete_preserve_money(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a,t,c=seed(db);tid,cid=t.id,c.id
    assert env.get('/finance/checks?year=2570').status_code==200
    for _ in range(2):assert env.post(f'/finance/checks/{cid}/link',data={'txn_id':tid}).status_code==200
    env.post(f'/finance/checks/{cid}/toggle',data={'cleared_date':'23/10/2569'})
    env.post(f'/finance/txn/{tid}/delete')
    with tn.session_for(sid) as db:
        assert db.get(FinanceTxn,tid).amount==500
        assert db.get(CheckPayment,cid).cleared
    env.post(f'/finance/checks/{cid}/delete')
    with tn.session_for(sid) as db:
        assert db.get(CheckPayment,cid) is None and db.get(FinanceTxn,tid)


def test_linked_disbursement_cannot_delete_money(env):
    import app.tenancy as tn
    from app.models import DisburseMemo
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a,t,c=seed(db)
        m=DisburseMemo(fiscal_year=2570,account_id=a.id,date=t.date,amount=500,status='จ่ายแล้ว')
        db.add(m);db.flush();t.disburse_id=m.id;c.txn_id=t.id;db.commit()
        mid,tid,aid=m.id,t.id,a.id
    response=env.post(f'/finance/disburse/{mid}/delete',follow_redirects=False)
    assert 'payment_message=' in response.headers['location']
    response=env.post(f'/finance/disburse/{mid}/update',data={'account_id':aid,'amount':600,'date':'20/10/2569'},follow_redirects=False)
    assert 'payment_message=' in response.headers['location']
    with tn.session_for(sid) as db:
        assert db.get(FinanceTxn,tid).amount==500 and db.get(DisburseMemo,mid)


def test_check_link_migration_keeps_old_data():
    from sqlalchemy import create_engine
    from app.database import run_migrations
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE check_payment (id INTEGER PRIMARY KEY, amount FLOAT)')
        conn.exec_driver_sql('INSERT INTO check_payment VALUES (1,50)')
    run_migrations(engine);run_migrations(engine)
    with engine.connect() as conn:
        assert tuple(conn.exec_driver_sql('SELECT amount,txn_id FROM check_payment').one())==(50,None)
    engine.dispose()
