# -*- coding: utf-8 -*-
"""เมนูโปรไฟล์ (ออกจากระบบ) ต้องกดได้ทุกหน้า

เดิมสคริปต์ toggleMe อยู่ในสาขา else ของเมนูข้าง หน้าหลักของครูใช้อีกสาขา
ปุ่มโปรไฟล์จึงกดแล้วไม่ขึ้นเมนู ครูออกจากระบบไม่ได้ (เจ้าของเจอบนมือถือ)
"""


def _teacher_client(person_id):
    """ล็อกอินเป็นครู (ไม่ใช่ไอดีหลัก) เพราะหน้าหลักของครูเท่านั้นที่ใช้เมนูข้างอีกสาขา"""
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "teacher", "role": "user", "tenant_id": 1,
        "display_name": "ครู", "must_change": False, "person_id": person_id}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {
        "is_owner": False, "modules": "academic", "active": True, "welcomed": True,
        "person_id": person_id}
    c = TestClient(app)
    c.post("/login", data={"username": "teacher", "password": "x"}, follow_redirects=False)
    return c


def test_teacher_personal_home_has_profile_menu_script():
    from app.tenancy import session_for
    from app.models import Person
    db = session_for(1)
    t = Person(name="ทดสอบเมนูโปรไฟล์_ครู", position="ครู"); db.add(t); db.commit()
    try:
        c = _teacher_client(t.id)
        for url in ("/", "/academic/lesson-plans"):
            html = c.get(url).text
            assert 'id="meBtn"' in html, url
            assert "function toggleMe" in html, url
            assert '/logout' in html, url
        assert "หน้าหลักของฉัน" in c.get("/").text, "ต้องเป็นหน้าหลักของครูจริง"
    finally:
        db.delete(t); db.commit()


def test_teacher_home_shows_plan_status_and_todos():
    """เจ้าของ: หน้าหลักครูต้องเห็นสถานะแผนเลย ไม่ต้องกดเข้าหน้าแผนการสอนก่อน"""
    from app.tenancy import session_for
    from app.models import Person, LessonPlan
    db = session_for(1)
    t = Person(name="ทดสอบหน้าหลัก_ครู", position="ครู"); db.add(t); db.commit()
    try:
        from app.routers.academic import _acad_year
        y = _acad_year(db)
        db.add(LessonPlan(person_id=t.id, year=y, term=1, title="ทดสอบหน้าหลัก_ส่งกลับ", status="revise",
                          mode="plan", comment="แก้ตัวชี้วัด"))
        db.add(LessonPlan(person_id=t.id, year=y, term=1, title="ทดสอบหน้าหลัก_ร่าง", status="draft", mode="plan"))
        db.commit()
        html = _teacher_client(t.id).get("/").text
        assert "แผนการสอนของฉัน" in html and "ใบลาและขอไปราชการ" in html
        assert "ส่งกลับให้แก้" in html and "แก้ตัวชี้วัด" in html
        assert html.index("แผนถูกส่งกลับให้แก้") < html.index("แผนยังไม่กดส่ง"), "เรื่องด่วนต้องขึ้นก่อน"
        assert "แผนรอดำเนินการ" in html and "บันทึกหลังสอนค้าง" in html
    finally:
        for p in db.query(LessonPlan).filter(LessonPlan.person_id == t.id).all():
            db.delete(p)
        db.delete(t); db.commit()
