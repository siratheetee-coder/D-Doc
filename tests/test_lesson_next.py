"""ปุ่ม "เช็กชื่อคาบที่สอน" หน้าหลักครู: เปิดคาบที่ใกล้เวลาตอนนี้ที่สุด"""
from datetime import date, datetime
from types import SimpleNamespace as N

from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account


def L(i, d, slot):
    return N(id=i, date=d, slot=slot, class_id=1, subject_id=1, term=2)


def test_pick_lesson_prefers_current_then_next_then_last():
    from app.routers.academic_lessons import pick_lesson
    d = date(2026, 11, 23)
    times = {"คาบ 1": (510, 560), "คาบ 3": (610, 660), "คาบ 6": (780, 830)}
    ls = [L(1, d, "คาบ 1"), L(3, d, "คาบ 3"), L(6, d, "คาบ 6")]
    at = lambda h, m: datetime(2026, 11, 23, h, m)
    assert pick_lesson(ls, times, at(10, 20)).id == 3          # กำลังสอนคาบ 3
    assert pick_lesson(ls, times, at(9, 30)).id == 3           # ว่าง -> คาบถัดไป
    assert pick_lesson(ls, times, at(7, 0)).id == 1            # เช้าก่อนเข้าเรียน
    assert pick_lesson(ls, times, at(15, 0)).id == 6           # เลิกแล้ว -> คาบล่าสุดของวันนี้
    other = [L(9, date(2026, 11, 20), "คาบ 2"), L(10, date(2026, 11, 25), "คาบ 2")]
    assert pick_lesson(other, times, at(10, 0)).id == 10       # วันนี้ไม่มีคาบ -> คาบถัดไปในวันข้างหน้า
    assert pick_lesson(other[:1], times, at(10, 0)).id == 9    # ไม่มีข้างหน้า -> ล่าสุดที่ผ่านมา
    assert pick_lesson([L(7, d, "08:00-08:50")], {}, at(8, 10)).id == 7   # ชื่อคาบเป็นเวลาเอง


def test_next_route_redirects_to_lesson_and_home_has_buttons(env):
    import app.tenancy as tn
    from app.models import AcadClass, AcadSubject, AcadTeaching, Person
    from app.routers.academic import _acad_year
    from app.services import academic_lessons as svc
    from app.thai_utils import thai_today
    with tn.session_for(next(iter(tn._engines))) as s:
        pid = s.query(Person).first().id
        y = _acad_year(s)
        k = AcadClass(year=y, level="ป.4", room="9"); s.add(k); s.flush()
        sb = AcadSubject(year=y, code="ว14101", name="วิทยาศาสตร์", level="ป.4", term=2); s.add(sb); s.flush()
        s.add(AcadTeaching(class_id=k.id, subject_id=sb.id, teacher_id=pid))
        svc.add_lesson(s, k, sb, 2, thai_today(), "คาบ 1", 50)
        s.commit()
        cid, sid = k.id, sb.id
    c = _account("ครูคาบถัดไป", "academic")
    r = c.get("/academic/lessons/next", follow_redirects=False)
    assert r.status_code == 303 and f"cid={cid}" in r.headers["location"] and f"sid={sid}" in r.headers["location"]
    assert "lesson=" in r.headers["location"]
    home = c.get("/").text
    assert "/academic/lessons/next" in home and "คาบที่สอน" in home and "/general/behavior" in home
