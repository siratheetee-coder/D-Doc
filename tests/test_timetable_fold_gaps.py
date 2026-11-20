from tests.test_subsidy import env  # noqa: F401
from types import SimpleNamespace as N


def test_period_gaps_flags_missing_periods():
    from app.routers.academic import _period_gaps
    ps = [N(id=1, seq=1, name="คาบ 1", time_label="08:30-09:20"),
          N(id=2, seq=2, name="คาบ 2", time_label="09:20-10:10"),
          N(id=3, seq=3, name="พักเที่ยง", time_label="11:50-12:40"),
          N(id=4, seq=4, name="คาบ 5", time_label="12:40-13:30")]
    gaps = _period_gaps(ps)
    assert len(gaps) == 1 and gaps[0][0].name == "คาบ 2" and gaps[0][2] == 100
    assert _period_gaps(ps[:2]) == []        # ต่อกันพอดี ไม่เตือน
    assert _period_gaps([N(id=9, seq=1, name="x", time_label="")]) == []


def test_mark_until_today(monkeypatch):
    from datetime import date
    import app.thai_utils as tu
    from app.routers.academic import _mark_until
    monkeypatch.setattr(tu, "thai_today", lambda: date(2026, 11, 21))
    assert _mark_until(2569, 11) == 21
    assert _mark_until(2569, 12) == 0 and _mark_until(2569, 1) == 0
    assert _mark_until(2569, 10) == 31 and _mark_until(2568, 1) == 31


def test_unlisted_note_survives_edit_and_save(env):
    import re
    import app.tenancy as tn
    from app.models import AcadClass, AcadPeriod, AcadTimetable
    from app.routers.academic import _acad_year
    with tn.session_for(next(iter(tn._engines))) as s:
        y = _acad_year(s)
        k = AcadClass(year=y, level="ป.1", room="7"); s.add(k); s.flush()
        p = AcadPeriod(year=y, seq=99, name="คาบ x", time_label="15:00-15:50"); s.add(p); s.flush()
        s.add(AcadTimetable(class_id=k.id, day=2, period_id=p.id, note="ลูกเสือ")); s.commit()
        cid, pid = k.id, p.id
    html = env.get(f"/academic/timetable?cid={cid}").text
    sel = re.search(r'<select name="cell_2_%d".*?</select>' % pid, html, re.S).group(0)
    assert 'value="n:ลูกเสือ"' in sel and "selected" in sel.split('n:ลูกเสือ')[1][:40]
    env.post("/academic/timetable/save", data={"cid": cid, f"cell_2_{pid}": "n:ลูกเสือ"})
    with tn.session_for(next(iter(tn._engines))) as s:
        assert s.query(AcadTimetable).filter_by(class_id=cid, day=2, period_id=pid).first().note == "ลูกเสือ"
