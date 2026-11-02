import json
from datetime import datetime
import pytest
from fastapi import HTTPException
from tests.test_subsidy import db, env, confirmed, prepared
from app.models import (FinanceAccount, AccountItem, FinanceTxn, SubsidyItemMapping,
    SubsidyReceiptLink, Project, PlanBudget, PlanFunding, ProjectFunding, DisburseMemo)
from app.services import plan_funding as pf, subsidy as sub


def make_plan(db,year=2568,mode='academic'):
    start,end=pf.defaults(year,mode)
    return pf.save_period(db,year,mode,start.isoformat(),end.isoformat())


def map_snapshot(db,snap):
    a=FinanceAccount(name='เงินอุดหนุน');db.add(a);db.flush()
    for row in json.loads(snap.payload)['result']['rows']:
        i=AccountItem(account_id=a.id,fiscal_year=snap.fiscal_year,name=row['name'],opening_balance=0)
        db.add(i);db.flush()
        db.add(SubsidyItemMapping(fiscal_year=snap.fiscal_year,item_key=row['key'],account_item_id=i.id))
    db.commit();return a


def import_all(db,p,kind='subsidy',sid=0):
    review=pf.preview(db,p,kind,sid)
    pf.apply(db,p,kind,sid,sub.fingerprint(review),[r['source_key'] for r in review['rows']])
    db.commit()


def test_snapshot_import_idempotent_and_cash_untouched(db):
    s=confirmed(db);map_snapshot(db,s);p=make_plan(db)
    before=db.query(FinanceTxn).count()
    import_all(db,p,sid=s.id);first=pf.summary(db,p)['total']
    import_all(db,p,sid=s.id)
    assert pf.summary(db,p)['total']==first==600000
    assert db.query(FinanceTxn).count()==before
    assert all(i.budget==0 for i in db.query(AccountItem))


def test_wrong_year_stale_snapshot_and_unmapped_rejected(db):
    s=confirmed(db);p=make_plan(db)
    with pytest.raises(ValueError,match='จับคู่'):pf.preview(db,p,'subsidy',s.id)
    map_snapshot(db,s)
    other=make_plan(db,2570,'budget')
    with pytest.raises(ValueError,match='ไม่ตรง'):pf.preview(db,other,'subsidy',s.id)
    prepared(db,**{'r_ป.1_teach':'2000'})
    with pytest.raises(ValueError,match='เปลี่ยน'):pf.preview(db,p,'subsidy',s.id)


def test_token_prevents_import_after_destination_changed(db):
    s=confirmed(db);map_snapshot(db,s);p=make_plan(db)
    old=pf.preview(db,p,'subsidy',s.id)
    import_all(db,p,sid=s.id)
    with pytest.raises(ValueError,match='เปลี่ยน'):pf.apply(db,p,'subsidy',s.id,sub.fingerprint(old),[r['source_key'] for r in old['rows']])


def test_academic_and_fiscal_rounds(db):
    t1=confirmed(db);t2=confirmed(db,term=2)
    acad=make_plan(db);fiscal=make_plan(db,2569,'budget')
    assert pf.eligible(acad,t1) and pf.eligible(acad,t2)
    assert not pf.eligible(fiscal,t1) and pf.eligible(fiscal,t2)


def test_early_receipt_not_counted_as_new_money(db):
    s=confirmed(db);a=map_snapshot(db,s);p=make_plan(db)
    item=db.query(AccountItem).filter_by(account_id=a.id).first()
    txn=FinanceTxn(account_id=a.id,item_id=item.id,fiscal_year=2568,kind='in',amount=20000,date=datetime(2025,4,30))
    db.add(txn);db.flush()
    db.add(SubsidyReceiptLink(txn_id=txn.id,academic_year=2568,term=1,item_key='teach',amount=20000,round='initial'))
    db.commit()
    row=next(r for r in pf.subsidy_candidates(db,p,s.id) if r['source_key'].endswith(':teach'))
    assert row['amount']==100000 and row['payload']['received_before']==20000


def test_thai_dates_and_locked_period(db):
    p=pf.save_period(db,2568,'academic','01/05/2568','30/04/2569')
    assert p.start_date==datetime(2025,5,1)
    db.add(PlanFunding(plan_id=p.id,source_key='other:lock',kind='other',name='test',amount=100));db.commit()
    with pytest.raises(ValueError,match='นำงบเข้าแผนแล้ว'):
        pf.save_period(db,2568,'academic','02/05/2568','30/04/2569')
    with pytest.raises(ValueError):pf.save_period(db,2569,'budget','01/01/2569','30/09/2569')


def test_opening_uses_cutoff_and_parent_self_only(db):
    p=make_plan(db)
    a=FinanceAccount(name='test');db.add(a);db.flush()
    parent=AccountItem(account_id=a.id,fiscal_year=2568,name='parent',opening_balance=10)
    db.add(parent);db.flush()
    child=AccountItem(account_id=a.id,fiscal_year=2568,name='child',parent_id=parent.id,opening_balance=100)
    db.add(child);db.flush()
    for date,kind,amt in [(datetime(2025,4,30),'in',50),(datetime(2025,4,30),'out',20),(datetime(2025,5,1),'out',99)]:
        db.add(FinanceTxn(account_id=a.id,item_id=child.id,fiscal_year=2568,date=date,kind=kind,amount=amt))
    db.commit();import_all(db,p,'opening')
    assert pf.summary(db,p)['total']==140
    db.add(FinanceTxn(account_id=a.id,item_id=child.id,fiscal_year=2568,date=datetime(2025,4,29),kind='out',amount=5));db.commit()
    assert pf.changed(db,p,next(s for s in pf.sources(db,p) if s.account_item_id==child.id))


