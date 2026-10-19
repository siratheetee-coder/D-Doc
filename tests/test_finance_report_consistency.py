from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import FinanceAccount, FinanceTxn, AccountOpening, AccountItem
from app.services.ebudget import build
from app.services.asset_utils import account_balance_year, account_balance_asof
from app.routers.finance import _build_cash_rows, _book_balance, _cashbook_fund_data

@pytest.fixture
def ledger():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a = FinanceAccount(name='เงินรายได้สถานศึกษา', fund_type='เงินนอกงบประมาณ', deposit_type='bank', opening_balance=99999)
        db.add(a); db.flush()
        db.add(AccountOpening(account_id=a.id, fiscal_year=2570, amount=1000))
        item = AccountItem(account_id=a.id, fiscal_year=2570, name='ค่าหนังสือเรียน', opening_balance=300, deposit_type='bank')
        db.add(item); db.flush()
        for day, kind, amount, fy in [
            (datetime(2026,10,1), 'in', 200,2570),
            (datetime(2027,3,31,23,59), 'out', 50,2570),
            (datetime(2027,4,1), 'in', 100,2570),
            (datetime(2027,9,30,23,59), 'out', 25,2570),
            (datetime(2026,9,30), 'out', 999,2569)]:
            db.add(FinanceTxn(account_id=a.id,item_id=item.id,fiscal_year=fy,date=day,kind=kind,amount=amount))
        db.commit()
        yield db,a
    engine.dispose()

@pytest.mark.parametrize('rnd,cutoff,expected', [(1,datetime(2027,3,31),1150),(2,datetime(2027,9,30),1225)])
def test_period_closing_matches_daily_and_reconciliation(ledger,rnd,cutoff,expected):
    db,a=ledger
    report=build(db,2570,rnd)
    assert report['totals']['closing']==expected
    assert report['check']==0
    assert account_balance_asof(a,2570,cutoff)==expected
    assert _book_balance(db,2570,a.id,cutoff)==expected
    rows,totals=_build_cash_rows([a],2570,cutoff)
    assert totals['total']==expected
    assert totals['bank']==expected
    assert report['n_in_period']==2
    if rnd==2:
        assert report['totals']['opening']==build(db,2570,1)['totals']['closing']
        assert account_balance_year(a,2570)==expected
        _,opening,receipts,payments=_cashbook_fund_data(db,2570)
        assert sum(opening.values())+sum(r['amount'] for r in receipts)-sum(r['amount'] for r in payments)==expected

def test_undated_legacy_transaction_is_not_counted_as_new_in_both_rounds(ledger):
    db,a=ledger
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,date=None,kind='out',amount=10)
    db.add(t);db.commit()
    t.date=None;db.commit()
    first,second=build(db,2570,1),build(db,2570,2)
    assert first['totals']['closing']==second['totals']['opening']
    assert first['totals']['expense']==60
    assert second['totals']['expense']==25
    assert second['totals']['closing']==account_balance_year(a,2570)
    assert first['undated']==second['undated']==[t.id]


def test_fill_page_includes_last_day_transactions(ledger, monkeypatch):
    from app.routers import finance
    db,a=ledger
    monkeypatch.setattr(finance.templates, 'TemplateResponse', lambda name, context: context)
    data=finance.ebudget_fill_page(None, db=db, year=2570, round=1, all=1)
    assert [r['t'].amount for r in data['rows']]==[200,50]
