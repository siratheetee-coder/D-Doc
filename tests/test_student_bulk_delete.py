from tests.test_subsidy import env
from app.models import Student, StudentMeasure, Arrival, AcadStudent, AcadClass


def test_bulk_delete_selected_preserves_academic_records(env):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        a=Student(name='ลบหนึ่ง',level='ป.1',room='1')
        b=Student(name='ลบสอง',level='ป.1',room='1')
        keep=Student(name='เก็บไว้',level='ป.2',room='1')
        c=AcadClass(year=2569,level='ป.1',room='1')
        db.add_all([a,b,keep,c]);db.flush()
        db.add(StudentMeasure(student_id=a.id,year=2569,term=1,times=1))
        db.add(Arrival(student_id=a.id,date='2026-10-12'))
        ac=AcadStudent(class_id=c.id,student_id=a.id,name=a.name)
        db.add(ac);db.commit()
        first,second,retained,academic=a.id,b.id,keep.id,ac.id
    page=env.get('/students')
    assert page.status_code==200 and 'bulkDeleteButton' in page.text and 'rosterFilter' in page.text
    for data in ({'ids':str(first)}, {'ids':f'{first},999999','confirmed':'yes'}, {'ids':'bad','confirmed':'yes'}):
        response=env.post('/students/bulk-delete',data=data)
        assert 'ยังไม่ได้ลบข้อมูล' in response.text
    with tn.session_for(tid) as db:
        assert db.get(Student,first) is not None
    response=env.post('/students/bulk-delete',data={'ids':f'{first},{second},{first}','confirmed':'yes'})
    assert response.status_code==200 and 'ลบจากทะเบียนนักเรียนกลางแล้ว 2 คน' in response.text
    with tn.session_for(tid) as db:
        assert db.get(Student,first) is None and db.get(Student,second) is None
        assert db.get(Student,retained) is not None
        assert db.get(AcadStudent,academic).student_id is None
        assert db.get(AcadStudent,academic).name=='ลบหนึ่ง'
        assert db.query(StudentMeasure).filter_by(student_id=first).count()==0
        assert db.query(Arrival).filter_by(student_id=first).count()==0
