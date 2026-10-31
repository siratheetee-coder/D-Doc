import json, os
from pathlib import Path
from datetime import datetime
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.database import Base
from app.models import School, StaffOfficer, Procurement, DisburseMemo, MoneyLoan, BankRecon, RevenueRemit, FinanceAccount, FinanceTxn
from app.services import staff
from tests.test_subsidy import env

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(School(name='ทดสอบ',officer_name='นาย ก',finance_officer_name='นาง การเงินเดิม'))
        db.commit()
        yield db
    engine.dispose()

def test_case_names_and_legacy_survive_school_changes(db):
    school=db.query(School).first()
    db.add(StaffOfficer(role='officer_name',name='นาย ข'));db.commit()
    p=Procurement(fiscal_year=2570,subject='เลือกข')
    staff.apply(db,p,json.dumps({'officer_name':'นาย ข'}));db.add(p)
    legacy=Procurement(fiscal_year=2570,subject='เรื่องเก่า');db.add(legacy);db.commit()
    db.execute(update(Procurement).where(Procurement.id==legacy.id).values(staff_snapshot=''));db.commit()
    school.officer_name='นาย ค';school.finance_officer_name='นาง การเงินใหม่';db.commit()
    assert staff.read(p)['officer_name']=='นาย ข'
    assert staff.read(legacy)['officer_name']=='นาย ก'
    assert 'นาย ก' in staff.roster(db,school)['officer_name']
    assert staff.school_for(p,school).officer_name=='นาย ข'
    assert school.officer_name=='นาย ค'
    m=DisburseMemo(fiscal_year=2570,subject='เบิก',procurement_id=p.id)
    staff.apply(db,m);db.add(m);db.commit()
    assert staff.read(m)['officer_name']=='นาย ข'
    assert staff.initial(db,{'procurement_id':p.id},school)['officer_name']=='นาย ข'

def test_unknown_or_cross_school_names_rejected(db):
    p=Procurement(fiscal_year=2570,subject='ทดสอบ')
    for data in ({'officer_name':'ชื่ออีกโรงเรียน'},{'director_name':'ปลอม'},[],{'officer_name':42}):
        with pytest.raises(HTTPException):staff.apply(db,p,json.dumps(data))
    staff.apply(db,p,json.dumps({'officer_name':''}))
    assert staff.read(p)['officer_name']==''

def test_real_forms_and_endpoints(env, tmp_path):
    from app.tenancy import session_for
    # อ่าน tid จากคุกกี้ session ตรง ๆ คีย์ลายเซ็นเปลี่ยนได้เมื่อรันรวมกับเทสต์อื่น
    from base64 import b64decode
    payload=env.cookies.get('ddoc_session').split('.')[0]
    tid=json.loads(b64decode(payload+'='*(-len(payload)%4)))['tid']
    with session_for(tid) as db:
        account=FinanceAccount(name='รายได้แผ่นดินทดสอบ',fund_type='เงินรายได้แผ่นดิน');db.add(account);db.flush()
        aid=account.id
        db.add(FinanceTxn(account_id=aid,fiscal_year=2570,date=datetime(2026,10,31),kind='in',amount=1000,category='ดอกเบี้ย'))
        db.commit()
    for role,name in [('officer_name','นาย เจ้าหน้าที่คนที่สอง'),('finance_officer_name','นาง การเงินคนที่สอง')]:
        r=env.post('/settings/officers',data={'role':role,'name':name})
        assert r.status_code==200,r.text
        assert env.post('/settings/officers',data={'role':role,'name':name}).status_code==200
    assert env.post('/settings/officers',data={'role':'invalid','name':'abc'}).status_code==400
    out=Path(os.environ.get('DDOC_QA_HTML_DIR',str(tmp_path)));out.mkdir(exist_ok=True)
    for path,label in [('/settings','settings'),('/procurement/new?case=normal','procurement'),('/finance/disburse','disburse'),('/finance/loans','loans'),('/finance/revenue','revenue'),('/finance/bank-recon','recon')]:
        r=env.get(path)
        assert r.status_code==200,(path,r.text[:300])
        (out/(label+'.html')).write_text(r.text,encoding='utf-8')
        if label!='settings':assert 'name="staff_selection"' in r.text,path
    choice=json.dumps({'finance_officer_name':'นาง การเงินคนที่สอง'},ensure_ascii=False)
    proc_choice=json.dumps({'officer_name':'นาย เจ้าหน้าที่คนที่สอง'},ensure_ascii=False)
    r=env.post('/procurement/new',data={'fiscal_year':'2570','subject':'ทดสอบเจ้าหน้าที่รายเรื่อง','staff_selection':proc_choice},follow_redirects=False)
    assert r.status_code==303,r.text
    pid=int(r.headers['location'].split('/')[-1])
    prefill=env.get(f'/finance/disburse?proc={pid}')
    from lxml import html
    value=html.fromstring(prefill.text).xpath('//input[@name="staff_selection"]/@value')[0]
    assert json.loads(value)['officer_name']=='นาย เจ้าหน้าที่คนที่สอง'
    r=env.post('/finance/disburse',data={'fiscal_year':'2570','subject':'เบิกทดสอบ','procurement_id':str(pid),'staff_selection':choice},follow_redirects=False)
    assert r.status_code==303,r.text
    assert 'name="staff_selection"' in env.get(r.headers['location']).text
    r=env.post('/finance/revenue',data={'account_id':str(aid),'rtype':'interest','amount':'100','date':'31/10/2569','staff_selection':choice},follow_redirects=False)
    assert r.status_code==303 and 'msg=saved' in r.headers['location'],r.text
    for path,payload in [('/finance/loans',{'fiscal_year':'2570','contract_no':'QA-1','borrower':'ทดสอบ','amount':'100'}),('/finance/bank-recon',{'fiscal_year':'2570','as_of':'31/10/2569'})]:
        r=env.post(path,data={**payload,'staff_selection':choice},follow_redirects=False)
        assert r.status_code==303,r.text
    with session_for(tid) as db:
        for kind,cls in [('loans',MoneyLoan),('bank-recon',BankRecon),('revenue',RevenueRemit)]:
            record=db.query(cls).order_by(cls.id.desc()).first()
            assert staff.read(record)['finance_officer_name']=='นาง การเงินคนที่สอง'
            assert env.get(f'/finance/staff/{kind}/{record.id}').status_code==200
            r=env.post(f'/finance/staff/{kind}/{record.id}',data={'staff_selection':json.dumps({'finance_officer_name':''})},follow_redirects=False)
            assert r.status_code==303,r.text
        assert env.get('/finance/staff/invalid/1').status_code==404

