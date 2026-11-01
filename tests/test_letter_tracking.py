"""Incoming letters, assignments, concurrency guards and attachment permissions."""
import time
from datetime import datetime, timedelta
import pytest
from tests.test_subsidy import env
from tests.test_letter_route import _login

def capture(name, page):
    import os
    from pathlib import Path
    folder=os.environ.get('LETTER_QA_CAPTURE')
    if folder:
        assert page.status_code==200
        (Path(folder)/(name+'.html')).write_text(page.text,encoding='utf-8')

@pytest.fixture(autouse=True)
def mail(monkeypatch):
    sent=[]
    monkeypatch.setattr('app.services.mailer.send_email',lambda *a,**kw: sent.append((a,kw)) or True)
    return sent

def school():
    from app.accounts import acc_session, Account
    with acc_session() as db: return db.query(Account).filter_by(username='demo').one().tenant_id

def people(tid):
    from app.tenancy import session_for
    from app.models import Person
    with session_for(tid) as db: return [p.id for p in db.query(Person).filter_by(active=True).order_by(Person.id).limit(3)]

def letter(env, **data):
    from app.models import IncomingLetter
    from app.tenancy import session_for
    subject='ทดสอบติดตามหนังสือ'
    response=env.post('/admin/incoming',data={'fiscal_year':2570,'recv_date':f"15/06/{data.get('fiscal_year',2570)}",'subject':subject,**data},follow_redirects=False)
    assert response.status_code==303
    with session_for(school()) as db: return db.query(IncomingLetter).filter_by(subject=subject).order_by(IncomingLetter.id.desc()).first().id

@pytest.mark.parametrize('action',['send','endorse','remind'])
def test_attached_letter_send_endorse_remind(env,monkeypatch,tmp_path,mail,action):
    from app.tenancy import session_for
    from app.models import IncomingLetter,LetterRecipient,Person
    import app.routers.admin as admin
    tid=school();pid=people(tid)[0]; name='a'*32+'.pdf'; content=b'%PDF-1.4\n%%EOF'
    (tmp_path/name).write_bytes(content);monkeypatch.setattr(admin,'_uploads_dir',lambda:tmp_path)
    with session_for(tid) as db:
        db.get(Person,pid).email='fixture@example.com'
        r=IncomingLetter(fiscal_year=2570,recv_no=7,file_path=name,subject='attachment',route_status='sent' if action=='remind' else 'director' if action=='endorse' else '')
        db.add(r);db.flush();rid=r.id
        if action=='remind':db.add(LetterRecipient(letter_id=rid,person_id=pid,name='test'))
        db.commit()
    response=env.post(f'/admin/incoming/{rid}/'+('route' if action=='send' else action),data={'action':action,'pid':[pid]},follow_redirects=False)
    assert response.status_code==303
    for _ in range(80):
        if mail:break
        time.sleep(.01)
    assert len(mail)==1
    assert mail[0][1]['attachments']==[('หนังสือ 7.pdf',content)]

def test_empty_invalid_recipient_and_historical_year(env):
    from app.tenancy import session_for
    from app.models import IncomingLetter
    tid=school();rid=letter(env,fiscal_year=2569)
    assert 'ทดสอบติดตามหนังสือ' in env.get('/admin/incoming?year=2569').text
    env.post(f'/admin/incoming/{rid}/route',data={'action':'director'})
    for data in ({},{'pid':['999999']}):
        r=env.post(f'/admin/incoming/{rid}/endorse',data=data,follow_redirects=False)
        assert r.status_code==303 and 'err=' in r.headers['location']
        with session_for(tid) as db:assert db.get(IncomingLetter,rid).route_status=='director'
    r=env.post(f'/admin/incoming/{rid}/delete',follow_redirects=False)
    assert r.headers['location']=='/admin/incoming?year=2569'

