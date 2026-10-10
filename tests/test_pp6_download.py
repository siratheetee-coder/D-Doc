from tests.test_subsidy import env
from app.models import AcadClass, AcadStudent


def test_primary_class_has_download_helper_and_both_pp6_downloads(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        c=AcadClass(year=2569,level='ป.1',room='1');db.add(c);db.flush()
        s=AcadStudent(class_id=c.id,seq=1,name='นักเรียนทดสอบ',student_no='001')
        db.add(s);db.commit();cid,aid=c.id,s.id
    page=env.get(f'/academic/classes/{cid}')
    assert page.status_code==200
    assert 'function ntGo(url)' in page.text
    assert "ntGo('/academic/student/' + sid + '/pp6.docx')" in page.text
    for path in [f'/academic/student/{aid}/pp6.docx',f'/academic/classes/{cid}/pp6-all.docx']:
        response=env.get(path)
        assert response.status_code==200
        assert response.content[:2]==b'PK'
        assert 'wordprocessingml' in response.headers['content-type']
