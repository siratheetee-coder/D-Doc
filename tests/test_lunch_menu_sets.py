import os
from pathlib import Path
from datetime import datetime,date
import pytest
from starlette.datastructures import FormData
from tests.test_subsidy import env,db
from app.models import LunchProgram,LunchMenu,LunchMenuSet,AcadCalendar
from app.services import lunch_menu_sets as svc

def sets(db):
 p=LunchProgram(year=2569,operate_mode='hire');db.add(p);db.flush()
 a=svc.save(db,LunchMenuSet(),'ชุด A',[dict(main='A1',dessert='กล้วย',note='',groups='1,2'),dict(main='A2',dessert='ส้ม',note='',groups='')])
 b=svc.save(db,LunchMenuSet(),'ชุด B',[dict(main='B1',dessert='ฝรั่ง',note='',groups='')])
 db.add(AcadCalendar(year=2569,month=11,days_csv='2,3,5,6,7,9,10,11,12'))
 db.add(LunchMenu(program_id=p.id,date=datetime(2026,11,3),main='เมนูเดิม',dessert='เดิม',groups='3'))
 db.commit();return p,a,b

def test_set_cycle_uses_school_days_and_preserves_existing_by_default(db):
 p,a,b=sets(db);ids=[str(a.id),str(b.id)]
 plan=svc.preview(db,p,ids,'02/11/2569','12/11/2569','skip')
 assert plan['total']==9 and plan['created']==8 and plan['skipped']==1
 assert date(2026,11,7) in [r['date'] for r in plan['rows']] and date(2026,11,4) not in [r['date'] for r in plan['rows']]
 svc.apply(db,p,ids,'02/11/2569','12/11/2569','skip',plan['token'],False);db.commit()
 rows=db.query(LunchMenu).filter_by(program_id=p.id).order_by(LunchMenu.date).all()
 assert [r.main for r in rows]==['A1','เมนูเดิม','B1','A1','A2','B1','A1','A2','B1']
 assert rows[1].groups=='3' and rows[0].groups=='1,2'
 a.items[0].main='เปลี่ยนชุด';db.commit();assert rows[0].main=='A1'

def test_replace_requires_review_and_source_or_calendar_changes_invalidate_preview(db):
 p,a,b=sets(db);ids=[str(a.id)]
 plan=svc.preview(db,p,ids,'02/11/2569','12/11/2569','replace')
 with pytest.raises(ValueError,match='ยืนยัน'):svc.apply(db,p,ids,'02/11/2569','12/11/2569','replace',plan['token'],False)
 a.items[0].main='เปลี่ยน';db.commit()
 with pytest.raises(ValueError,match='เปลี่ยน'):svc.apply(db,p,ids,'02/11/2569','12/11/2569','replace',plan['token'],True)
 fresh=svc.preview(db,p,ids,'02/11/2569','12/11/2569','replace')
 svc.apply(db,p,ids,'02/11/2569','12/11/2569','replace',fresh['token'],True);db.commit()
 assert db.query(LunchMenu).filter_by(program_id=p.id,date=datetime(2026,11,3)).one().main=='A2'
 fresh=svc.preview(db,p,ids,'02/11/2569','12/11/2569','skip')
 db.query(AcadCalendar).one().days_csv='2,3,5';db.commit()
 with pytest.raises(ValueError,match='เปลี่ยน'):svc.apply(db,p,ids,'02/11/2569','12/11/2569','skip',fresh['token'],False)

def test_repeated_application_and_duplicate_day_are_safe(db):
 p,a,b=sets(db);ids=[str(a.id)]
 plan=svc.preview(db,p,ids,'02/11/2569','12/11/2569','skip');svc.apply(db,p,ids,'02/11/2569','12/11/2569','skip',plan['token'],False);db.commit()
 with pytest.raises(ValueError):svc.apply(db,p,ids,'02/11/2569','12/11/2569','skip',plan['token'],False)
 plan=svc.preview(db,p,ids,'02/11/2569','12/11/2569','skip');assert plan['created']==0
 db.add(LunchMenu(program_id=p.id,date=datetime(2026,11,3),main='ซ้ำ'));db.commit()
 with pytest.raises(ValueError,match='ซ้ำ'):svc.preview(db,p,ids,'02/11/2569','12/11/2569','replace')

