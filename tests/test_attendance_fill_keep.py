from tests.test_subsidy import env  # noqa: F401


def test_fill_year_keeps_absences_and_skips_future(env, monkeypatch):
    from datetime import date
    import app.thai_utils as tu
    import app.tenancy as tn
    from app.models import AcadClass, AcadStudent, AcadAttendance, AcadCalendar
    from app.services.academic import build_marks, parse_marks
    monkeypatch.setattr(tu, "thai_today", lambda: date(2026, 11, 21))
    with tn.session_for(next(iter(tn._engines))) as s:
        y = 2569
        k = AcadClass(year=y, level="ป.6", room="9"); s.add(k); s.flush()
        st = AcadStudent(class_id=k.id, name="ทดสอบ", seq=1); s.add(st); s.flush()
        for m, csv in ((11, "2,3,20,23,24"), (12, "1,2")):
            row = s.query(AcadCalendar).filter_by(year=y, month=m).first()
            if not row:
                row = AcadCalendar(year=y, month=m); s.add(row)
            row.days_csv = csv
        s.add(AcadAttendance(acad_student_id=st.id, month=11, marks=build_marks({20: "ข"}))); s.commit()
        cid, sid = k.id, st.id
    r = env.post("/academic/attendance/fill-year", data={"cid": cid, "mode": "overall"}, follow_redirects=False)
    assert r.status_code == 303
    with tn.session_for(next(iter(tn._engines))) as s:
        nov = parse_marks(s.query(AcadAttendance).filter_by(acad_student_id=sid, month=11).one().marks)
        assert nov == {2: "/", 3: "/", 20: "ข"}          # ขาดยังอยู่ 23-24 ยังไม่ถึงไม่ใส่
        dec = s.query(AcadAttendance).filter_by(acad_student_id=sid, month=12).first()
        assert not dec or not parse_marks(dec.marks)
