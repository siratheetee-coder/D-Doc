"""Calendar register boundaries, legacy preservation, import and export."""
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse, parse_qs
import pytest
from tests.test_subsidy import env
from tests.test_letter_tracking import school, people, capture

@pytest.fixture(autouse=True)
def no_mail(monkeypatch):
    monkeypatch.setattr('app.services.mailer.send_email', lambda *a, **kw: True)

def test_receipt_calendar_continues_in_october_and_resets_january(env):
    from app.tenancy import session_for
    from app.models import IncomingLetter, DocNumberCounter
    from app.services.incoming_register import next_number
    dates=['30/09/2569','01/10/2569','31/12/2569','01/01/2570']
    for i,date in enumerate(dates):
        response=env.post('/admin/incoming',data={'subject':f'ขอบเขตปี {i}','recv_date':date},follow_redirects=False)
        assert response.status_code==303 and 'err=' not in response.headers['location']
        assert response.headers['location']==('/admin/incoming?year=2570' if i==3 else '/admin/incoming?year=2569')
    with session_for(school()) as db:
        rows=db.query(IncomingLetter).order_by(IncomingLetter.id).all()
        assert [r.recv_no for r in rows]==[1,2,3,1]
        assert [r.calendar_year for r in rows]==[2569,2569,2569,2570]
        assert [r.fiscal_year for r in rows]==[2569,2570,2570,2570]
        # 2570 is the current fiscal year in November 2569: never remap it back to 2569 here.
        assert next_number(db,2570)==2 and next_number(db,2569)==4
        assert db.query(DocNumberCounter).filter_by(doc_type='incoming',fiscal_year=2570).one().last_number==1
    page=env.get('/admin/incoming?year=2569')
    assert page.status_code==200 and 'ปี พ.ศ. 2569' in page.text
    assert 'ขอบเขตปี 2' in page.text and 'ขอบเขตปี 3' not in page.text
    capture('calendar-register',page)
    dashboard=env.get('/admin')
    assert dashboard.status_code==200 and f'หนังสือรับ ปี {datetime.now().year+543}' in dashboard.text

def test_year_and_duplicate_validation_is_friendly(env):
    from app.models import IncomingLetter
    from app.tenancy import session_for
    a=env.post('/admin/incoming',data={'calendar_year':2569,'recv_date':'01/01/2570','subject':'wrong year'},follow_redirects=False)
    params=parse_qs(urlparse(a.headers['location']).query)
    assert a.status_code==303 and params['year']==['2570'] and 'err' in params
    assert 'ปีทะเบียนต้องตรง' in env.get(a.headers['location']).text
    form={'recv_date':'01/10/2569','recv_no':'8','subject':'original'}
    env.post('/admin/incoming',data=form)
    b=env.post('/admin/incoming',data={**form,'subject':'duplicate'},follow_redirects=False)
    assert b.status_code==303 and 'err' in parse_qs(urlparse(b.headers['location']).query)
    with session_for(school()) as db: assert db.query(IncomingLetter).count()==1

def test_undated_legacy_requires_confirmation_keeps_number_and_ack(env):
    from app.models import IncomingLetter,LetterRecipient
    from app.tenancy import session_for
    from app.services.incoming_register import next_number
    tid=school();pid=people(tid)[0];stamp=datetime(2026,10,5,9)
    with session_for(tid) as db:
        r=IncomingLetter(fiscal_year=2570,recv_no=90,subject='ทะเบียนเดิมไม่มีวันที่',route_status='sent')
        db.add(r);db.flush();rid=r.id
        rc=LetterRecipient(letter_id=rid,person_id=pid,name='Legacy teacher',ack_at=stamp,ack_by='ธุรการ')
        db.add(rc);db.commit();rcid=rc.id
        assert next_number(db,2569)>=91
    assert 'ทะเบียนเดิมไม่มีวันที่' not in env.get('/admin/incoming?year=2569').text
    page=env.get('/admin/incoming?year=-1')
    assert 'ทะเบียนเดิมไม่มีวันที่' in page.text and 'name="calendar_year"' not in page.text
    capture('calendar-pending',page)
    detail=env.get(f'/admin/incoming/{rid}')
    assert 'ยืนยันปีทะเบียน โดยคงเลขรับเดิม' in detail.text
    capture('calendar-confirm',detail)
    response=env.post(f'/admin/incoming/{rid}/calendar-year',data={'calendar_year':2569},follow_redirects=False)
    assert response.status_code==303 and 'msg=' in response.headers['location']
    with session_for(tid) as db:
        r=db.get(IncomingLetter,rid);rc=db.get(LetterRecipient,rcid)
        assert (r.calendar_year,r.fiscal_year,r.recv_no)==(2569,2570,90)
        assert rc.ack_at==stamp and rc.ack_by=='ธุรการ'
    assert 'ทะเบียนเดิมไม่มีวันที่' in env.get('/admin/incoming?year=2569').text

