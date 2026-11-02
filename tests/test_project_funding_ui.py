"""Project/account links never reserve cash; all HTTP fixtures use isolated schools."""
import json, os, re
from pathlib import Path
import pytest
from tests.test_subsidy import env
from tests.test_plan_funding import make_plan, import_all
from app.models import FinanceAccount, AccountItem, FinanceTxn, Project, ProjectFunding, PlanFunding
from app.services import plan_funding as pf

@pytest.fixture
def world(env):
    from app.tenancy import session_for, _engines
    tid = next(iter(_engines))
    with session_for(tid) as db:
        a=FinanceAccount(name='เงินอุดหนุน', deposit_type='bank')
        b=FinanceAccount(name='เงินรายได้สถานศึกษา', deposit_type='bank')
        db.add_all([a,b]); db.flush()
        ia=AccountItem(account_id=a.id, fiscal_year=2570, name='ค่าจัดการเรียนการสอน', opening_balance=59000)
        ib=AccountItem(account_id=b.id, fiscal_year=2570, name='รายได้สถานศึกษา', opening_balance=10000)
        db.add_all([ia,ib]); db.commit()
        plan=make_plan(db,2569,'academic'); import_all(db,plan,'opening')
        src=pf.sources(db,plan)
        p=Project(name='โครงการพัฒนาบุคลากร', plan_year=2569, budget=20000)
        db.add(p); db.commit()
        return dict(tid=tid,pid=p.id,f1=next(s.id for s in src if s.account_item_id==ia.id),
                    f2=next(s.id for s in src if s.account_item_id==ib.id), i1=ia.id,i2=ib.id,a1=a.id,a2=b.id)

def capture(name, response, world):
    assert response.status_code==200
    if os.environ.get('PROJECT_FUNDING_CAPTURE'):
        out=Path(os.environ['PROJECT_FUNDING_CAPTURE']); out.mkdir(exist_ok=True,parents=True)
        (out/(name+'.html')).write_text(response.text,encoding='utf-8')
        (out/'fixture.json').write_text(json.dumps(world),encoding='utf-8')

def save(env,w,ids,token=None):
    from app.tenancy import session_for
    if token is None:
        with session_for(w['tid']) as db:
            token=pf.allocation_token(db,pf.plan(db,2569),db.get(Project,w['pid']))
    return env.post(f'/plan-budget/project/{w["pid"]}/allocate',
                    data={'token':token,**{f'fund_{i}':'1' for i in ids}},follow_redirects=False)

def test_two_accounts_no_reservation_and_only_actual_payment_reduces_balance(env,world):
    from app.tenancy import session_for
    from app.services.asset_utils import item_remaining_asof
    from app.services.project_money import project_sources, item_allocations
    w=world
    capture('project',env.get(f'/projects/{w["pid"]}'),w)
    with session_for(w['tid']) as db: before=db.query(FinanceTxn).count()
    for _ in range(2): assert save(env,w,[w['f1'],w['f2']]).status_code==303
    with session_for(w['tid']) as db:
        p=db.get(Project,w['pid']); plan=pf.plan(db,2569)
        assert p.budget==20000
        assert pf.summary(db,plan)['remaining']==69000
        assert db.query(FinanceTxn).count()==before
        assert item_remaining_asof(db.get(AccountItem,w['i1']))==59000
        assert {a.funding_id:a.amount for a in db.query(ProjectFunding).filter_by(project_id=p.id)}=={w['f1']:0,w['f2']:0}
        assert {r['item_id'] for r in project_sources(db,p.id,2570)}=={w['i1'],w['i2']}
    page=env.get(f'/projects/{w["pid"]}'); capture('saved',page,w)
    assert '59,000.00' in page.text and 'ไม่กันเงินจากกองกลาง' in page.text
    assert re.search(rf'name="fund_{w["f1"]}" value="1" checked',page.text)
    card=page.text.split('id="project-funding"')[1].split('</section>')[0]
    assert 'type="number"' not in card and card.count('type="checkbox"')==2
    ledger=env.get(f'/finance/accounts/{w["a1"]}?year=2570'); capture('ledger',ledger,w)
    assert 'เชื่อมกับ 1 โครงการ' in ledger.text and 'รอใช้ในโครงการ' not in ledger.text
    response=env.post(f'/finance/accounts/{w["a1"]}/txn',data=dict(kind='out',amount='3000',date='02/11/2569',
        fiscal_year='2570',item_id=w['i1'],project_id=w['pid'],note='จ่าย ค่าอบรมบุคลากร',place='bank'),follow_redirects=False)
    assert response.status_code==303 and 'txn_err' not in response.headers['location']
    with session_for(w['tid']) as db:
        assert db.query(FinanceTxn).count()==before+1
        assert item_remaining_asof(db.get(AccountItem,w['i1']))==56000
        assert item_remaining_asof(db.get(AccountItem,w['i2']))==10000
        it=db.get(AccountItem,w['i1']); txn=db.query(FinanceTxn).order_by(FinanceTxn.id.desc()).first()
        al=item_allocations(db,[dict(it=it,level=0,remain=56000,tout=3000)],{txn.id:db.get(Project,w['pid'])})[it.id]
        assert al['waiting']==0 and al['free']==56000 and al['projects'][0]['used']==3000
    capture('after-payment',env.get(f'/projects/{w["pid"]}'),w)

