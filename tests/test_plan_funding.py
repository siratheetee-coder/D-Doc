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


def test_thai_dates_and_period(db):
    p=pf.save_period(db,2568,'academic','01/05/2568','30/04/2569')
    assert p.start_date==datetime(2025,5,1)
    db.commit()
    assert pf.save_period(db,2568,'academic','16/05/2568','15/05/2569').start_date==datetime(2025,5,16), "เปลี่ยนช่วงแผนได้เสมอ"
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
