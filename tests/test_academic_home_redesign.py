from pathlib import Path
import os
import re
from tests.test_subsidy import env
from app.models import AcadClass,AcadStudent,AcadSubject,AcadTeaching,Person,AcadYearSetting

def test_owner_home_keeps_real_counts_progress_and_ten_menus(env):
 import app.tenancy as tn
 with tn.session_for(next(iter(tn._engines))) as db:
  teacher=Person(name='ครูตัวอย่าง');db.add(teacher);db.flush()
  for level in ['ป.1','ป.6']:
   c=AcadClass(year=2569,level=level,room='1',homeroom_id=teacher.id);db.add(c);db.flush()
   for n in range(20):db.add(AcadStudent(class_id=c.id,name=f'นักเรียนตัวอย่าง {n+1}',seq=n+1))
   for n,name in enumerate(['ภาษาไทย','คณิตศาสตร์','วิทยาศาสตร์','ภาษาอังกฤษ','สังคมศึกษา']):
    sub=AcadSubject(year=2569,level=level,code=f'ท{n+1}',name=name,hours=200);db.add(sub);db.flush()
    db.add(AcadTeaching(class_id=c.id,subject_id=sub.id,teacher_id=teacher.id))
  db.commit()
 res=env.get('/academic?year=2569&term=2');assert res.status_code==200
 links=re.findall(r'<a class="ah-menu" href="([^"]+)"',res.text)
 assert re.findall(r'<strong>(\d+) <small>(ห้อง|คน|วิชา)</small>',res.text)==[('2','ห้อง'),('40','คน'),('10','วิชา')]
 assert len(links)==10
 assert res.text.split('<table class="dash-table">')[1].split('</table>')[0].count('<tr>')==3
 assert 'class="seg-btn on" href="/academic?year=2569&term=2"' in res.text
 assert 'id="ah-year" name="year"' in res.text
 assert 'href="/guide#video-academic"' in res.text
 for route in ['classes','subjects','calendar','grades','eval','pp7','timetable','lesson-plans','supervision','teacher-accounts']:
  assert any(h.split('?')[0]=='/academic/'+route for h in links)
 assert 'id="setup-acad"' in res.text
 Path(os.environ['ACADEMIC_HOME_CAPTURE'],'owner.html').write_text(res.text,encoding='utf-8')

def test_teacher_home_keeps_role_specific_tasks_and_hides_setup(env,monkeypatch):
 from app.routers import academic
 class Teacher:
  is_teacher=True
  class_ids,subject_ids,teach_pairs=set(),set(),set()
 monkeypatch.setattr(academic,'_scope',lambda *a:Teacher())
 monkeypatch.setattr(academic,'_teacher_todo',lambda *a:dict(items=[],homerooms=[],month=11,month_name='พฤศจิกายน'))
 res=env.get('/academic?year=2569&term=1');assert res.status_code==200
 links=re.findall(r'<a class="ah-menu" href="([^"]+)"',res.text)
 assert 'id="setup-acad"' not in res.text
 assert 'class="card ah-progress"' not in res.text
 assert len(links)==8
 assert '/academic/teacher-accounts' not in links
 for href in ['/me/leave','/me/travel','/general/assembly','/academic/attendance?mode=overall']:
  assert href in links
 assert 'งานของฉัน' in res.text
 Path(os.environ['ACADEMIC_HOME_CAPTURE'],'teacher.html').write_text(res.text,encoding='utf-8')

def test_empty_academic_home_still_has_working_navigation(env):
 res=env.get('/academic?year=2588');assert res.status_code==200
 assert '0 <small>ห้อง' in res.text
 Path(os.environ['ACADEMIC_HOME_CAPTURE'],'empty.html').write_text(res.text,encoding='utf-8')