def test_allocation_caps_stale_form_and_move_delete_guards(db):
    p=make_plan(db)
    source=PlanFunding(plan_id=p.id,source_key='other:test',kind='other',name='donation',amount=100)
    project=Project(name='A',plan_year=p.year,budget=90);other=Project(name='B',plan_year=p.year,budget=100)
    db.add_all([source,project,other]);db.commit()
    token=pf.allocation_token(db,p,project)
    pf.allocate(db,p,project,{str(source.id):80},token);db.commit()
    with pytest.raises(ValueError,match='เปลี่ยน'):pf.allocate(db,p,project,{str(source.id):80},token)
    with pytest.raises(ValueError,match='เกินวงเงิน'):pf.allocate(db,p,other,{str(source.id):30},pf.allocation_token(db,p,other))
    with pytest.raises(ValueError,match='เกินงบโครงการ'):pf.allocate(db,p,project,{str(source.id):95},pf.allocation_token(db,p,project))
    with pytest.raises(HTTPException):pf.guard_project(db,project,year=2569)
    with pytest.raises(HTTPException):pf.guard_project(db,project,budget=79)
    with pytest.raises(HTTPException):pf.guard_project(db,project,deleting=True)
    assert pf.summary(db,p)['remaining']==20


def test_lower_snapshot_cannot_erase_allocated_money(db):
    s=confirmed(db);map_snapshot(db,s);p=make_plan(db);import_all(db,p,sid=s.id)
    source=next(s for s in pf.sources(db,p) if s.source_key.endswith(':teach'))
    project=Project(name='A',plan_year=p.year,budget=120000);db.add(project);db.commit()
    pf.allocate(db,p,project,{str(source.id):120000},pf.allocation_token(db,p,project));db.commit()
    latest=confirmed(db,**{'r_ป.1_teach':'500'})
    assert pf.changed(db,p,source)
    data=pf.preview(db,p,'subsidy',latest.id)
    with pytest.raises(ValueError,match='ต่ำกว่า'):pf.apply(db,p,'subsidy',latest.id,sub.fingerprint(data),[source.source_key])
    assert source.amount==120000


def test_overlapping_plans_cannot_reuse_money(db):
    p=make_plan(db);a=PlanFunding(plan_id=p.id,source_key='other:1',kind='other',name='test',amount=1)
    db.add(a);db.commit()
    other=make_plan(db,2569,'budget')
    with pytest.raises(ValueError,match='ซ้อน'):pf.preview(db,other,'opening')


def test_cash_counted_once_not_procurement_commitments(db):
    project=Project(name='A',budget=100);db.add(project);db.flush()
    a=FinanceAccount(name='cash');db.add(a);db.flush()
    memo=DisburseMemo(project_id=project.id,fiscal_year=2568,amount=90);db.add(memo);db.flush()
    db.add(FinanceTxn(account_id=a.id,project_id=project.id,disburse_id=memo.id,fiscal_year=2568,kind='out',amount=70))
    db.add(FinanceTxn(account_id=a.id,project_id=project.id,fiscal_year=2568,kind='in',amount=200));db.commit()
    assert pf.actual_paid(db,project)==70


def test_http_period_review_allocation_and_prefilled_ledger(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        s=confirmed(db);a=map_snapshot(db,s);snapshot_id=s.id
        project=Project(name='โครงการทดสอบแผน',plan_year=2568,budget=10000);db.add(project);db.commit();pid=project.id
    assert env.get('/plan-budget/2568?mode=academic').status_code==200
    result=env.post('/plan-budget/2568/period',data=dict(mode='academic',start='2025-05-01',end='2026-04-30'))
    assert result.status_code==200
    review=env.get(f'/plan-budget/2568/review?kind=subsidy&snapshot_id={snapshot_id}')
    assert review.status_code==200,review.text[:300]
    with tn.session_for(sid) as db:
        p=pf.plan(db,2568);data=pf.preview(db,p,'subsidy',snapshot_id)
    result=env.post('/plan-budget/2568/apply',data=dict(kind='subsidy',snapshot_id=str(snapshot_id),token=sub.fingerprint(data),selected=[r['source_key'] for r in data['rows']]))
    assert result.status_code==200,result.text[:300]
    assert env.get('/projects?year=2568').status_code==200
    with tn.session_for(sid) as db:
        p=pf.plan(db,2568);project=db.get(Project,pid);source=pf.sources(db,p)[0];fid=source.id
        tok=pf.allocation_token(db,p,project);item=db.get(AccountItem,source.account_item_id);aid,iid=item.account_id,item.id
    result=env.post(f'/plan-budget/project/{pid}/allocate',data={'token':tok,f'fund_{fid}':'10000'})
    assert result.status_code==200,result.text[:300]
    assert 'จ่ายจริงตามทะเบียนคุมเงิน' in result.text
    ledger=env.get(f'/finance/accounts/{aid}?year=2568&item={iid}&project={pid}&kind=out')
    assert ledger.status_code==200
    assert 'value="out" selected' in ledger.text and f'value="{pid}" selected' in ledger.text
    assert env.post(f'/projects/{pid}/set-year',data={'plan_year':'2569'}).status_code==409
    assert env.post(f'/plan-budget/2568/remove/{fid}').status_code==409

