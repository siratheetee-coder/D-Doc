"""Fiscal-year/term subsidy regressions, isolated from real school data."""
import importlib.util
import pathlib
import re
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AY = 2569


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    import app.main as main_mod
    import app.routers.auth as auth_mod
    monkeypatch.setattr(auth_mod, "authenticate", ac.authenticate)
    for key in ("tenant_state", "can_use_module", "get_account_access"):
        monkeypatch.setattr(main_mod, key, getattr(ac, key))

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    return c


from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from app.database import Base
from app.models import (School, FinanceAccount, FinanceTxn, AccountItem, SubsidySnapshot,
                        SubsidyRate, SubsidyCensus, SubsidyReceiptLink, SubsidyCensusRevision)
from app.services import subsidy as sub
import json


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(School(name='โรงเรียนทดสอบ'))
        session.commit()
        yield session
    engine.dispose()


def form_for(db, ay=2568, term=1, **overrides):
    s = sub.state(db, ay, term)
    d = {'academic_year': str(ay), 'term': str(term), 'token': s['token'], 'levels': 'ป.1',
         'rate_source': 'หนังสืออัตราทดสอบ', 'rates_confirmed': '1'}
    for k in sub.keys_for(term):
        d['r_ป.1_'+k] = '1000'
    for scan in s['census']:
        d['n_'+scan['key']+'_ป.1'] = '100' if scan == s['census'][0] else '120'
        d['source_'+scan['key']] = 'รายงาน DMC ทดสอบ'
        d['confirm_'+scan['key']] = '1'
    d.update(overrides)
    return FormData(d)


def prepared(db, ay=2568, term=1, **overrides):
    state = sub.save(db, ay, term, form_for(db, ay, term, **overrides))
    db.commit()
    return state


def confirmed(db, **overrides):
    s = prepared(db, **overrides)
    snap = sub.confirm(db, s['academic_year'], s['term'], s['token'])
    db.commit()
    return snap


def test_topup_is_full_latest_minus_first_not_thirty_percent(db):
    s = prepared(db)
    row = s['result']['rows'][0]
    assert (row['first_estimate'],row['full'],row['remaining']) == (70000,120000,50000)
    assert s['result']['ready']
    s = prepared(db, first_teach='65000', first_ref='หนังสือ 1')
    assert s['result']['rows'][0]['remaining'] == 55000


def test_declining_roll_retains_negative_adjustment(db):
    s = prepared(db, **{'n_jun2568_ป.1':'50'})
    assert s['result']['rows'][0]['remaining'] == -20000


def test_term_two_uses_new_fiscal_year_independent_rates(db):
    old = confirmed(db)
    frozen = old.payload
    s = prepared(db, term=2, **{'r_ป.1_teach':'1500'})
    assert s['fiscal_year'] == 2569
    assert len(s['result']['rows']) == 3
    assert s['result']['rows'][0]['full'] == 180000
    assert sub.state(db,2568,1)['config']['rates']['ป.1']['teach'] == 1000
    assert db.get(SubsidySnapshot,old.id).payload == frozen


def test_promotion_uses_destination_grade_rate_and_entry_grade_stays():
    cfg={'levels':['ป.1','ป.2','ม.4','ม.5','อ.2','อ.3'], 'rates':{}, 'rates_confirmed':True,'rate_source':'x'}
    for lv in cfg['levels']:
        cfg['rates'][lv]={k:10 for k in sub.keys_for(1)}
    scans=[{'counts':{'ป.1':10,'ป.2':99,'ม.4':20,'อ.2':30},'confirmed':True,'source':'x','label':'old'},
           {'counts':{lv:1 for lv in cfg['levels']},'confirmed':True,'source':'x','label':'new'}]
    r=sub.calculate(cfg,scans,1)
    assert [b['advance'] for b in r['basis']] == [10,10,20,20,30,30]
    assert r['rows'][0]['first_estimate'] == 840


def test_missing_is_not_zero_and_future_census_cannot_confirm(db):
    s=prepared(db, **{'n_jun2568_ป.1':''})
    assert s['result']['total'] is None and not s['result']['ready']
    with pytest.raises(ValueError,match='ยังยืนยันไม่ได้'): sub.confirm(db,2568,1,s['token'])
    db.rollback()
    s=prepared(db, **{'n_jun2568_ป.1':'0'})
    assert s['result']['total'] == 0 and s['result']['ready']
    with pytest.raises(ValueError,match='ยังไม่ถึงวันสำรวจ'):
        sub.save(db,2699,2,form_for(db,2699,2))
    db.rollback()


@pytest.mark.parametrize('raw',['-1','NaN','Infinity','1000000001','abc'])
def test_invalid_money_rejected(raw):
    with pytest.raises(ValueError): sub.number(raw,'amount')


def test_dmc_fraction_rejected():
    with pytest.raises(ValueError): sub.number('1.5','heads',True)


