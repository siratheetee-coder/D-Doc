from tests.test_subsidy import env  # noqa: F401


def test_save_all_terms_holiday_and_days_in_one_post(env):
    import app.tenancy as tn
    from app.models import AcadHoliday, AcadYearSetting, AcadCalendar
    y = 2575
    r = env.post("/academic/calendar/save-all", data={
        "year": y, "t1_start": "16/05/2575", "t1_end": "10/10/2575",
        "t2_start": "01/11/2575", "t2_end": "31/03/2576",
        "new_day": "20", "new_month": "5", "new_name": "วันหยุดทดสอบ",
        "days_dirty": "1", "m_5": "16,19,20,21,22,23"}, follow_redirects=False)
    assert r.status_code == 303 and "saved=1" in r.headers["location"]
    with tn.session_for(next(iter(tn._engines))) as s:
        st = s.query(AcadYearSetting).filter_by(year=y).one()
        assert st.t1_start.day == 16
        assert s.query(AcadHoliday).filter_by(year=y, name="วันหยุดทดสอบ").count() == 1
        days = s.query(AcadCalendar).filter_by(year=y, month=5).one().days_csv
        assert "20" not in days.split(",") and "19" in days.split(",")   # วันหยุดที่เพิ่งเพิ่มถูกตัดออก
        assert s.query(AcadCalendar).filter_by(year=y, month=6).count() == 0  # ไม่ได้ส่ง = ไม่แตะ


def test_save_all_without_day_clicks_keeps_draft_months(env):
    import app.tenancy as tn
    from app.models import AcadCalendar
    y = 2576
    env.post("/academic/calendar/save-all", data={"year": y, "m_5": "1,2", "m_6": ""}, follow_redirects=False)
    with tn.session_for(next(iter(tn._engines))) as s:
        assert s.query(AcadCalendar).filter_by(year=y).count() == 0


def test_settings_tab_renders_steps(env):
    html = env.get("/academic/calendar?view=days").text
    assert "cd-steps" in html and "/save-all" in html and html.count("บันทึกปฏิทิน") >= 1
