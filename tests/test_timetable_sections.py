from datetime import date
from tests.test_academic_lessons import db
from tests.test_subsidy import env
from app.models import AcadClass, AcadPeriod, AcadTimetable, AcadSubject, AcadTeaching, Person, AcadCalendar
from app.services import timetable_sections as ts
from app.services import academic_lessons as lessons


def seed(db):
    primary=AcadClass(year=2569,level='ป.1',room='1')
    secondary=AcadClass(year=2569,level='ม.1',room='1')
    p=AcadPeriod(year=2569,seq=1,name='คาบ 1',time_label='08:30-09:20')
    teacher=Person(name='ครูข้ามระดับ')
    subject=AcadSubject(year=2569,level='ม.1',name='ภาษาไทย',term=1)
    subp=AcadSubject(year=2569,level='ป.1',name='ภาษาไทย',term=0)
    db.add_all([primary,secondary,p,teacher,subject,subp]);db.flush()
    db.add_all([AcadTimetable(class_id=primary.id,day=1,period_id=p.id,subject_id=subp.id),
                AcadTimetable(class_id=secondary.id,day=1,period_id=p.id,subject_id=subject.id),
                AcadTeaching(class_id=primary.id,subject_id=subp.id,teacher_id=teacher.id),
                AcadTeaching(class_id=secondary.id,subject_id=subject.id,teacher_id=teacher.id)])
    db.commit()
    return primary,secondary,p,teacher,subject


def test_split_preserves_assignments_and_imports_correct_minutes(db):
    primary,secondary,p,teacher,subject=seed(db)
    ts.enable(db,2569);db.commit();ts.enable(db,2569);db.commit()
    assert db.query(AcadPeriod).count()==2
    second=ts.periods(db,2569,level='ม.1')[0]
    assert ts.periods(db,2569,level='ป.1')[0].id==p.id
    assert db.query(AcadTimetable).filter_by(class_id=secondary.id).one().period_id==second.id
    second.time_label='09:00-10:00';db.add(AcadCalendar(year=2569,month=5,days_csv='18'));db.commit()
    assert ts.overlaps(p,second)
    assert lessons.import_preview(db,secondary,subject,1,'2026-05-18','2026-05-18')[0]['minutes']==60
    second.time_label='09:20-10:00';assert not ts.overlaps(p,second)
    second.time_label='';assert ts.overlaps(p,second)


def test_auto_schedule_avoids_cross_level_overlaps(db):
    from app.routers.academic import _auto_schedule, _busy_at, _teach_map
    primary,secondary,p,teacher,subject=seed(db)
    ts.enable(db,2569);db.commit()
    second=ts.periods(db,2569,level='ม.1')[0];second.time_label='09:00-10:00';db.commit()
    assert teacher.id in _busy_at(db,2569,1,second.id,_teach_map(db))
    placed,unplaced=_auto_schedule(db,secondary,{subject.id:5},True)
    assert placed==4 and unplaced==1
    assert not db.query(AcadTimetable).filter_by(class_id=secondary.id,day=1).first()


def test_split_routes_and_teacher_warnings(env):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        primary,secondary,p,teacher,subject=seed(db)
        cid,teacher_id=secondary.id,teacher.id
    r=env.post('/academic/timetable/separate',data={'year':2569})
    assert r.status_code==200 and 'แยกตารางประถม–มัธยม' in r.text
    with tn.session_for(tid) as db:
        p=ts.periods(db,2569,level='ม.1')[0];pid=p.id
    r=env.post('/academic/timetable/periods/save',data={'year':2569,'section':'secondary',f'name_{pid}':'คาบมัธยม',f'time_{pid}':'09:00-10:00',f'seq_{pid}':1})
    assert r.status_code==200
    page=env.get(f'/academic/timetable?cid={cid}').text
    assert 'คาบมัธยม' in page and '09:00-10:00' in page
    assert 'พบเวลาสอนซ้อน' in env.get(f'/academic/timetable/teacher?year=2569&pid={teacher_id}').text
    invalid=env.post('/academic/timetable/periods/save',data={'year':2569,'section':'secondary',f'del_{pid}':'1'})
    assert 'คาบนี้มีตารางเรียน' in invalid.text
    with tn.session_for(tid) as db:
        assert db.get(AcadPeriod,pid) is not None
    assert env.get(f'/academic/timetable/class.docx?cid={cid}').status_code==200
    assert env.get(f'/academic/timetable/teacher.docx?pid={teacher_id}&year=2569').status_code==200