@pytest.mark.parametrize('ids,start,end,mode',[([], '02/11/2569','12/11/2569','skip'),(['9999'],'02/11/2569','12/11/2569','skip'),(['1'],'12/11/2569','02/11/2569','skip'),(['1'],'02/11/2568','12/11/2569','skip'),(['1'],'02/11/2569','12/11/2569','bad')])
def test_invalid_plans_do_not_write(db,ids,start,end,mode):
 p,a,b=sets(db)
 with pytest.raises(ValueError):svc.preview(db,p,ids,start,end,mode)
 assert db.query(LunchMenu).count()==1

def test_validation_keeps_exact_number_of_days():
 with pytest.raises(ValueError):svc.fields(FormData([('name','A'),('days','2'),('main','A1'),('dessert','')]))
 with pytest.raises(ValueError):svc.fields(FormData([('name','A'),('days','1'),('main',''),('dessert','')]))
 name,rows=svc.fields(FormData([('name','A'),('days','1'),('main','ข้าว'),('dessert',''),('groups_0','2')]))
 assert rows[0]['groups']=='2'

def test_http_library_create_edit_copy_preview_and_apply(env):
 import app.tenancy as tn
 tid=next(iter(tn._engines))
 with tn.session_for(tid) as s:p,a,b=sets(s);pid,aid,bid=p.id,a.id,b.id
 for url in [f'/lunch/{pid}/menu?d=02/11/2569',f'/lunch/{pid}/menu/sets',f'/lunch/{pid}/menu/sets?edit={aid}',f'/lunch/{pid}/menu/sets?new=1']:
  response=env.get(url);assert response.status_code==200,(url,response.text[:200])
 response=env.post(f'/lunch/{pid}/menu/sets/{aid}/copy',follow_redirects=False);assert response.status_code==303
 with tn.session_for(tid) as s:
  copy=s.query(LunchMenuSet).order_by(LunchMenuSet.id.desc()).first();cid=copy.id;assert cid!=aid and [x.main for x in copy.items]==['A1','A2']
 response=env.post(f'/lunch/{pid}/menu/sets/save',data={'set_id':cid,'name':'สำเนาใหม่','days':2,'main':['C1','C2'],'dessert':['','']},follow_redirects=False)
 assert response.status_code==303,response.text
 with tn.session_for(tid) as s:assert s.get(LunchMenuSet,aid).items[0].main=='A1'
 bad=env.post(f'/lunch/{pid}/menu/sets/save',data={'name':'ยังกรอกไม่ครบ','days':2,'main':['C1',''],'dessert':['','']});assert bad.status_code==422 and 'C1' in bad.text
 form={'set_ids':[str(aid),str(bid)],'start':'02/11/2569','end':'12/11/2569','mode':'skip'}
 response=env.post(f'/lunch/{pid}/menu/sets/use',data=form);assert response.status_code==200,response.text[:200]
 import re
 token=re.search('name="token" value="([^"]+)"',response.text).group(1)
 assert 'ข้ามเมนูเดิม' in response.text
 if os.environ.get('MENU_CAPTURE'):
  out=Path(os.environ['MENU_CAPTURE']);(out/'preview.html').write_text(response.text,encoding='utf-8')
 response=env.post(f'/lunch/{pid}/menu/sets/use',data={**form,'token':token,'action':'apply'},follow_redirects=False);assert response.status_code==303
 with tn.session_for(tid) as s:assert s.query(LunchMenu).filter_by(program_id=pid).count()==9
 if os.environ.get('MENU_CAPTURE'):
  out=Path(os.environ['MENU_CAPTURE'])
  for name,url in [('daily',f'/lunch/{pid}/menu?d=02/11/2569'),('library',f'/lunch/{pid}/menu/sets?selected={aid}'),('editor',f'/lunch/{pid}/menu/sets?edit={aid}'),('apply',f'/lunch/{pid}/menu/sets?use={aid}')]:
   page=env.get(url);assert page.status_code==200;(out/(name+'.html')).write_text(page.text,encoding='utf-8')
  (out/'ids.txt').write_text(str(pid),encoding='utf-8')