def test_recalled_letter_notifies_selected_recipients_once(env):
    from app.tenancy import session_for
    from app.models import IncomingLetter,Notification
    tid=school();p1,p2,_=people(tid);rid=letter(env)
    env.post(f'/admin/incoming/{rid}/route',data={'action':'director','pid':[p1,p2]})
    env.post(f'/admin/incoming/{rid}/route',data={'action':'recall'})
    env.post(f'/admin/incoming/{rid}/route',data={'action':'send','pid':[p1]})
    env.post(f'/admin/incoming/{rid}/route',data={'action':'send','pid':[p1]})
    with session_for(tid) as db:
        r=db.get(IncomingLetter,rid);assert [x.person_id for x in r.recipients]==[p1]
        assert db.query(Notification).filter_by(person_id=p1,link=f'/me/letters/{r.recipients[0].id}').count()==1

@pytest.mark.parametrize('change',[{'task_pid':[]},{'task_pid':[999999]},{'task_instruction':''},{'task_due':'99/99/2569'}])
def test_assignment_validation_preserves_unsent_letter(env,change):
    from app.tenancy import session_for
    from app.models import IncomingLetter,LetterTask
    tid=school();pid=people(tid)[0];rid=letter(env)
    form={'action':'send','pid':[pid],'work_mode':'task','task_pid':[pid],'task_instruction':'จัดเตรียมข้อมูล','task_due':'01/11/2569',**change}
    response=env.post(f'/admin/incoming/{rid}/route',data=form,follow_redirects=False)
    assert response.status_code==303 and 'err=' in response.headers['location']
    with session_for(tid) as db:
        assert not db.get(IncomingLetter,rid).route_status
        assert db.query(LetterTask).count()==0

