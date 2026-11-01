from datetime import date,datetime
from pathlib import Path
import os
from tests.test_subsidy import env,db
from app.models import Person,TravelRequest,TravelRecord,DisburseMemo,FinanceTxn

def test_travel_to_finance_claim_and_duplicate_submission(env,tmp_path):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        p=Person(name='ครูตัวอย่าง เบิกค่าเดินทาง');db.add(p);db.flush()
        ids={}
        for key,status,flag,budget in [('yes','approved','yes',2500),('no','approved','no',2500),('pending','pending','yes',2500),('legacy','approved','',1200),('unknown','approved','',0)]:
            r=TravelRequest(person_id=p.id,status=status,reimburse=flag,budget=budget,subject='อบรมพัฒนาการสอน',place='สำนักงานเขตพื้นที่',start_date=date(2026,9,15),end_date=date(2026,9,16),days=2)
            db.add(r);db.flush();ids[key]=r.id
        db.commit()
    form=env.get(f'/finance/disburse?travel={ids["yes"]}')
    assert form.status_code==200 and 'name="fiscal_year" value="2569"' in form.text
    assert 'value="2500.00"' in form.text and 'ตรวจยอดตามหลักฐาน' in form.text
    out=Path(os.environ.get('DDOC_TRAVEL_QA_DIR',str(tmp_path)));out.mkdir(exist_ok=True)
    (out/'claim-form.html').write_text(form.text,encoding='utf-8')
    hr=env.get(f'/hr/travel-requests/{ids["yes"]}')
    (out/'travel-before.html').write_text(hr.text,encoding='utf-8')
    for key in ['no','pending','unknown']:
        assert env.get(f'/finance/disburse?travel={ids[key]}').status_code==400
        assert env.post('/finance/disburse',data={'travel_request_id':ids[key],'fiscal_year':'2569','amount':'999'},follow_redirects=False).status_code==400
    assert env.get(f'/finance/disburse?travel={ids["legacy"]}').status_code==200
    assert env.get('/finance/disburse?travel=999999').status_code==404
    payload={'travel_request_id':str(ids['yes']),'fiscal_year':'2569','amount':'2400','subject':'ค่าเดินทางอบรมตามหลักฐาน','payee':'ครูตัวอย่าง เบิกค่าเดินทาง','proc_kind':'ค่าใช้จ่ายอื่น'}
    with tn.session_for(tid) as db:before=db.query(FinanceTxn).count()
    result=env.post('/finance/disburse',data=payload,follow_redirects=False)
    assert result.status_code==303,result.text
    location=result.headers['location']
    assert env.post('/finance/disburse',data=payload,follow_redirects=False).headers['location']==location
    assert env.get(f'/finance/disburse?travel={ids["yes"]}',follow_redirects=False).headers['location']==location
    detail=env.get(location)
    assert f'/hr/travel-requests/{ids["yes"]}' in detail.text
    (out/'claim-detail.html').write_text(detail.text,encoding='utf-8')
    hr=env.get(f'/hr/travel-requests/{ids["yes"]}')
    assert 'เปิดบันทึกขอเบิก' in hr.text and 'ยังไม่มีรายการจ่ายในทะเบียนคุมเงิน' in hr.text
    (out/'travel-after.html').write_text(hr.text,encoding='utf-8')
    with tn.session_for(tid) as db:
        assert db.query(DisburseMemo).filter_by(travel_request_id=ids['yes']).count()==1
        assert db.query(FinanceTxn).count()==before
        assert db.query(DisburseMemo).filter_by(travel_request_id=ids['yes']).one().amount==2400

def test_registry_document_preserves_requested_expenses(db,tmp_path,monkeypatch):
    from app.routers import hr
    from app.services import gov_forms
    from docx import Document
    p=Person(name='ครู ทดสอบ',position='ครู');db.add(p);db.flush()
    rec=TravelRecord(person_id=p.id,year=2569,subject='อบรม',start_date=datetime(2026,9,15),end_date=datetime(2026,9,16),days=2,budget=2500)
    db.add(rec);db.flush()
    request=TravelRequest(person_id=p.id,record_id=rec.id,status='approved',reimburse='yes',budget=2500,subject='อบรม',place='สำนักงานเขตพื้นที่',purpose_type='อบรม',doc_ref='หนังสือเชิญ 123',start_date=date(2026,9,15),end_date=date(2026,9,16),days=2)
    db.add(request);db.commit()
    monkeypatch.setattr(gov_forms,'get_data_dir',lambda:tmp_path)
    monkeypatch.setattr(hr,'serve_generated',lambda path,mime:path)
    path=hr.hr_travel_request_docx(rec.id,db)
    text='\n'.join(p.text for p in Document(path).paragraphs)
    assert '2,500' in text and 'หนังสือเชิญ 123' in text and '☑ อบรม' in text