def test_snapshot_immutable_and_stale_form_rejected(db):
    snap=confirmed(db)
    frozen=snap.payload
    stale=form_for(db)
    prepared(db, **{'r_ป.1_teach':'1100'})
    assert sub.state(db,2568,1)['changed']
    assert db.get(SubsidySnapshot,snap.id).payload==frozen
    with pytest.raises(ValueError,match='หน้าอื่น'): sub.save(db,2568,1,stale)
    db.rollback()
    assert sub.state(db,2568,1)['config']['rates']['ป.1']['teach']==1100


def test_reconfirm_idempotent_and_census_revisions_not_duplicated(db):
    snap=confirmed(db)
    s=sub.state(db,2568,1)
    assert sub.confirm(db,2568,1,s['token']).id==snap.id
    prepared(db)
    assert db.query(SubsidyCensusRevision).count()==2


def test_legacy_data_preserved_unconfirmed(db):
    db.add(SubsidyRate(academic_year=2568,level='ป.1',item_key='teach',amount=2280))
    db.add(SubsidyCensus(academic_year=2567,round='nov',level='ป.1',count=9))
    db.commit()
    s=sub.state(db,2568,1)
    assert s['config']['rates']['ป.1']['teach']==1140
    assert not s['result']['ready']
    prepared(db)
    assert db.query(SubsidyRate).one().amount==2280
    assert db.query(SubsidyCensus).one().count==9


def account(db):
    a=FinanceAccount(name='เงินอุดหนุน')
    db.add(a);db.flush()
    return a


def test_receipt_split_cannot_double_count_between_terms_or_repeat_click(db):
    a=account(db)
    t=FinanceTxn(account_id=a.id,fiscal_year=2569,kind='in',amount=1000)
    db.add(t);db.commit()
    sub.link_receipt(db,2568,2,t.id,'teach','first','600');db.commit()
    with pytest.raises(ValueError,match='เชื่อมรายการ'): sub.link_receipt(db,2568,2,t.id,'teach','first','100')
    db.rollback()
    with pytest.raises(ValueError,match='เกินเงินรับจริง'): sub.link_receipt(db,2569,1,t.id,'teach','first','500')
    db.rollback()
    sub.link_receipt(db,2569,1,t.id,'teach','first','400');db.commit()
    assert sub.receipt_summary(db,2568,2)[0]['teach']==600
    assert sub.receipt_summary(db,2569,1)[0]['teach']==400
    assert sub.receipt_summary(db,2570,1)[0]=={}
    t.amount=500;db.commit()
    assert sub.receipt_summary(db,2568,2)[0]=={}
    assert not sub.receipt_summary(db,2569,1)[1][0]['valid']


def test_deleted_receipt_cannot_attach_to_reused_id(db):
    a=account(db)
    t=FinanceTxn(account_id=a.id,fiscal_year=2568,kind='in',amount=1000)
    db.add(t);db.commit();tid=t.id
    sub.link_receipt(db,2568,1,tid,'teach','first','500');db.commit()
    db.delete(t);db.commit()
    db.add(FinanceTxn(id=tid,account_id=a.id,fiscal_year=2568,kind='in',amount=1000));db.commit()
    assert sub.receipt_summary(db,2568,1)[0]=={}
    assert db.query(SubsidyReceiptLink).count()==0


def test_deleted_budget_item_does_not_reuse_old_contribution(db):
    from app.models import SubsidyBudgetContribution
    snap=confirmed(db);a=account(db);db.commit()
    p=sub.budget_preview(db,snap,a.id);sub.apply_budget(db,snap,a.id,sub.fingerprint(p));db.commit()
    item=db.query(AccountItem).filter_by(name=sub.NAMES['teach']).one();iid=item.id
    db.delete(item);db.commit()
    db.add(AccountItem(id=iid,account_id=a.id,fiscal_year=2568,name='งบอื่น',budget=200));db.commit()
    assert db.query(SubsidyBudgetContribution).filter_by(item_key='teach').count()==0
    p=sub.budget_preview(db,snap,a.id)
    row=next(r for r in p['rows'] if r['key']=='teach')
    assert row['item_id'] is None and row['previous']==0


def test_budget_preserves_other_money_and_uses_correct_fy(db):
    snap=confirmed(db)
    a=account(db)
    item=AccountItem(account_id=a.id,fiscal_year=2568,name=sub.NAMES['teach'],budget=123)
    db.add(item);db.commit()
    p=sub.budget_preview(db,snap,a.id)
    token=sub.fingerprint(p)
    sub.apply_budget(db,snap,a.id,token);db.commit()
    assert item.budget==120123
    assert db.query(AccountItem).filter_by(fiscal_year=2569).count()==0
    with pytest.raises(ValueError,match='ยอดงบปลายทางเปลี่ยน'): sub.apply_budget(db,snap,a.id,token)
    db.rollback()
    p=sub.budget_preview(db,snap,a.id)
    sub.apply_budget(db,snap,a.id,sub.fingerprint(p));db.commit()
    assert item.budget==120123 and db.query(AccountItem).count()==5


