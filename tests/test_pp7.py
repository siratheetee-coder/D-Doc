import json
import pytest
from tests.test_subsidy import env, db
from app.models import Student,AcadStudent,AcadClass,AcadSubject,AcadScore,AcadCertificate
from app.services.pp7 import history,average


def seed(db):
    central=Student(name='นักเรียนตัวอย่าง',student_no='1001');db.add(central);db.flush()
    out=[]
    for year,level in [(2568,'ป.1'),(2569,'ป.2')]:
        c=AcadClass(year=year,level=level,room='1');db.add(c);db.flush()
        s=AcadStudent(class_id=c.id,student_id=central.id,name=central.name,student_no='1001');db.add(s);db.flush()
        sub=AcadSubject(year=year,level=level,name='ภาษาไทย',code='ท11101',hours=200,term=0);db.add(sub);db.flush()
        db.add(AcadScore(acad_student_id=s.id,subject_id=sub.id,term=0,grade='4'))
        out.append(s)
    db.commit();return out


def test_history_identity_and_incomplete(db):
    old,s=seed(db)
    groups,warnings,_=history(db,s,2568,2569)
    assert len(groups)==2 and not warnings
    assert average(groups[0]['rows'])==4
    db.query(AcadScore).filter_by(acad_student_id=old.id).update({'term':1});db.commit()
    groups,warnings,_=history(db,s,2568,2569)
    assert warnings and groups[0]['rows'][0]['grade']==''
    assert average(groups[0]['rows']) is None
    s.student_id=None;db.commit()
    assert len(history(db,s,2568,2569)[0])==1


def test_issue_snapshot_and_download(env):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        _,s=seed(db);aid=s.id
    page=env.get(f'/academic/student/{aid}/pp7?start=2568&end=2569')
    assert page.status_code==200 and 'ภาษาไทย' in page.text
    form=dict(start=2568,end=2569,number='1/2569',registrar='นายทะเบียนทดสอบ',issued='10/10/2569',valid_days=30)
    import re
    form['source_token']=re.search('name="source_token" value="([^"]+)"',page.text)[1]
    response=env.post(f'/academic/student/{aid}/pp7',data=form,follow_redirects=False)
    assert response.status_code==303,response.text
    with tn.session_for(tid) as db:
        c=db.query(AcadCertificate).one();cid=c.id
        assert json.loads(c.payload)['groups'][0]['rows'][0]['grade']=='4'
        db.query(AcadScore).update({'grade':'2'});db.commit()
        assert json.loads(c.payload)['groups'][0]['rows'][0]['grade']=='4'
    download=env.get(f'/academic/pp7/{cid}.docx')
    assert download.status_code==200 and download.content[:2]==b'PK'
    assert env.post(f'/academic/student/{aid}/pp7',data=form).status_code==400
    fresh=env.get(f'/academic/student/{aid}/pp7?start=2568&end=2569')
    form['source_token']=re.search('name="source_token" value="([^"]+)"',fresh.text)[1]
    assert env.post(f'/academic/student/{aid}/pp7',data=form).status_code==409
    assert env.get(f'/academic/student/{aid}/pp7?start=2570&end=2568').status_code==400


def test_secondary_uses_credit_and_separate_terms(db):
    c=AcadClass(year=2569,level='ม.1',room='1');db.add(c);db.flush()
    s=AcadStudent(class_id=c.id,name='นักเรียนมัธยม');db.add(s);db.flush()
    for term in [1,2]:
        sub=AcadSubject(year=2569,level='ม.1',name='ภาษาไทย',code='ท21101',credit=1.5,hours=60,term=term)
        db.add(sub);db.flush()
        db.add(AcadScore(acad_student_id=s.id,subject_id=sub.id,term=term,grade='3.5'))
    db.commit()
    groups,_,_=history(db,s,2569,2569)
    assert [g['term'] for g in groups]==[1,2]
    assert all(g['unit']=='หน่วยกิต' and g['rows'][0]['weight']==1.5 for g in groups)


def test_average_does_not_round_up_or_hide_incomplete():
    rows=[dict(grade='4',weight=1),dict(grade='3',weight=2)]
    assert average(rows)==3.33
    assert average([dict(grade='ร',weight=1)]) is None
    assert average([dict(grade='4',weight=0)]) is None


def test_pp7_requires_homeroom_access(env,monkeypatch):
    import app.tenancy as tn
    import app.routers.academic as router
    from types import SimpleNamespace
    with tn.session_for(next(iter(tn._engines))) as db:
        _,s=seed(db);aid=s.id
    monkeypatch.setattr(router,'_scope',lambda *args:SimpleNamespace(can_homeroom=lambda cid:False))
    denied=env.get(f'/academic/student/{aid}/pp7',follow_redirects=False)
    assert denied.status_code==303 and denied.headers['location']=='/academic'
    denied=env.post(f'/academic/student/{aid}/pp7',data={},follow_redirects=False)
    assert denied.status_code==303 and denied.headers['location']=='/academic'
