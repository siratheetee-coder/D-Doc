import os
from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account


def _homeroom_teacher():
    import app.tenancy as tn
    from app.models import AcadClass, AcadSubject, AcadTeaching, Person
    from app.routers.academic import _acad_year
    with tn.session_for(next(iter(tn._engines))) as s:
        pid = s.query(Person).first().id
        y = _acad_year(s)
        k = AcadClass(year=y, level="ป.3", room="8", homeroom_id=pid); s.add(k); s.flush()
        sb = AcadSubject(year=y, code="ท13101", name="ภาษาไทย", level="ป.3"); s.add(sb); s.flush()
        s.add(AcadTeaching(class_id=k.id, subject_id=sb.id, teacher_id=pid)); s.commit()
        return k.id


def test_teacher_home_has_quick_check_buttons(env):
    cid = _homeroom_teacher()
    c = _account("ครูประจำชั้นปุ่มลัด", "academic")
    html = c.get("/").text
    assert "hq-bar" in html and f"cid={cid}" in html and "/general/assembly" in html
    ah = c.get("/academic").text
    out = os.environ.get("ZZ_SHOT_DIR")
    if out:
        open(os.path.join(out, "home.html"), "w", encoding="utf8").write(html)
        open(os.path.join(out, "acad.html"), "w", encoding="utf8").write(ah)