def test_budget_rejects_stale_snapshot_and_destination_change(db):
    snap=confirmed(db); a=account(db);db.commit()
    p=sub.budget_preview(db,snap,a.id)
    db.add(AccountItem(account_id=a.id,fiscal_year=2568,name=sub.NAMES['teach'],budget=100));db.commit()
    with pytest.raises(ValueError,match='ยอดงบปลายทางเปลี่ยน'): sub.apply_budget(db,snap,a.id,sub.fingerprint(p))
    db.rollback()
    prepared(db, **{'r_ป.1_teach':'900'})
    with pytest.raises(ValueError,match='ฉบับใหม่'): sub.apply_budget(db,snap,a.id,sub.fingerprint(p))
    db.rollback()


def test_removed_extra_subtracts_only_previous_contribution(db):
    snap=confirmed(db,extra_small='500',extra_ref_small='หนังสือเพิ่มเติม')
    a=account(db);db.commit()
    p=sub.budget_preview(db,snap,a.id);sub.apply_budget(db,snap,a.id,sub.fingerprint(p));db.commit()
    item=db.query(AccountItem).filter_by(name=sub.NAMES['small']).one()
    item.budget+=50;db.commit()
    snap2=confirmed(db)
    p=sub.budget_preview(db,snap2,a.id);sub.apply_budget(db,snap2,a.id,sub.fingerprint(p));db.commit()
    assert item.budget==50


def test_two_academic_years_contribute_to_same_fiscal_budget(db):
    a=account(db);db.commit()
    prior=confirmed(db,ay=2567,term=2)
    p=sub.budget_preview(db,prior,a.id);sub.apply_budget(db,prior,a.id,sub.fingerprint(p));db.commit()
    current=confirmed(db,ay=2568,term=1)
    p=sub.budget_preview(db,current,a.id);sub.apply_budget(db,current,a.id,sub.fingerprint(p));db.commit()
    item=db.query(AccountItem).filter_by(fiscal_year=2568,name=sub.NAMES['teach']).one()
    assert item.budget==240000
    amended=confirmed(db,ay=2568,term=1,**{'r_ป.1_teach':'900'})
    p=sub.budget_preview(db,amended,a.id);sub.apply_budget(db,amended,a.id,sub.fingerprint(p));db.commit()
    assert item.budget==228000  # Other term's 120,000 remains intact.


def test_confirmed_report_uses_frozen_amounts_and_sources(db,monkeypatch,tmp_path):
    from app.services import finance_forms_doc, subsidy_report
    from docx import Document
    monkeypatch.setattr(finance_forms_doc,'get_data_dir',lambda:tmp_path)
    snap=confirmed(db)
    prepared(db,rate_source='หนังสือใหม่',**{'r_ป.1_teach':'900'})
    path=subsidy_report.render(db.query(School).first(),json.loads(snap.payload),snap.id)
    doc=Document(path)
    assert doc.tables[0].rows[1].cells[3].text=='120,000.00'
    assert any('หนังสืออัตราทดสอบ' in p.text for p in doc.paragraphs)
    assert not any('หนังสือใหม่' in p.text for p in doc.paragraphs)


def test_routes_save_validation_snapshot_and_budget(env):
    from app.tenancy import session_for
    c=env
    r=c.get('/finance/subsidy?year=2568&term=1')
    assert r.status_code==200, r.text[:500]
    assert 'บาท/คน/ภาคเรียน' in r.text
    db=session_for(1)
    data=dict(form_for(db))
    a=account(db);db.commit();aid=a.id;db.close()
    invalid=dict(data, rate_source='', rates_confirmed='1')
    r=c.post('/finance/subsidy',data=invalid,follow_redirects=False)
    assert r.status_code==422 and 'ยังบันทึกไม่ได้' in r.text
    assert 'value="1000"' in r.text
    r=c.post('/finance/subsidy',data=data,follow_redirects=False)
    assert r.status_code==303,r.text[:500]
    db=session_for(1);s=sub.state(db,2568,1);db.close()
    r=c.post('/finance/subsidy/confirm',data={'academic_year':2568,'term':1,'token':s['token']},follow_redirects=False)
    assert r.status_code==303,r.text
    assert c.get(r.headers['location']).status_code==200
    sid=int(r.headers['location'].split('/')[-1])
    r=c.get(f'/finance/subsidy/budget-preview?snapshot_id={sid}&account_id={aid}')
    assert r.status_code==200,r.text
    token=re.search(r'name="token" value="([^"]+)"',r.text).group(1)
    post={'snapshot_id':sid,'account_id':aid,'token':token}
    assert c.post('/finance/subsidy/to-budget',data=post).status_code==409
    post['reviewed']='1'
    assert c.post('/finance/subsidy/to-budget',data=post,follow_redirects=False).status_code==303
    assert c.get('/finance/subsidy?year=2568&term=3').status_code==400
