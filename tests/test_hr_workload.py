"""ภาระงานบุคลากร: รวมคาบสอน ประจำชั้น กรรมการ (จับคู่ชื่อ) หน้าที่อื่น + สิทธิ์ (ครูเห็นแค่ของตัวเอง)"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account


def test_norm_name_strips_prefixes():
    from app.services.hr_workload import norm_name
    assert norm_name("นางสาว สมใจ  ใจดี") == norm_name("สมใจ ใจดี") == norm_name("น.ส.สมใจ ใจดี")


def _setup():
    import app.tenancy as tn
    from app.models import (Person, AcadClass, AcadSubject, AcadTeaching, AcadPeriod, AcadTimetable,
                            Procurement, Committee, CommitteeMember, StaffDuty, Project)
    from app.routers.academic import _acad_year
    with tn.session_for(next(iter(tn._engines))) as s:
        y = _acad_year(s)
        a = Person(name="นายภาระ มากมาย", position="ครู"); b = Person(name="นางสาวว่าง สบาย", position="ครู")
        s.add_all([a, b]); s.flush()
        k = AcadClass(year=y, level="ป.3", room="5", homeroom_id=a.id); s.add(k); s.flush()
        sb = AcadSubject(year=y, code="ค13101", name="คณิตศาสตร์", level="ป.3"); s.add(sb); s.flush()
        s.add(AcadTeaching(class_id=k.id, subject_id=sb.id, teacher_id=a.id))
        for i in range(4):
            p = AcadPeriod(year=y, seq=90 + i, name=f"คาบ x{i}", time_label=""); s.add(p); s.flush()
            s.add(AcadTimetable(class_id=k.id, day=1 + i % 5, period_id=p.id, subject_id=sb.id))
        pr = Procurement(fiscal_year=y, subject="ซื้อกระดาษ", request_date=datetime(y - 543, 7, 1)); s.add(pr); s.flush()
        cm = Committee(procurement_id=pr.id, kind="inspect"); s.add(cm); s.flush()
        s.add(CommitteeMember(committee_id=cm.id, name="ภาระ มากมาย"))          # ไม่มีคำนำหน้า ต้องจับคู่ได้
        s.add(CommitteeMember(committee_id=cm.id, name="คนนอก ไม่อยู่ในทะเบียน"))
        s.add(Project(name="โครงการรักการอ่าน", plan_year=y + 1, responsible="นายภาระ มากมาย และฝ่ายวิชาการ"))
        s.add(StaffDuty(person_id=b.id, year=y, name="ครูเวร", weight=2))
        s.commit()
        return y, a.id, b.id


def test_compute_scores_and_unmatched(env):
    import app.tenancy as tn
    from app.services import hr_workload as wl
    y, a, b = _setup()
    with tn.session_for(next(iter(tn._engines))) as s:
        d = wl.compute(s, y)
    ra = next(r for r in d["rows"] if r["p"].id == a)
    rb = next(r for r in d["rows"] if r["p"].id == b)
    assert ra["periods"] == 4 and len(ra["homeroom"]) == 1 and len(ra["proc"]) == 1
    assert ra["project"] == ["ผู้รับผิดชอบโครงการ: โครงการรักการอ่าน"]
    assert ra["score"] == 4 * 1.0 + 3.0 + 0.5 + 1.0
    assert rb["score"] == 2 and [x.name for x in rb["duties"]] == ["ครูเวร"]
    assert "คนนอก ไม่อยู่ในทะเบียน" in d["unmatched"]


def test_pages_and_teacher_sees_only_own(env):
    y, a, b = _setup()
    html = env.get("/hr/workload").text
    assert "ภาระงานบุคลากร" in html and "นายภาระ มากมาย" in html
    assert "ครูเวร" in env.get(f"/hr/workload/{b}").text
    r = env.post("/hr/workload/duty", data={"name": "หัวหน้ากลุ่มสาระ", "weight": "3", "person_ids": [str(a), str(b)], "year": y},
                 follow_redirects=False)
    assert r.status_code == 303 and "2" in r.headers["location"]
    t = _account("ครูดูภาระงาน", "academic")
    assert t.get("/hr/workload", follow_redirects=False).status_code in (302, 303, 403)
    me = t.get("/me/workload").text
    assert "ภาระงานของฉัน" in me and "นางสาวว่าง สบาย" not in me
