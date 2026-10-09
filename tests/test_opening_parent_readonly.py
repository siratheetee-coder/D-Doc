from tests.test_subsidy import db, env
from app.models import FinanceAccount, AccountItem
from app.services.finance_openings import save, token


def test_parent_value_is_preserved_not_overwritten_by_display_total(db):
    a=FinanceAccount(name='test');db.add(a);db.flush()
    p=AccountItem(account_id=a.id,fiscal_year=2570,name='parent',opening_balance=10)
    db.add(p);db.flush()
    c=AccountItem(account_id=a.id,fiscal_year=2570,name='child',parent_id=p.id,opening_balance=20)
    db.add(c);db.commit()
    save(db,a,2570,{'opening_token':token(db,a,2570),'account_opening':'40',f'opening_{p.id}':'999',f'opening_{c.id}':'30'})
    assert p.opening_balance==10
    assert c.opening_balance==30


def test_parent_rendered_as_output_and_children_editable(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as db:
        a=FinanceAccount(name='test');db.add(a);db.flush()
        p=AccountItem(account_id=a.id,fiscal_year=2570,name='parent',opening_balance=0)
        db.add(p);db.flush()
        c=AccountItem(account_id=a.id,fiscal_year=2570,name='child',parent_id=p.id,opening_balance=185000)
        db.add(c);db.commit();aid,pid,cid=a.id,p.id,c.id
    r=env.get(f'/finance/accounts/{aid}?year=2570')
    assert r.status_code==200
    assert f'data-opening-parent="{pid}"' in r.text
    assert f'name="opening_{pid}"' not in r.text
    assert f'name="opening_{cid}"' in r.text
    assert '185,000.00</output>' in r.text
