from datetime import datetime,date
from pathlib import Path
import os,json
import pytest
from tests.test_subsidy import env,db
from app.models import SchoolEvent,AcadClass,AcadStudent,Person,AcadCalendar,AcadHoliday,LunchProgram,LunchClass,LunchHireRound,LunchInstallment,FinanceTxn
from app.services import school_events as ev,school_calendar as sc

def session():
 import app.tenancy as tn
 return tn.session_for(next(iter(tn._engines)))

def form(**kw):
 return dict(year='2569',title='กีฬาสี',kind='activity',start_date='20/11/2569',end_date='20/11/2569',all_day='1',audience='school',location='สนามโรงเรียน',organizer='ครูตัวอย่าง',note='กิจกรรมร่วมกัน',**kw)

def make_event(client,values=None):
 res=client.post('/settings/calendar/events/save',data=values or form(),follow_redirects=False)
 assert res.status_code==303,res.text[:150]
 from urllib.parse import parse_qs,urlparse
 return int(parse_qs(urlparse(res.headers['location']).query)['event'][0])

def add_targets():
 with session() as s:
  p=Person(name='ครูประจำชั้น');other=Person(name='ครูอีกห้อง');s.add_all([p,other]);s.flush()
  a=AcadClass(year=2569,level='ป.6',room='1',homeroom_id=p.id);b=AcadClass(year=2569,level='ป.1',room='1',homeroom_id=other.id);s.add_all([a,b]);s.flush()
  s.add(AcadStudent(class_id=a.id,name='นักเรียนตัวอย่าง',seq=1));s.commit();return p.id,a.id,b.id

def as_teacher(monkeypatch,pid):
 import app.main as main
 base=main.get_account_access(1)
 monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':False,'person_id':pid,'modules':'academic'})

def test_crud_shared_routes_and_no_day_or_money_changes(env):
 with session() as s:
  s.add(AcadCalendar(year=2569,month=11,days_csv='18,19,20'));s.commit()
  before=(s.query(AcadCalendar).first().days_csv,s.query(AcadHoliday).count(),s.query(FinanceTxn).count(),s.query(LunchInstallment).count())
 eid=make_event(env)
 for base in ['/academic/calendar','/settings/calendar']:
  r=env.get(f'{base}?year=2569&month=11&event={eid}')
  assert r.status_code==200 and 'กีฬาสี' in r.text
 with session() as s:
  row=s.get(SchoolEvent,eid);assert row.version==1
  assert before==(s.query(AcadCalendar).first().days_csv,s.query(AcadHoliday).count(),s.query(FinanceTxn).count(),s.query(LunchInstallment).count())
 data=form();data.update(event_id=eid,version=1,title='กีฬาสีปรับเวลา')
 r=env.post('/academic/calendar/events/save',data=data,follow_redirects=False);assert r.status_code==303
 stale=env.post('/settings/calendar/events/save',data=data,follow_redirects=False)
 assert stale.status_code==400 and 'ถูกแก้ไขแล้ว' in stale.text and 'กีฬาสีปรับเวลา' in stale.text
 assert env.post(f'/settings/calendar/events/{eid}/delete',data={'version':1},follow_redirects=False).status_code==409
 assert env.post(f'/academic/calendar/events/{eid}/delete',data={'version':2},follow_redirects=False).status_code==303
 with session() as s:assert not s.get(SchoolEvent,eid) and s.query(AcadCalendar).first().days_csv=='18,19,20'

@pytest.mark.parametrize('patch',[{'title':''},{'start_date':'31/11/2569'},{'end_date':'19/11/2569'},{'start_date':'30/04/2569'},{'end_date':'01/05/2570'},{'kind':'holiday'},{'audience':'class','classes':['99999']},{'audience':'level','levels':['ม.9']},{'all_day':'','start_time':'15:00','end_time':'14:00'}])
def test_invalid_activity_preserves_form_and_does_not_change_calendar(env,patch):
 data=form();data.update(patch)
 r=env.post('/settings/calendar/events/save',data=data,follow_redirects=False)
 assert r.status_code==400 and 'id="se-editor"' in r.text and 'ข้อมูลที่กรอกยังอยู่' in r.text
 with session() as s:assert s.query(SchoolEvent).count()==0

