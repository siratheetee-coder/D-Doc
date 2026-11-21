"""คะแนนความประพฤติ: บันทึก/หลายคน/ลบ/สิทธิ์/หักอัตโนมัติจากการเข้าแถว/หนังสือ/ตั้งค่า"""
import json

from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account


def _class_with_students(n=2):
    import app.tenancy as tn
    from app.models import AcadClass, AcadStudent, Student
    from app.routers.academic import _acad_year
    with tn.session_for(next(iter(tn._engines))) as s:
        y = _acad_year(s)
        k = AcadClass(year=y, level="ม.2", room="7"); s.add(k); s.flush()
        ids = []
        for i in range(n):
            st = Student(name=f"นักเรียนทดสอบ {i}", level="ม.2", room="7"); s.add(st); s.flush()
            s.add(AcadStudent(class_id=k.id, student_id=st.id, name=st.name, seq=i + 1)); ids.append(st.id)
        s.commit()
        return k.id, ids, y


def _score(sid, y):
    import app.tenancy as tn
    from app.services import behavior
    with tn.session_for(next(iter(tn._engines))) as s:
        return behavior.scores(s, y, [sid])[sid]


def test_record_multi_and_custom_then_delete(env):
    cid, (a, b), y = _class_with_students()
    html = env.get(f"/general/behavior?cid={cid}").text
    assert "นักเรียนทดสอบ 0" in html and "bhDlg" in html
    import app.tenancy as tn
    from app.models import BehaviorRule, BehaviorRecord
    with tn.session_for(next(iter(tn._engines))) as s:
        late = s.query(BehaviorRule).filter_by(name="มาสาย").first().id
    r = env.post("/general/behavior/add", data={"student_ids": f"{a},{b}", "rule_id": late}, follow_redirects=False)
    assert r.status_code == 303 and "2" in r.headers["location"]
    assert _score(a, y) == 95 and _score(b, y) == 95
    env.post("/general/behavior/add", data={"student_ids": str(a), "kind": "plus", "label": "ช่วยงานกีฬาสี", "points": "3"})
    assert _score(a, y) == 98
    page = env.get(f"/general/behavior/s/{a}").text
    assert "ช่วยงานกีฬาสี" in page and "98" in page
    with tn.session_for(next(iter(tn._engines))) as s:
        rid = s.query(BehaviorRecord).filter_by(student_id=a, label="ช่วยงานกีฬาสี").one().id
    env.post(f"/general/behavior/r/{rid}/delete")
    assert _score(a, y) == 95


def test_teacher_can_record_but_not_delete_others_or_change_settings(env):
    cid, (a, _b), y = _class_with_students()
    env.post("/general/behavior/add", data={"student_ids": str(a), "label": "ทดสอบ", "points": "10"})
    t = _account("ครูความประพฤติ", "academic")
    assert t.get("/general/behavior/settings", follow_redirects=False).status_code == 403
    import app.tenancy as tn
    from app.models import BehaviorRecord
    with tn.session_for(next(iter(tn._engines))) as s:
        rid = s.query(BehaviorRecord).filter_by(student_id=a, label="ทดสอบ").one().id
    assert t.post(f"/general/behavior/r/{rid}/delete", follow_redirects=False).status_code == 403
    t.post("/general/behavior/add", data={"student_ids": str(a), "label": "ครูบันทึกเอง", "points": "2"})
    with tn.session_for(next(iter(tn._engines))) as s:
        mine = s.query(BehaviorRecord).filter_by(student_id=a, label="ครูบันทึกเอง").one().id
    assert t.post(f"/general/behavior/r/{mine}/delete", follow_redirects=False).status_code == 303
    assert _score(a, y) == 90


def test_auto_deduct_from_assembly_follows_status(env):
    cid, (a, b), y = _class_with_students()
    env.post("/general/behavior/settings", data={"full": "100", "warn_parent": "70", "warn_probation": "50",
                                                 "auto_late": "5", "auto_skip": "10"})
    d = "21/11/2569"
    env.post("/general/assembly", data={"date": d, "cid": cid, "marks": json.dumps({str(a): "late", str(b): "skip"})})
    assert _score(a, y) == 95 and _score(b, y) == 90
    env.post("/general/assembly", data={"date": d, "cid": cid, "marks": json.dumps({str(a): "ontime", str(b): "late"})})
    assert _score(a, y) == 100 and _score(b, y) == 95          # แก้สถานะ = รายการหักเปลี่ยนตาม ไม่ซ้ำ
    env.post("/general/assembly", data={"date": d, "cid": cid, "marks": json.dumps({str(b): ""})})
    assert _score(b, y) == 100


def test_letters_and_levels(env):
    cid, (a, _b), y = _class_with_students()
    env.post("/general/behavior/add", data={"student_ids": str(a), "label": "ทะเลาะวิวาท", "points": "55"})
    page = env.get(f"/general/behavior/s/{a}").text
    assert "ควรทำทัณฑ์บน" in page
    p = env.get(f"/general/behavior/s/{a}/letter?kind=probation").text
    assert "บันทึกการทำทัณฑ์บน" in p and "ทะเลาะวิวาท" in p and "45" in p
    assert "หนังสือเชิญผู้ปกครองพบ" in env.get(f"/general/behavior/s/{a}/letter").text
