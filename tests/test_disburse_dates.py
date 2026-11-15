from datetime import datetime
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import os
import pytest
from tests.test_subsidy import env,db
from app.models import FinanceAccount,FinanceTxn,DisburseMemo,DisburseSplit,Receipt,CheckPayment,School
from app.services import disburse_split as splits

def session():
 import app.tenancy as tn
 return tn.session_for(next(iter(tn._engines)))

def seed(env,split=False):
 with session() as db:
  a=FinanceAccount(name='เงินอุดหนุน');b=FinanceAccount(name='รายได้สถานศึกษา');db.add_all([a,b]);db.flush()
  m=DisburseMemo(fiscal_year=2570,memo_no='DATE/2570',date=datetime(2026,11,1),subject='ค่าวัสดุกิจกรรมการเรียนการสอน',amount=1000,wht=10,account_id=a.id,status='อนุมัติ')
  db.add(m);db.flush()
  if split:m.splits=[DisburseSplit(seq=1,account_id=a.id,amount=600),DisburseSplit(seq=2,account_id=b.id,amount=400)]
  db.commit();return m.id,a.id,b.id

@pytest.mark.parametrize('split',[False,True])
def test_payment_date_separate_from_memo_and_survives_edits(env,split):
 mid,aid,bid=seed(env,split);url=f'/finance/disburse/{mid}'
 html=env.get(url).text
 assert 'name="paid_date"' in html and 'วันที่จ่ายเงินจริง' in html
 env.post(url+'/post',data={'paid_date':'05/11/2569'})
 with session() as db:
  m=db.get(DisburseMemo,mid);rows=db.query(FinanceTxn).filter_by(disburse_id=mid).all()
  assert len(rows)==(2 if split else 1) and m.date==datetime(2026,11,1)
  assert all(t.date==datetime(2026,11,5) for t in rows)
  db.add(CheckPayment(txn_id=rows[0].id,account_id=aid,fiscal_year=2570,amount=rows[0].amount));db.commit()
 if not split:
  assert '-1,000.00' not in env.get('/finance/cash-report?date=04/11/2569').text
  assert '-1,000.00' in env.get('/finance/cash-report?date=05/11/2569').text
 form=dict(account_id=str(aid),amount='1000',wht='10',date='02/11/2569',subject='แก้ชื่อเรื่อง',memo_no='DATE/2570',status='อนุมัติ')
 if split:form.update(split_account=[str(aid),str(bid)],split_item=['',''],split_amount=['600','400'])
 res=env.post(url+'/update',data=form,follow_redirects=False)
 assert 'saved=1' in res.headers['location'],res.headers['location']
 env.post(url+'/post',data={'paid_date':'06/11/2569'})
 with session() as db:
  assert db.get(DisburseMemo,mid).date==datetime(2026,11,2)
  rows=db.query(FinanceTxn).filter_by(disburse_id=mid).all()
  assert len(rows)==(2 if split else 1) and all(t.date==datetime(2026,11,5) for t in rows)

@pytest.mark.parametrize('value',['','bad','31/11/2569','30/09/2569','01/10/2570'])
def test_bad_or_out_of_year_payment_dates_do_not_post(env,value):
 mid,_,_=seed(env)
 res=env.post(f'/finance/disburse/{mid}/post',data={'paid_date':value},follow_redirects=False)
 assert 'payment_message=' in res.headers['location']
 with session() as db:assert db.query(FinanceTxn).filter_by(disburse_id=mid).count()==0