def test_generated_documents_use_case_names(db,monkeypatch,tmp_path):
    from app.services import render,proc_alt_doc,finance_doc,finance_forms_doc
    from zipfile import ZipFile
    from lxml import etree
    for module in (proc_alt_doc,finance_doc,finance_forms_doc):monkeypatch.setattr(module,'get_data_dir',lambda:tmp_path)
    school=db.query(School).first()
    selected=json.dumps({'officer_name':'นาย ผู้ทำเรื่อง','finance_officer_name':'นาง ผู้เบิกเรื่อง'})
    p=Procurement(fiscal_year=2570,subject='ทดสอบเอกสาร',staff_snapshot=selected)
    m=DisburseMemo(fiscal_year=2570,subject='ทดสอบเบิก',staff_snapshot=selected)
    b=BankRecon(fiscal_year=2570,as_of=datetime(2026,10,31),staff_snapshot=selected)
    db.add_all([p,m,b]);db.commit()
    assert render.build_context(p,school)['officer_name']=='นาย ผู้ทำเรื่อง'
    for path,name in [(proc_alt_doc.render_w804(p,school),'นาย ผู้ทำเรื่อง'),(finance_doc.render_disburse(m,school),'นาง ผู้เบิกเรื่อง'),(finance_forms_doc.render_bank_recon(school,b),'นาง ผู้เบิกเรื่อง')]:
        with ZipFile(path) as z:
            tree=etree.fromstring(z.read('word/document.xml'))
            text=''.join(tree.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
        assert name in text
    assert school.officer_name=='นาย ก'

def test_additive_migration_preserves_existing_records(tmp_path):
    from app.database import init_school_db
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for cls in staff.MODELS:c.exec_driver_sql(f'ALTER TABLE {cls.__tablename__} DROP COLUMN staff_snapshot')
        c.exec_driver_sql("INSERT INTO procurement (fiscal_year,subject) VALUES (2570,'legacy')")
        c.exec_driver_sql('DROP TABLE staff_officer')
    init_school_db(engine);init_school_db(engine)
    with Session(engine) as db:
        assert db.query(Procurement).one().subject=='legacy'
        assert db.query(Procurement).one().staff_snapshot==''
        assert db.query(StaffOfficer).count()==0
    engine.dispose()


def test_removing_a_name_keeps_old_cases(db):
    from app.routers.pages import officer_delete
    school=db.query(School).first()
    db.add(StaffOfficer(role='officer_name',name='นาย ข'));db.commit()
    p=Procurement(fiscal_year=2570,subject='เลือกข')
    staff.apply(db,p,json.dumps({'officer_name':'นาย ข'}));db.add(p);db.commit()
    officer_delete(db=db,role='officer_name',name='นาย ข')
    assert 'นาย ข' not in staff.roster(db,school)['officer_name']
    assert staff.read(p)['officer_name']=='นาย ข'
    assert 'นาย ข' in staff.initial(db,p,school).values()


def test_default_name_and_bad_role_cannot_be_removed(db):
    from app.routers.pages import officer_delete
    for role,name in [('officer_name','นาย ก'),('bad','x')]:
        with pytest.raises(HTTPException):officer_delete(db=db,role=role,name=name)
