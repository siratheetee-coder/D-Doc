from datetime import datetime
from io import BytesIO
from pathlib import Path
import os
from docx import Document
from tests.test_subsidy import env
from app.models import FinanceAccount,FinanceTxn,DisburseMemo,WithholdingCertificate,Vendor

def doc_text(response):
    assert response.status_code==200,response.text[:200] if response.status_code!=200 else ''
    doc=Document(BytesIO(response.content))
    return '\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)

def test_tax_hub_inline_save_and_existing_payments(env,tmp_path,monkeypatch):
    import app.tenancy as tn
    import app.services.finance_forms_doc as docs
    monkeypatch.setattr(docs,'get_data_dir',lambda:tmp_path)
    tid=next(iter(tn._engines))
    out=Path(os.environ.get('DDOC_WHT_QA_DIR',str(tmp_path)));out.mkdir(exist_ok=True)
    with tn.session_for(tid) as db:
        a=FinanceAccount(name='บัญชีจ่ายทดสอบ',opening_balance=20000);db.add(a);db.flush();aid=a.id
        t=FinanceTxn(account_id=aid,fiscal_year=2570,kind='out',amount=9900,date=datetime(2026,11,1),ref='จ่าย-ภาษี-1',note='จ่ายค่าบริการที่ลงไว้แล้ว')
        db.add(FinanceTxn(account_id=aid,fiscal_year=2570,kind='out',amount=3000,date=datetime(2026,11,1),ref='จ่าย-ภาษี-2',note='ค่าจ้างที่ลงทะเบียนไว้แล้ว'))
        db.add(t);db.add(Vendor(name='ร้านทดสอบภาษี',tax_id='0105559999999',address='99 ถนนตัวอย่าง'));db.commit();txid=t.id
        before=db.query(FinanceTxn).count()
    payload={'fiscal_year':'2570','subject':'ค่าจ้างบริการทดสอบ','payee':'ร้านทดสอบภาษี','proc_kind':'จัดจ้าง','amount':'10700','vat':'700','wht':'100','date':'01/11/2569','after_save':'withholding'}
    r=env.post('/finance/disburse',data=payload,follow_redirects=False)
    assert r.status_code==303 and '/finance/withholding/memo/' in r.headers['location'],r.text
    mid=int(r.headers['location'].split('/')[-1]);review=r.headers['location']
    for path,name in [('/finance/disburse','new-memo'),(f'/finance/disburse/{mid}','memo-detail'),(review,'memo-review'),('/finance/withholding?year=2570','tax-hub'),(f'/finance/withholding/payment/{txid}','payment-review')]:
        r=env.get(path);assert r.status_code==200,(path,r.text[:200]);(out/(name+'.html')).write_text(r.text,encoding='utf-8')
    data={'income_type':'ค่าบริการ','tax_id':'0105559999999','address':'99 ถนนตัวอย่าง','ref_no':'ทดสอบ-100','intent':'download','tax_amount':'9999','base_amount':'1'}
    r=env.post(review,data=data)
    text=doc_text(r);assert '100.00' in text and '10,000.00' in text and '9,999.00' not in text
    (out/'memo-certificate.docx').write_bytes(r.content)
    # Save the latest changed amount before the nearby button opens the certificate review.
    update={**payload,'memo_no':'1/2570','wht':'150','after_save':'withholding'}
    r=env.post(f'/finance/disburse/{mid}/update',data=update,follow_redirects=False)
    assert r.status_code==303 and r.headers['location']==review
    assert '150.00' in doc_text(env.get(f'/finance/disburse/{mid}/wht.docx'))
    direct=f'/finance/withholding/payment/{txid}'
    data={'payee':'นายผู้รับเงิน ทดสอบ','tax_id':'','address':'บ้านเลขที่ 9','income_type':'ค่าบริการ','ref_no':'จ่าย-ภาษี-1','base_amount':'10000','tax_amount':'100','intent':'download'}
    r=env.post(direct,data=data);assert 'นายผู้รับเงิน ทดสอบ' in doc_text(r)
    (out/'payment-certificate.docx').write_bytes(r.content)
    assert env.post(direct,data={**data,'intent':'save'},follow_redirects=False).status_code==303
    r=env.get('/finance/withholding?year=2570');assert 'นายผู้รับเงิน ทดสอบ' in r.text and 'ร้านทดสอบภาษี' in r.text
    (out/'tax-hub.html').write_text(r.text,encoding='utf-8')
    for label,path in [('memo-detail',f'/finance/disburse/{mid}'),('payment-review',direct)]:
        (out/(label+'.html')).write_text(env.get(path).text,encoding='utf-8')
    with tn.session_for(tid) as db:
        assert db.query(WithholdingCertificate).count()==2
        assert db.query(FinanceTxn).count()==before
        assert db.get(FinanceTxn,txid).amount==9900
        assert db.query(DisburseMemo).count()==1
    for path in [f'/finance/txn/{txid}/delete',f'/finance/accounts/{aid}/delete',f'/finance/disburse/{mid}/delete']:
        r=env.post(path,follow_redirects=False);assert r.status_code==303 and 'source_locked' in r.headers['location']
    bad=env.post(direct,data={**data,'tax_amount':'NaN'});assert bad.status_code==400 and 'role="alert"' in bad.text
    for amount in ['0','-1','10001']:
        assert env.post(direct,data={**data,'tax_amount':amount}).status_code==400
    assert env.post(direct,data={**data,'tax_id':'123'}).status_code==400
    # Clearing memo tax must not leave its saved certificate impossible to delete.
    with tn.session_for(tid) as db:
        db.get(DisburseMemo,mid).wht=0;db.commit()
    assert env.get(f'/finance/disburse/{mid}/wht.docx').status_code==400
    assert env.get(review).status_code==200
    assert env.post(review+'/delete',follow_redirects=False).status_code==303
    assert env.post(direct+'/delete',follow_redirects=False).status_code==303
    with tn.session_for(tid) as db:
        assert db.query(WithholdingCertificate).count()==0
        assert db.get(FinanceTxn,txid).amount==9900

def test_only_real_unlinked_payments_can_start_certificates(env):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        a=FinanceAccount(name='บัญชีตรวจสิทธิ์');db.add(a);db.flush()
        ids=[]
        for fields in [dict(kind='in'),dict(kind='out',no_count=True),dict(kind='out',loan_id=123),dict(kind='out',disburse_id=123)]:
            t=FinanceTxn(account_id=a.id,fiscal_year=2570,amount=100,**fields);db.add(t);db.flush();ids.append(t.id)
        db.commit()
    for txid in ids:assert env.get(f'/finance/withholding/payment/{txid}').status_code==404
    assert env.get('/finance/withholding/payment/999999').status_code==404


def test_certificate_table_is_added_to_existing_database(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base,init_school_db
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE withholding_certificate')
        conn.exec_driver_sql("INSERT INTO finance_account (name) VALUES ('existing account')")
    init_school_db(engine);init_school_db(engine)
    with Session(engine) as db:
        assert db.query(WithholdingCertificate).count()==0
        assert db.query(FinanceAccount).one().name=='existing account'
    engine.dispose()