def test_default_year_filter_and_explicit_all_years(env):
 from app.thai_utils import current_fiscal_year
 fy=current_fiscal_year()
 with session() as db:
  db.add_all([DisburseMemo(fiscal_year=fy,subject='CURRENT_YEAR_ONLY'),DisburseMemo(fiscal_year=fy-1,subject='PREVIOUS_YEAR_ONLY')]);db.commit()
 html=env.get('/finance/disburse').text
 assert 'CURRENT_YEAR_ONLY' in html and 'PREVIOUS_YEAR_ONLY' not in html
 html=env.get('/finance/disburse?year=all').text
 assert 'CURRENT_YEAR_ONLY' in html and 'PREVIOUS_YEAR_ONLY' in html and 'ทุกปีงบประมาณ' in html
 (Path(os.environ['FINANCE_DASH_CAPTURE'])/'dates-filter-all.html').write_text(html,encoding='utf-8')
 html=env.get(f'/finance/disburse?year={fy-1}').text
 assert 'PREVIOUS_YEAR_ONLY' in html and 'CURRENT_YEAR_ONLY' not in html
 assert env.get('/finance/disburse?year=bad').status_code==400
 assert env.get('/finance/disburse?year=99999').status_code==400

def test_generated_request_and_tax_certificate_use_their_own_dates(env,tmp_path,monkeypatch):
 import app.services.finance_doc as memo_doc
 import app.services.finance_forms_doc as forms
 from app.thai_utils import thai_date,thai_date_short
 monkeypatch.setattr(memo_doc,'get_data_dir',lambda:tmp_path)
 monkeypatch.setattr(forms,'get_data_dir',lambda:tmp_path)
 mid,_,_=seed(env);env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'05/11/2569'})
 with session() as db:
  m=db.get(DisburseMemo,mid);school=db.query(School).first()
  from app.services.disburse_dates import certificate_date
  assert certificate_date(m)==datetime(2026,11,5)
  memo_path=memo_doc.render_disburse(m,school)
  tax_path=forms.render_wht_certificate(school,m)
  from docx import Document
  def text(p):
   d=Document(p);return '\n'.join([x.text for x in d.paragraphs]+[c.text for t in d.tables for row in t.rows for c in row.cells])
  assert thai_date(datetime(2026,11,1)) in text(memo_path)
  assert thai_date_short(datetime(2026,11,5)) in text(tax_path)
  assert thai_date_short(datetime(2026,11,1)) not in text(tax_path)
 out=Path(os.environ['FINANCE_DASH_CAPTURE'])
 (out/'dates-ready.html').write_text(env.get('/finance/disburse?year=2570').text,encoding='utf-8')
 (out/'dates-paid.html').write_text(env.get(f'/finance/disburse/{mid}').text,encoding='utf-8')
 # Separate unpaid record for the confirmation dialog screenshot.
 other,_,_=seed(env)
 (out/'dates-dialog.html').write_text(env.get(f'/finance/disburse/{other}').text,encoding='utf-8')

def test_split_added_after_payment_uses_original_payment_day(db):
 a=FinanceAccount(name='a');b=FinanceAccount(name='b');db.add_all([a,b]);db.flush()
 m=DisburseMemo(fiscal_year=2570,account_id=a.id,amount=1000,date=datetime(2026,11,1));db.add(m);db.flush()
 splits.post(db,m,paid_date=datetime(2026,11,5));db.flush()
 rows=db.query(FinanceTxn).filter_by(disburse_id=m.id).all()
 splits.apply(db,m,[dict(account_id=a.id,item_id=None,amount=600),dict(account_id=b.id,item_id=None,amount=400)])
 m.date=datetime(2026,11,2);splits.sync(db,m,rows);db.flush()
 assert all(t.date==datetime(2026,11,5) for t in db.query(FinanceTxn).filter_by(disburse_id=m.id))

def test_certificate_does_not_invent_payment_date_for_unpaid_or_mixed_legacy(db):
 from app.services.disburse_dates import certificate_date
 a=FinanceAccount(name='a');db.add(a);db.flush()
 m=DisburseMemo(fiscal_year=2570,account_id=a.id,amount=1000,date=datetime(2026,11,1));db.add(m);db.flush()
 assert certificate_date(m) is None
 for day in (5,6):db.add(FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=500,disburse_id=m.id,date=datetime(2026,11,day)))
 db.flush();assert certificate_date(m) is None