def test_teacher_visibility_and_readonly_home(env,monkeypatch):
 pid,cid,other=add_targets()
 public=make_event(env)
 from datetime import timedelta
 from app.thai_utils import thai_today
 d0=thai_today();d1=d0+timedelta(days=1)  # กิจกรรมต้องยังไม่ผ่าน ถึงจะขึ้น 'กิจกรรมใกล้ถึง' หน้าหลัก
 data=form();data.update(title='ทัศนศึกษาห้องเรา',audience='class',classes=[str(cid)],start_date=f'{d0.day:02d}/{d0.month:02d}/{d0.year+543}',end_date=f'{d1.day:02d}/{d1.month:02d}/{d1.year+543}');own=make_event(env,data)
 data=form();data.update(title='กิจกรรมห้องอื่นเท่านั้น',audience='class',classes=[str(other)]);hidden=make_event(env,data)
 data=form();data.update(title='ประชุมระดับ ป.6',audience='level',levels=['ป.6']);level=make_event(env,data)
 as_teacher(monkeypatch,pid)
 page=env.get(f'/academic/calendar?year=2569&month={d0.month}');assert page.status_code==200
 assert 'ทัศนศึกษาห้องเรา' in page.text and 'ประชุมระดับ ป.6' in page.text and 'กิจกรรมห้องอื่นเท่านั้น' not in page.text
 assert 'id="se-editor"' not in page.text
 assert env.get(f'/academic/calendar?year=2569&event={hidden}').status_code==404
 assert env.post('/settings/calendar/events/save',data=form()).status_code==403
 assert env.post(f'/academic/calendar/events/{own}/delete',data={'version':1}).status_code==403
 home=env.get('/');assert home.status_code==200 and 'กิจกรรมห้องอื่นเท่านั้น' not in home.text and 'ทัศนศึกษาห้องเรา' in home.text
 assert home.text.index('id="sc-widget-title"')>home.text.index('class="home-columns"')
 out=Path(os.environ['SCHOOL_EVENTS_CAPTURE']);(out/'teacher-home.html').write_text(home.text,encoding='utf-8');(out/'teacher-calendar.html').write_text(page.text,encoding='utf-8')

def test_capture_calendar_and_timed_multiday_event(env):
 add_targets()
 eid=make_event(env)
 data=form();data.update(title='ประชุมผู้ปกครอง',kind='meeting',all_day='',start_date='12/11/2569',end_date='12/11/2569',start_time='13:00',end_time='15:00');make_event(env,data)
 data=form();data.update(title='กิจกรรมต่อเนื่อง',start_date='29/12/2569',end_date='02/01/2570');long=make_event(env,data)
 with session() as s:
  d=ev.payload(s.get(SchoolEvent,long),s.query(AcadClass).all());assert d['end']=='2027-01-02'
 for name,url in [('calendar',f'/settings/calendar?year=2569&month=11&event={eid}'),('days','/settings/calendar?year=2569&view=days')]:
  r=env.get(url);assert r.status_code==200
  Path(os.environ['SCHOOL_EVENTS_CAPTURE'],name+'.html').write_text(r.text,encoding='utf-8')

def test_other_school_event_ids_and_targets_are_not_readable(env):
 import app.tenancy as tn
 with tn.session_for(999) as s:
  s.add(SchoolEvent(id=88888,year=2569,title='กิจกรรมโรงเรียนอื่น',start_at=datetime(2026,11,20),end_at=datetime(2026,11,20)));s.commit()
 assert env.get('/settings/calendar?year=2569&event=88888').status_code==404
 assert env.post('/settings/calendar/events/save',data={**form(),'event_id':88888,'version':1}).status_code==404
 assert env.post('/settings/calendar/events/88888/delete',data={'version':1}).status_code==404


def test_dense_day_filter_fixture_and_html_are_safe(env):
 for title,kind in [('<img src=x onerror=alert(1)>','activity'),('กิจกรรมที่สอง','activity'),('ประชุมลำดับที่สาม','meeting')]:
  data=form();data.update(title=title,kind=kind);make_event(env,data)
 page=env.get('/settings/calendar?year=2569&month=11');assert page.status_code==200
 assert '<img src=x onerror=alert(1)>' not in page.text
 Path(os.environ['SCHOOL_EVENTS_CAPTURE'],'dense.html').write_text(page.text,encoding='utf-8')
 assert env.get('/settings/calendar?year=2569&month=0').status_code==400
 assert env.get('/settings/calendar?year=2569&month=13').status_code==400