def test_assignment_report_return_resubmit_complete_and_access(env,monkeypatch,tmp_path):
    from app.tenancy import session_for
    from app.accounts import acc_session,Account,hash_password,add_teacher_account
    from app.models import IncomingLetter,LetterRecipient,LetterTask,LetterTaskReport
    from app.services.nav import _director_alerts
    import app.routers.letter_tracking as tracker
    monkeypatch.setattr(tracker,'report_dir',lambda:tmp_path)
    tid=school();p1,p2,_=people(tid)
    a=add_teacher_account(tid,p1,'reportteach','Route!12345','ครูผู้รับผิดชอบ')
    b=add_teacher_account(tid,p2,'reportother','Route!12345','ครูผู้รับทราบ')
    with acc_session() as db:
        db.add(Account(username='dir-track',password_hash=hash_password('Route!12345'),tenant_id=tid,is_director=True,must_change_password=False,active=True));db.commit()
    teacher=_login(a['username'],'Route!12345');other=_login(b['username'],'Route!12345');director=_login('dir-track','Route!12345')
    rid=letter(env)
    form={'pid':[p1,p2],'work_mode':'task','task_pid':[p1],'task_instruction':'รวบรวมข้อมูลและสรุปผล','task_due':'01/01/2569'}
    r=env.post(f'/admin/incoming/{rid}/route',data={'action':'director',**form},follow_redirects=False);assert r.status_code==303
    assert 'ทดสอบติดตามหนังสือ' not in teacher.get('/me/letters').text
    preview=director.get(f'/admin/incoming/{rid}');assert preview.status_code==200 and 'รวบรวมข้อมูลและสรุปผล' in preview.text
    capture('director-assign',preview)
    assert 'value="01/01/2569"' in preview.text
    assert director.post(f'/admin/incoming/{rid}/endorse',data={'order':'ดำเนินการตามเสนอ',**form},follow_redirects=False).status_code==303
    with session_for(tid) as db:
        r=db.get(IncomingLetter,rid);rc=next(x for x in r.recipients if x.person_id==p1);rcid=rc.id;taskid=rc.task.id;other_rc=next(x.id for x in r.recipients if x.person_id==p2)
        assert r.route_status=='sent' and rc.task.version==0
    url=f'/me/letters/{rcid}';review=f'/admin/incoming/{rid}/tasks/{taskid}/review'
    assert 'งานที่มอบหมายถึงคุณ' in teacher.get(url).text
    capture('teacher-form',teacher.get(url))
    capture('tracking-overdue',director.get('/admin/incoming-tracking?year=2570'))
    assert director.post(f'/admin/incoming/{rid}/remind',follow_redirects=False).status_code==303
    assert 'งานที่มอบหมายถึงคุณ' not in other.get(f'/me/letters/{other_rc}').text
    assert other.post(url+'/report',data={'body':'wrong','version':0},follow_redirects=False).headers['location'].startswith('/me/letters?')
    # Unsupported files must leave task and filesystem untouched.
    bad=teacher.post(url+'/report',data={'body':'test','version':0},files={'attachment':('bad.html',b'<script>alert(1)</script>','text/html')},follow_redirects=False)
    assert 'err=' in bad.headers['location'] and not list(tmp_path.iterdir())
    content=b'%PDF-1.4\n%%EOF'
    sent=teacher.post(url+'/report',data={'body':'รวบรวมข้อมูลแล้ว','version':0},files={'attachment':('รายงาน.pdf',content,'application/pdf')},follow_redirects=False)
    assert sent.status_code==303 and 'msg=' in sent.headers['location']
    capture('director-review',director.get(f'/admin/incoming/{rid}'))
    capture('tracking-review',director.get('/admin/incoming-tracking?year=2570'))
    with session_for(tid) as db:
        task=db.get(LetterTask,taskid);reportid=task.reports[-1].id
        assert task.status=='submitted' and task.version==1 and not task.recipient.ack_at
        assert any('รายงานผลหนังสือรอตรวจ' in str(a) for a in _director_alerts(db))
    fileurl=url+f'/reports/{reportid}/file'
    assert teacher.get(fileurl).content==content
    assert other.get(fileurl,follow_redirects=False).status_code==303
    assert other.get(f'/admin/incoming/{rid}/reports/{reportid}/file').status_code==403
    assert director.get(f'/admin/incoming/{rid}/reports/{reportid}/file').content==content
    duplicate=teacher.post(url+'/report',data={'body':'duplicate','version':0},follow_redirects=False)
    assert 'err=' in duplicate.headers['location']
    assert teacher.post(review,data={'decision':'done','version':1,'report_id':reportid}).status_code==403
    assert 'err=' in director.post(review,data={'decision':'returned','version':1,'report_id':reportid},follow_redirects=False).headers['location']
    assert 'msg=' in director.post(review,data={'decision':'returned','review_note':'เพิ่มรายละเอียด','version':1,'report_id':reportid},follow_redirects=False).headers['location']
    assert 'เพิ่มรายละเอียด' in teacher.get(url).text
    assert 'err=' in teacher.post(url+'/report',data={'body':'stale','version':0},follow_redirects=False).headers['location']
    teacher.post(url+'/report',data={'body':'เพิ่มเติมรายละเอียดครบแล้ว','version':2},follow_redirects=False)
    with session_for(tid) as db:
        task=db.get(LetterTask,taskid);newreport=task.reports[-1].id
        assert len(task.reports)==2 and task.reports[0].review_note=='เพิ่มรายละเอียด'
    assert 'err=' in director.post(review,data={'decision':'done','version':3,'report_id':reportid},follow_redirects=False).headers['location']
    assert 'msg=' in director.post(review,data={'decision':'done','version':3,'report_id':newreport},follow_redirects=False).headers['location']
    assert 'ทดสอบติดตามหนังสือ' in director.get('/admin/incoming-tracking?year=2570').text
    assert 'ทดสอบติดตามหนังสือ' not in director.get('/admin/incoming-tracking?year=2570&status=review').text
    assert 'ทดสอบติดตามหนังสือ' not in director.get('/admin/incoming-tracking?year=2570&status=overdue').text
    assert teacher.get('/admin/incoming-tracking').status_code==403
    # Captured pages use isolated fixture data only.
    import os
    from pathlib import Path
    capture_folder=os.environ.get('LETTER_QA_CAPTURE')
    if capture_folder:
        folder=Path(capture_folder);folder.mkdir(parents=True,exist_ok=True)
        for filename,page in [('tracking',director.get('/admin/incoming-tracking?year=2570')),('director-detail',director.get(f'/admin/incoming/{rid}')),('teacher',teacher.get(url))]:
            assert page.status_code==200
            (folder/(filename+'.html')).write_text(page.text,encoding='utf-8')
    env.post(f'/admin/incoming/{rid}/delete')
    with session_for(tid) as db:
        assert db.query(LetterTask).count()==0 and db.query(LetterTaskReport).count()==0

