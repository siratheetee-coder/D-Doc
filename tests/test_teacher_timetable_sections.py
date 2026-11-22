"""ตารางสอนรายครู: โรงเรียนแยกคาบประถม/มัธยม รวมเป็นตารางเดียว คาบเวลาเดียวกันอยู่คอลัมน์เดียว"""
from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account


def test_teacher_timetable_split_by_section(env):
    import app.tenancy as tn
    from app.models import AcadClass, AcadSubject, AcadTeaching, AcadPeriod, AcadTimetable, Person
    from app.routers.academic import _acad_year
    from app.services import timetable_sections as ts
    with tn.session_for(next(iter(tn._engines))) as s:
        pid = s.query(Person).first().id
        y = _acad_year(s)
        if not ts.periods(s, y, "primary"):
            s.add(AcadPeriod(year=y, seq=1, name="คาบ 1", time_label="08:30-09:30", school_section="primary"))
            s.flush()
        ts.enable(s, y)
        k = AcadClass(year=y, level="ป.5", room="8"); s.add(k); s.flush()
        sb = AcadSubject(year=y, code="อ15101", name="ภาษาอังกฤษ", level="ป.5"); s.add(sb); s.flush()
        s.add(AcadTeaching(class_id=k.id, subject_id=sb.id, teacher_id=pid))
        p = ts.periods(s, y, "primary")[0]
        s.add(AcadTimetable(class_id=k.id, day=1, period_id=p.id, subject_id=sb.id)); s.commit()
    html = _account("ครูตารางแยก", "academic").get("/academic/timetable/teacher").text
    import re
    head = html[html.index("<thead>"):html.index("</thead>")]
    assert head.count("08:30-09:30") == 1            # คาบ 1 ประถม+มัธยม เวลาเดียวกัน = คอลัมน์เดียว
    assert "ภาษาอังกฤษ" in html and "ประถม" not in head and "มัธยม" not in head
