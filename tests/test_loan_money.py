from tests.test_subsidy import db, env
from app.models import FinanceAccount, FinanceTxn, MoneyLoan, LoanReturn
from app.services import loan_money as lm
from datetime import datetime
import pytest


def seed(db):
    a=FinanceAccount(name='loan account');db.add(a);db.flush()
    l=MoneyLoan(fiscal_year=2570,amount=1000,receive_date=datetime(2026,10,20),account_id=a.id)
    db.add(l);db.commit()
    return a,l


def test_cash_and_voucher_no_double_expense(db):
    a,l=seed(db)
    t=lm.record(db,l.id,0,'new',a.id);db.commit()
    assert lm.record(db,l.id,0,'new',a.id).id==t.id
    ret=LoanReturn(loan_id=l.id,kind='เงินสด',amount=200,date=datetime(2027,10,1))
    voucher=LoanReturn(loan_id=l.id,kind='ใบสำคัญ',amount=800,date=datetime(2026,10,21))
    db.add_all([ret,voucher]);db.commit()
    incoming=lm.record(db,l.id,ret.id,'new',a.id);db.commit()
    assert incoming.kind=='in' and incoming.fiscal_year==2571
    with pytest.raises(ValueError):lm.record(db,l.id,voucher.id,'new',a.id)
    assert sum(x.amount if x.kind=='out' else -x.amount for x in db.query(FinanceTxn))==800


def test_existing_link_and_unlink_keep_money(db):
    a,l=seed(db)
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=1000,ref='old')
    db.add(t);db.commit()
    lm.record(db,l.id,0,'link',a.id,txn_id=t.id);db.commit()
    assert db.query(FinanceTxn).count()==1
    lm.unlink(db,l.id,0);db.commit()
    assert t.loan_id is None and t.ref=='old' and t.amount==1000


def test_cannot_link_wrong_or_disbursement_txn(db):
    a,l=seed(db)
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=999)
    db.add(t);db.commit()
    with pytest.raises(ValueError):lm.record(db,l.id,0,'link',a.id,txn_id=t.id)
    t.amount=1000;t.disburse_id=99;db.flush()
    with pytest.raises(ValueError):lm.record(db,l.id,0,'link',a.id,txn_id=t.id)


def test_loan_page_and_delete_protection(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a,l=seed(db);aid,lid=a.id,l.id
    url=f'/finance/loans/{lid}/money'
    assert env.get(url).status_code==200
    for _ in range(2):
        assert env.post(url+'/0',data={'mode':'new','account_id':aid}).status_code==200
    with tn.session_for(sid) as db:
        rows=db.query(FinanceTxn).filter_by(loan_id=lid).all();assert len(rows)==1;tid=rows[0].id
    env.post(f'/finance/loans/{lid}/delete')
    env.post(f'/finance/txn/{tid}/delete')
    with tn.session_for(sid) as db:
        assert db.get(MoneyLoan,lid) and db.get(FinanceTxn,tid)
    result=env.post(f'/finance/loans/{lid}/return',data={'kind':'เงินสด','date':'21/10/2569','amount':'1001'})
    assert 'ยอดส่งใช้รวมเกิน' in result.text
    env.post(url+'/0',data={'mode':'unlink'})
    env.post(f'/finance/loans/{lid}/delete')
    with tn.session_for(sid) as db:
        assert db.get(MoneyLoan,lid) is None and db.get(FinanceTxn,tid)


def test_old_schema_and_cash_before_payout(db):
    from sqlalchemy import create_engine
    from app.database import run_migrations
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE finance_txn (id INTEGER PRIMARY KEY, amount FLOAT)')
        conn.exec_driver_sql('INSERT INTO finance_txn VALUES (1,125)')
    run_migrations(engine);run_migrations(engine)
    with engine.connect() as conn:
        assert tuple(conn.exec_driver_sql('SELECT amount,loan_id,loan_return_id FROM finance_txn').one())==(125,None,None)
    engine.dispose()
    a,l=seed(db)
    ret=LoanReturn(loan_id=l.id,kind='เงินสด',amount=100,date=datetime(2026,10,21));db.add(ret);db.commit()
    with pytest.raises(ValueError):lm.record(db,l.id,ret.id,'new',a.id)
    lm.record(db,l.id,0,'new',a.id);db.commit()
    lm.record(db,l.id,ret.id,'new',a.id);db.commit()
    with pytest.raises(ValueError):lm.unlink(db,l.id,0)
    lm.unlink(db,l.id,ret.id);lm.unlink(db,l.id,0);db.commit()
    assert db.query(FinanceTxn).count()==2