def test_legacy_amount_is_preserved_but_does_not_reserve_cash(env,world):
    from app.tenancy import session_for
    w=world
    with session_for(w['tid']) as db:
        db.add(ProjectFunding(project_id=w['pid'],funding_id=w['f1'],amount=20000));db.commit()
        assert pf.allocated(db,w['f1'])==0
        assert pf.summary(db,pf.plan(db,2569))['remaining']==69000
    assert save(env,w,[w['f1']]).status_code==303
    with session_for(w['tid']) as db:
        assert db.query(ProjectFunding).filter_by(project_id=w['pid']).one().amount==20000
    page=env.get(f'/projects/{w["pid"]}');capture('legacy',page,w)
    assert '59,000.00' in page.text and 'ยังไม่ระบุรายการเงิน <b>' not in page.text
    assert save(env,w,[]).status_code==303
    with session_for(w['tid']) as db:
        assert pf.project_link_count(db,w['pid'])==0
        assert db.get(AccountItem,w['i1']).opening_balance==59000

def test_other_plan_and_stale_form_are_rejected(env,world):
    from app.tenancy import session_for
    w=world
    with session_for(w['tid']) as db:
        p=db.get(Project,w['pid']);plan=pf.plan(db,2569);token=pf.allocation_token(db,plan,p)
        other=make_plan(db,2571,'academic')
        f=PlanFunding(plan_id=other.id,source_key='other:foreign',kind='other',name='เงินอีกแผน',amount=1)
        db.add(f);db.commit();bad=f.id
    assert save(env,w,[bad],token).status_code==409
    assert save(env,w,[w['f1']],token).status_code==303
    assert save(env,w,[w['f2']],token).status_code==409
    assert env.post(f'/plan-budget/2569/remove/{w["f1"]}',follow_redirects=False).status_code==409

def test_quick_project_checkbox_value_links_without_a_cash_budget(env,world):
    from app.tenancy import session_for
    w=world
    with session_for(w['tid']) as db:
        # A zero snapshot balance must still be linkable, not hidden as exhausted.
        db.get(PlanFunding,w['f2']).amount=0;db.commit()
    available=env.get('/finance/projects/quick-form?year=2569').json()
    assert w['f2'] in [s['id'] for s in available['sources']]
    response=env.post('/finance/projects/quick',data={'name':'โครงการใหม่','plan_year':'2569','budget':'0',
        f'fund_{w["f1"]}':'1',f'fund_{w["f2"]}':'1'})
    assert response.status_code==200
    with session_for(w['tid']) as db:
        assert pf.project_link_count(db,response.json()['id'])==2
        assert pf.summary(db,pf.plan(db,2569))['remaining']==59000
