import os
from pathlib import Path
from datetime import datetime,timedelta
from tests.test_subsidy import env
from app.models import IncomingLetter,LetterRecipient,LetterTask,Person,School
from app.tenancy import session_for
from app.services.home_dashboard import build

def seed(env):
 import app.tenancy as tn
 tid=next(iter(tn._engines))
 with session_for(tid) as s:
  p=Person(name='ครูหนึ่ง');other=Person(name='ครูสอง');s.add_all([p,other]);s.flush()
  a=IncomingLetter(fiscal_year=2570,calendar_year=2569,subject='หนังสือถึงครูหนึ่ง',route_status='sent')
  b=IncomingLetter(fiscal_year=2570,calendar_year=2569,subject='ความลับครูสอง',route_status='sent')
  c=IncomingLetter(fiscal_year=2570,calendar_year=2569,subject='ฉบับรอสั่งการ',route_status='director')
  s.add_all([a,b,c]);s.flush()
  rc=LetterRecipient(letter_id=a.id,person_id=p.id,name=p.name)
  rc2=LetterRecipient(letter_id=a.id,person_id=other.id,name=other.name)
  rc3=LetterRecipient(letter_id=b.id,person_id=other.id,name=other.name)
  s.add_all([rc,rc2,rc3]);s.flush();s.add(LetterTask(recipient_id=rc.id,instruction='ส่งรายงาน',due_at=datetime.now()-timedelta(days=2),status='pending'))
  s.commit();return tid,p.id,other.id,rc.id

def capture(name,text):
 if os.environ.get('HOME_CAPTURE'):(Path(os.environ['HOME_CAPTURE'])/(name+'.html')).write_text(text,encoding='utf-8')

def test_owner_counts_letters_not_people_and_home_links(env):
 tid,p,other,rc=seed(env)
 with session_for(tid) as s:s.query(School).first().approval_on=True;s.commit()
 page=env.get('/');assert page.status_code==200,page.text[:200]
 assert 'ติดตามหนังสือรับ' in page.text and 'อัปเดตระบบล่าสุด' in page.text
 capture('admin-home',page.text)
 with session_for(tid) as s:
  h=build(s,dict(tid=tid,owner=True,uid=1))
  counts=dict(h['letter_counts']);assert counts['ยังมีผู้ไม่รับทราบ']==2 and counts['เลยกำหนดรายงานผล']==1
 page=env.get('/home/letters?group=unacked');assert page.status_code==200 and 'รับทราบแล้ว 0/2 คน' in page.text
 assert env.get('/system-updates').status_code==200
 with session_for(tid) as s:s.query(School).first().approval_on=False;s.commit()
 assert 'ติดตามการอนุมัติ' not in env.get('/').text
 for status in ['pending','approved','returned','stale']:assert env.get('/home/approvals?status='+status).status_code==200

def test_teacher_home_and_results_are_personal(env,monkeypatch):
 import app.main as main
 from app.models import Procurement,Approval
 from app.services import approval as ap
 tid,p,other,rc=seed(env)
 base=main.get_account_access(1)
 monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':False,'person_id':p,'modules':'academic'})
 with session_for(tid) as s:
  school=s.query(School).first();school.approval_on=True
  pr=Procurement(subject='เรื่องส่วนตัวของคนอื่น',fiscal_year=2570,proc_type='ซื้อ');s.add(pr);s.flush()
  ap.send(s,'proc_order',pr.id,'ครูสอง',by_pid=other);s.commit()
 page=env.get('/');assert page.status_code==200,page.text[:200]
 assert 'หนังสือถึงครูหนึ่ง' in page.text and 'ความลับครูสอง' not in page.text
 assert 'เรื่องส่วนตัวของคนอื่น' not in page.text and f'/me/letters/{rc}' in page.text
 capture('teacher-home',page.text)
 assert 'เรื่องส่วนตัวของคนอื่น' not in env.get('/home/approvals').text
 assert env.get('/home/letters',follow_redirects=False).headers['location']=='/me/letters'
 with session_for(tid) as s:
  h=build(s,dict(tid=tid,owner=False,uid=1,person_id=p,mods='academic'))
  assert dict(h['letter_counts'])=={'หนังสือรอรับทราบ':1,'งานรอรายงานผล':1,'งานเลยกำหนด':1}
  s.get(LetterRecipient,rc).ack_at=datetime.now();s.get(LetterRecipient,rc).task.status='done';s.commit()
 page=env.get('/');assert 'ไม่มีงานค้าง' in page.text

def test_unassigned_staff_cannot_read_school_letters(env,monkeypatch):
 import app.main as main
 seed(env);base=main.get_account_access(1)
 monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':False,'person_id':None,'modules':'finance'})
 page=env.get('/');assert page.status_code==200
 assert 'ฉบับรอสั่งการ' not in page.text and 'หนังสือถึงครูหนึ่ง' not in page.text
 assert env.get('/home/letters').status_code==403


def test_approval_summary_counts_latest_stage_and_detects_edit_after_approval(env):
 from app.models import Procurement,Approval
 from app.services import approval as ap
 tid,p,other,rc=seed(env)
 with session_for(tid) as s:
  pr=Procurement(subject='งบจัดซื้อ',fiscal_year=2570,proc_type='ซื้อ',total_amount=100);s.add(pr);s.flush()
  old=Approval(kind='proc_order',ref_id=pr.id,status='approved',fingerprint=ap.fingerprint('proc_order',pr),decided_at=datetime.now())
  s.add(old);s.flush()
  latest=Approval(kind='proc_order',ref_id=pr.id,status='pending',fingerprint=ap.fingerprint('proc_order',pr));s.add(latest);s.commit()
  sess=dict(tid=tid,owner=True,uid=1)
  h=build(s,sess);assert len(h['approval']['pending'])==1 and not h['approval']['approved']
  latest.status='approved';latest.decided_at=datetime.now();s.commit()
  assert len(build(s,sess)['approval']['approved'])==1
  pr.total_amount=200;s.commit()
  h=build(s,sess);assert len(h['approval']['stale'])==1 and not h['approval']['approved']