def test_actual_legacy_schema_backfills_only_dated_rows(tmp_path):
    from sqlalchemy import create_engine, MetaData, Table, Column, insert, select
    from app.database import Base,init_school_db
    from app.models import IncomingLetter
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    meta=MetaData()
    old=Table('incoming_letter',meta,*[Column(c.name,c.type,primary_key=c.primary_key,nullable=c.nullable)
                  for c in IncomingLetter.__table__.columns if c.name!='calendar_year'])
    meta.create_all(engine)
    with engine.begin() as db:
        db.execute(insert(old),[
          {'id':1,'fiscal_year':2569,'recv_no':5,'recv_date':datetime(2026,9,30)},
          {'id':2,'fiscal_year':2570,'recv_no':5,'recv_date':datetime(2026,10,1)},
          {'id':3,'fiscal_year':2570,'recv_no':90,'recv_date':None}])
    init_school_db(engine)
    init_school_db(engine)  # idempotent on subsequent restarts
    with engine.connect() as db:
        rows=db.execute(select(IncomingLetter.id,IncomingLetter.fiscal_year,IncomingLetter.calendar_year,IncomingLetter.recv_no).order_by(IncomingLetter.id)).all()
    assert [tuple(r) for r in rows]==[(1,2569,2569,5),(2,2570,2569,5),(3,2570,None,90)]
    engine.dispose()

def test_import_excel_dates_and_export_calendar_year(env,monkeypatch,tmp_path):
    from openpyxl import Workbook,load_workbook
    from app.services import admin_io
    from app.models import IncomingLetter
    from app.tenancy import session_for
    monkeypatch.setattr(admin_io,'get_data_dir',lambda:tmp_path)
    wb=Workbook();ws=wb.active;ws.title='หนังสือรับ';ws.append(['นำเข้า']);ws.append(['หัวตาราง'])
    ws.append([7,datetime(2026,10,1),'A','01/10/2569','ต้นทาง','','นำเข้าวันที่ Excel',''])
    ws.append([8,'02/10/2569','B','','ต้นทาง','','นำเข้าวันที่ข้อความ',''])
    ws.append([9,None,'C','','ต้นทาง','','นำเข้าไม่ทราบวันที่',''])
    stream=BytesIO();wb.save(stream)
    with session_for(school()) as db:
        admin_io.import_admin_workbook(stream.getvalue(),db)
        rows=db.query(IncomingLetter).order_by(IncomingLetter.id).all()
        assert [r.calendar_year for r in rows]==[2569,2569,None]
    response=env.get('/admin/incoming/export.xlsx?year=2569')
    assert response.status_code==200
    exported=load_workbook(BytesIO(response.content),data_only=True)
    assert exported.sheetnames==['หนังสือรับ']
    assert exported.active['A1'].value=='หนังสือรับ ประจำปี พ.ศ. 2569'
    values=list(exported.active.values)
    assert len(values)==5 and values[3][0]==7 and values[4][0]==8
    assert 'ปีงบ' not in exported.active['A1'].value

def test_upload_confirmation_defaults_to_calendar_year(env,monkeypatch):
    import app.routers.admin as admin
    monkeypatch.setattr(admin,'_save_upload',lambda *a:'d'*32+'.pdf')
    monkeypatch.setattr(admin,'extract_letter_fields',lambda *a:{'subject':'ยืนยันนำเข้า','letter_date':None})
    response=env.post('/admin/incoming/upload',files={'file':('letter.pdf',b'%PDF-1.4\n%%EOF','application/pdf')})
    assert response.status_code==200
    assert f'name="calendar_year" value="{datetime.now().year+543}"' in response.text
    assert 'ปีปฏิทิน 1 มกราคม–31 ธันวาคม' in response.text
