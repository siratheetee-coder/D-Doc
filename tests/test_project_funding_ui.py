"""Existing project funding card: neutral wording, multiple accounts, no cash movement."""
import json
import os
from pathlib import Path
import pytest
from tests.test_subsidy import env
from tests.test_plan_funding import make_plan,import_all
from app.models import FinanceAccount,AccountItem,FinanceTxn,Project,ProjectFunding,PlanFunding
from app.services import plan_funding as pf

@pytest.fixture()
def world(env):
    from app.tenancy import session_for
    from app.accounts import acc_session,Account
    with acc_session() as db: tid=db.query(Account).filter_by(username='demo').one().tenant_id
    with session_for(tid) as db:
        a=FinanceAccount(name='เงินอุดหนุน',deposit_type='bank')
        b=FinanceAccount(name='เงินรายได้สถานศึกษา',deposit_type='bank')
        db.add_all([a,b]);db.flush()
        ia=AccountItem(account_id=a.id,fiscal_year=2570,name='ค่าจัดการเรียนการสอน',opening_balance=59141.98)
        ib=AccountItem(account_id=b.id,fiscal_year=2570,name='รายได้ทั่วไป',opening_balance=26361)
        db.add_all([ia,ib]);db.commit()
        plan=make_plan(db,2569,'academic');import_all(db,plan,'opening')
        sources=pf.sources(db,plan)
        f1=next(s.id for s in sources if s.account_item_id==ia.id)
        f2=next(s.id for s in sources if s.account_item_id==ib.id)
        p=Project(name='โครงการพัฒนาบุคลากร',plan_year=2569,budget=30000)
        old=Project(name='โครงการเริ่มใช้ระบบกลางปี',plan_year=2569,budget=30000,spent_before=8000)
        db.add_all([p,old]);db.commit()
        return dict(tid=tid,pid=p.id,legacy_pid=old.id,f1=f1,f2=f2,i1=ia.id,i2=ib.id)

def capture(name,page):
    out=os.environ.get('PROJECT_FUNDING_CAPTURE')
    if out:
        assert page.status_code==200
        folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
        (folder/(name+'.html')).write_text(page.text,encoding='utf-8')

def test_existing_card_names_cap_and_legacy_explanation(env,world):
    page=env.get(f'/projects/{world["pid"]}')
    assert page.status_code==200
    text=page.text
    assert text.count('id="project-funding"')==1
    assert 'เงินที่จัดไว้ให้โครงการนี้ (บาท)' in text and 'การบันทึกนี้ไม่เพิ่มหรือตัดเงินจริง' in text
    assert 'ยังไม่ระบุรายการเงิน <b>30,000.00</b>' in text
    assert 'จัดสรรให้โครงการนี้ได้ไม่เกิน' not in text
    assert f'action="/plan-budget/project/{world["pid"]}/allocate"' in text
    assert 'data-funding-target="30000.00"' in text
    assert 'เงินรายได้สถานศึกษา' in text and 'เงินอุดหนุน' in text
    capture('project',page)
    old=env.get(f'/projects/{world["legacy_pid"]}')
    assert old.status_code==200 and 'data-funding-target="22000.00"' in old.text
    assert 'ยอดที่ต้องระบุรายการเงิน 22,000.00 บาท' in old.text
    assert 'ยังไม่ระบุรายการเงิน <b>22,000.00</b>' in old.text
    capture('legacy',old)
    out=os.environ.get('PROJECT_FUNDING_CAPTURE')
    if out: (Path(out)/'fixture.json').write_text(json.dumps(world),encoding='utf-8')

def test_save_two_sources_and_retry_never_change_cash_or_duplicate_allocations(env,world):
    from app.tenancy import session_for
    def facts(db):
        return (db.query(FinanceTxn).count(),db.get(AccountItem,world['i1']).opening_balance,
                db.get(AccountItem,world['i2']).opening_balance,db.get(PlanFunding,world['f1']).amount,
                db.get(PlanFunding,world['f2']).amount)
    with session_for(world['tid']) as db:
        before=facts(db)
        p=db.get(Project,world['pid']);plan=pf.plan(db,2569)
        token=pf.allocation_token(db,plan,p)
    # Existing allocations can be recorded partially; being incomplete is not a cash shortage.
    response=env.post(f'/plan-budget/project/{world["pid"]}/allocate',data={'token':token,f'fund_{world["f1"]}':'20000',f'fund_{world["f2"]}':'0'},follow_redirects=False)
    assert response.status_code==303
    assert 'ยังไม่ระบุรายการเงิน <b>10,000.00</b>' in env.get(f'/projects/{world["pid"]}').text
    for _ in range(2):
        with session_for(world['tid']) as db:
            token=pf.allocation_token(db,pf.plan(db,2569),db.get(Project,world['pid']))
        response=env.post(f'/plan-budget/project/{world["pid"]}/allocate',data={'token':token,f'fund_{world["f1"]}':'20000',f'fund_{world["f2"]}':'10000'},follow_redirects=False)
        assert response.status_code==303
    with session_for(world['tid']) as db:
        amounts={r.funding_id:r.amount for r in db.query(ProjectFunding).filter_by(project_id=world['pid'])}
        assert amounts=={world['f1']:20000,world['f2']:10000}
        assert facts(db)==before
    page=env.get(f'/projects/{world["pid"]}')
    assert page.status_code==200 and 'ระบุรายการเงินครบแล้ว' in page.text
    capture('saved',page)

def test_server_still_rejects_amount_above_remaining_project_budget(env,world):
    from app.tenancy import session_for
    with session_for(world['tid']) as db:
        token=pf.allocation_token(db,pf.plan(db,2569),db.get(Project,world['legacy_pid']))
        n=db.query(FinanceTxn).count()
    response=env.post(f'/plan-budget/project/{world["legacy_pid"]}/allocate',data={'token':token,f'fund_{world["f1"]}':'30000'},follow_redirects=False)
    assert response.status_code==409 and '22,000.00' in response.text
    with session_for(world['tid']) as db:
        assert db.query(ProjectFunding).filter_by(project_id=world['legacy_pid']).count()==0
        assert db.query(FinanceTxn).count()==n
