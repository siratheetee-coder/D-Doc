from datetime import datetime
from pathlib import Path
import json,os
import pytest
from app import models as m
from tests.test_subsidy import db,env
from tests.test_payment_date_edit import setup


def test_standalone_payment_uses_same_date_service(db):
    from app.services import payment_date_edit as edit
    a,p,memo,t,r=setup(db);t.disburse_id=None;db.commit()
    edit.save(db,None,t,'05/10/2569',edit.token(db,t));db.commit()
    assert t.date==r.date==datetime(2026,10,5) and t.amount==1000 and t.disburse_id is None


def test_quick_api_updates_same_payment_and_reorders_ledger_without_reposting(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p,memo,t,r=setup(db);tid=t.id
        other=m.FinanceTxn(account_id=a.id,fiscal_year=2570,date=datetime(2026,10,8),amount=200,kind='out')
        db.add(other);db.commit()
        out=Path(os.environ['QUICK_DATE_CAPTURE'])
        ledger=f'/finance/accounts/{a.id}?year=2570'
        page=env.get(ledger);assert page.status_code==200
        assert f'data-payment-date-edit="{tid}"' in page.text
        (out/'ledger-before.html').write_text(page.text,encoding='utf-8')
        project=env.get(f'/projects/{p.id}');assert project.status_code==200
        assert f'data-payment-date-edit="{tid}"' in project.text
        (out/'project-before.html').write_text(project.text,encoding='utf-8')
        url=f'/finance/txn/{tid}/payment-date'
        response=env.get(url);assert response.status_code==200,response.text
        data=response.json();assert data['be_date']=='12/10/2569'
        (out/'date-get.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        response=env.post(url,data={'paid_date':'05/10/2569','version':data['version']},follow_redirects=False)
        assert response.status_code==200 and 'location' not in response.headers,response.text
        data=response.json();assert data['be_date']=='05/10/2569'
        (out/'date-saved.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        db.expire_all();assert db.get(m.FinanceTxn,tid).date==datetime(2026,10,5)
        assert db.query(m.FinanceTxn).count()==2 and memo.date==datetime(2026,10,5) and r.amount==1000
        page=env.get(ledger);assert page.status_code==200
        assert page.text.index(f'<tr id="t{tid}"')<page.text.index(f'<tr id="t{other.id}"')
        first_row=page.text.split(f'<tr id="t{tid}"')[1].split('</tr>')[0]
        assert '<b>-1,000.00</b>' in first_row
        (out/'ledger-after.html').write_text(page.text,encoding='utf-8')
        project=env.get(f'/projects/{p.id}');assert '5 ต.ค. 2569' in project.text
    finally:db.close()


def test_api_supports_manual_and_rejects_stale_invalid_and_missing(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p,memo,t,r=setup(db);t.disburse_id=None;db.commit()
        url=f'/finance/txn/{t.id}/payment-date'
        data=env.get(url).json();assert data['memo_date']==''
        for date in ['bad','05/10/2568']:
            assert env.post(url,data={'paid_date':date,'version':data['version']}).status_code==409
        assert env.post(url,data={'paid_date':'05/10/2569','version':data['version']}).status_code==200
        assert env.post(url,data={'paid_date':'06/10/2569','version':data['version']}).status_code==409
        assert env.get('/finance/txn/999999/payment-date').status_code==404
    finally:db.close()


def test_project_without_finance_access_does_not_offer_date_edit(env,monkeypatch):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        a,p,memo,t,r=setup(db)
        monkeypatch.setattr('app.routers.pages._can_finance',lambda request:False)
        response=env.get(f'/projects/{p.id}')
        assert response.status_code==200
        assert 'data-payment-date-edit=' not in response.text and '12 ต.ค. 2569' in response.text
    finally:db.close()