def test_daily_save_is_an_upsert_and_groups_are_not_preselected(env):
 import app.tenancy as tn
 tid=next(iter(tn._engines))
 with tn.session_for(tid) as s:p,a,b=sets(s);pid=p.id
 data=dict(date='02/11/2569',main='ข้าวใหม่',dessert='ผลไม้')
 for _ in range(2):assert env.post(f'/lunch/{pid}/menu/day',data=data,follow_redirects=False).status_code==303
 with tn.session_for(tid) as s:
  rows=s.query(LunchMenu).filter_by(program_id=pid,date=datetime(2026,11,2)).all();assert len(rows)==1 and rows[0].groups==''
 assert env.post(f'/lunch/{pid}/menu/day',data={**data,'date':'04/11/2569'}).status_code==422

def test_sets_from_another_school_are_not_available(db):
 from sqlalchemy import create_engine
 from sqlalchemy.orm import Session
 from app.database import Base
 p,a,b=sets(db);engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
 with Session(engine) as other:
  with pytest.raises(ValueError,match='ไม่พบชุด'):svc.preview(other,p,[str(a.id)],'02/11/2569','12/11/2569','skip')
 engine.dispose()


def test_old_dateless_menu_is_preserved_and_other_program_cannot_be_edited(env):
 import app.tenancy as tn
 tid=next(iter(tn._engines))
 with tn.session_for(tid) as s:
  p,a,b=sets(s);pid=p.id
  old=LunchMenu(program_id=pid,main='เมนูเก่าไม่มีวัน',groups='1');s.add(old)
  other=LunchProgram(year=2569);s.add(other);s.commit();oid,otherid=old.id,other.id
 page=env.get(f'/lunch/{pid}/menu?edit={oid}')
 assert page.status_code==200 and 'แก้เมนูเดิมที่ยังไม่ระบุวัน' in page.text
 assert f'/lunch/menu/{oid}/update' in page.text
 assert env.post(f'/lunch/menu/{oid}/update',data={'date':'','main':'เมนูเก่าแก้แล้ว','groups':'1'},follow_redirects=False).status_code==303
 assert env.post(f'/lunch/{otherid}/menu/day',data={'mid':oid,'date':'02/11/2569','main':'ผิดโครงการ'}).status_code==404
 with tn.session_for(tid) as s:assert s.get(LunchMenu,oid).date is None and s.get(LunchMenu,oid).main=='เมนูเก่าแก้แล้ว'

def test_new_menu_set_routes_respect_module_and_director_readonly_permissions(env,monkeypatch):
 import app.main as main
 import app.tenancy as tn
 tid=next(iter(tn._engines))
 with tn.session_for(tid) as s:p,a,b=sets(s);pid,aid=p.id,a.id
 base=main.get_account_access(1)
 monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':False,'modules':'finance','person_id':None})
 assert env.get(f'/lunch/{pid}/menu/sets').status_code==403
 assert env.post(f'/lunch/{pid}/menu/sets/{aid}/copy').status_code==403
 monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':True,'modules':'lunch','person_id':None})
 assert env.get(f'/lunch/{pid}/menu/sets').status_code==200
 assert env.post(f'/lunch/{pid}/menu/sets/{aid}/copy').status_code==403


def test_ten_day_A_and_ten_day_B_repeat_over_forty_school_days(db):
 from app.services import school_calendar as cal
 p,a,b=sets(db);db.query(LunchMenu).filter_by(program_id=p.id).delete();db.commit()
 a=svc.save(db,LunchMenuSet(),'ชุด 10 วัน A',[dict(main='A'+str(i+1),dessert='',note='',groups='') for i in range(10)])
 b=svc.save(db,LunchMenuSet(),'ชุด 10 วัน B',[dict(main='B'+str(i+1),dessert='',note='',groups='') for i in range(10)]);db.commit()
 dates=[d for d in cal.open_dates(db,p.year) if d>=date(2026,11,2)][:40]
 be=lambda d:f'{d.day:02}/{d.month:02}/{d.year+543}'
 ids=[str(a.id),str(b.id)];start,end=be(dates[0]),be(dates[-1])
 plan=svc.preview(db,p,ids,start,end,'skip');assert plan['created']==40
 svc.apply(db,p,ids,start,end,'skip',plan['token'],False);db.commit()
 expected=(['A'+str(i+1) for i in range(10)]+['B'+str(i+1) for i in range(10)])*2
 assert [m.main for m in db.query(LunchMenu).filter_by(program_id=p.id).order_by(LunchMenu.date)]==expected