def test_cross_school_cannot_open_reports(env,tmp_path,monkeypatch):
    from app.accounts import acc_session,Tenant,Account,hash_password
    from app.tenancy import session_for
    from app.models import IncomingLetter,LetterRecipient,LetterTask,LetterTaskReport
    import app.routers.letter_tracking as tracker
    monkeypatch.setattr(tracker,'report_dir',lambda:tmp_path)
    tid=school();pid=people(tid)[0];name='c'*32+'.pdf'
    (tmp_path/name).write_bytes(b'%PDF-private-school-A')
    with session_for(tid) as db:
        r=IncomingLetter(fiscal_year=2570,recv_no=1,route_status='sent');db.add(r);db.flush()
        rc=LetterRecipient(letter_id=r.id,person_id=pid,name='test');db.add(rc);db.flush()
        task=LetterTask(recipient_id=rc.id,instruction='secret');db.add(task);db.flush()
        report=LetterTaskReport(task_id=task.id,body='private',file_path=name,file_name='private.pdf');db.add(report);db.commit()
        rid,rcid,reportid=r.id,rc.id,report.id
    with acc_session() as db:
        t=Tenant(name='Other school',slug='other-school-track',active=True,plan='member',modules='admin');db.add(t);db.flush()
        db.add(Account(username='other-school-owner',password_hash=hash_password('Route!12345'),tenant_id=t.id,is_owner=True,must_change_password=False,active=True));db.commit()
    other=_login('other-school-owner','Route!12345')
    result=other.get(f'/admin/incoming/{rid}/reports/{reportid}/file',follow_redirects=False)
    assert result.status_code==303 and b'%PDF-private' not in result.content
    assert other.get(f'/me/letters/{rcid}/reports/{reportid}/file',follow_redirects=False).status_code==303

def test_existing_database_upgrade_keeps_acknowledgements(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base,init_school_db
    from app.models import IncomingLetter,LetterRecipient,LetterTask,Person
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    Base.metadata.create_all(engine,tables=[t for t in Base.metadata.sorted_tables if t.name not in ('letter_task','letter_task_report')])
    stamp=datetime(2026,10,1,9)
    with Session(engine) as db:
        p=Person(name='Existing teacher');db.add(p);db.flush()
        r=IncomingLetter(fiscal_year=2570,recv_no=1,route_status='sent');db.add(r);db.flush()
        rc=LetterRecipient(letter_id=r.id,person_id=p.id,name=p.name,ack_at=stamp);db.add(rc);db.commit();rcid=rc.id
    init_school_db(engine)
    with Session(engine) as db:
        rc=db.get(LetterRecipient,rcid)
        assert rc.ack_at==stamp and rc.task is None and db.query(LetterTask).count()==0
    engine.dispose()

def test_tracking_all_years_and_historical_year_filter(env):
    from app.tenancy import session_for
    from app.models import IncomingLetter
    with session_for(school()) as db:
        db.add_all([IncomingLetter(fiscal_year=2569,calendar_year=2569,recv_no=9,route_status='sent',subject='งานค้างปีก่อน'),
                    IncomingLetter(fiscal_year=2570,calendar_year=2570,recv_no=1,route_status='sent',subject='งานปีปัจจุบัน')])
        db.commit()
    page=env.get('/admin/incoming-tracking?year=0').text
    assert 'งานค้างปีก่อน' in page and 'งานปีปัจจุบัน' in page
    page=env.get('/admin/incoming-tracking?year=2569').text
    assert 'งานค้างปีก่อน' in page and 'งานปีปัจจุบัน' not in page
    page=env.get('/admin/incoming-tracking?year=0&q=งานค้าง').text
    assert 'งานค้างปีก่อน' in page and 'งานปีปัจจุบัน' not in page
