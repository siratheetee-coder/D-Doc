import re
from fastapi.testclient import TestClient
from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _seed(env):
    from app.models import Student, AcadClass, AcadStudent, AcadSubject, AcadScore, AcadAttendance, School
    from app.routers.academic import _acad_year
    with _db() as s:
        y = _acad_year(s)
        a = Student(name="เด็กชายเอ ทดสอบ", student_no="90001", level="ป.5")
        b = Student(name="เด็กหญิงบี ทดสอบ", student_no="90002", level="ป.5")
        s.add_all([a, b]); s.flush()
        k = AcadClass(year=y, level="ป.5", room="9"); s.add(k); s.flush()
        ra = AcadStudent(class_id=k.id, student_id=a.id, seq=1, student_no="90001", name=a.name)
        rb = AcadStudent(class_id=k.id, student_id=b.id, seq=2, student_no="90002", name=b.name)
        sj = AcadSubject(year=y, level="ป.5", code="ค15101", name="คณิตศาสตร์")
        s.add_all([ra, rb, sj]); s.flush()
        s.add_all([AcadScore(acad_student_id=ra.id, subject_id=sj.id, term=0, score=81, grade="4"),
                   AcadScore(acad_student_id=rb.id, subject_id=sj.id, term=0, score=37.25, grade="1.5"),
                   AcadAttendance(acad_student_id=ra.id, month=6, marks="//ข/ป" + "." * 26),
                   AcadAttendance(acad_student_id=rb.id, month=6, marks="ขขขขข" + "." * 26)])
        s.commit()
        return dict(cid=k.id, sid=sj.id, a=a.id, b=b.id)


def _login(u, p):
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": u, "password": p}, follow_redirects=False)
    return c, r


def test_student_portal_flow_and_isolation(env):
    x = _seed(env)
    # ปิดอยู่: ครูสร้างบัญชีได้ นักเรียนยังไม่เห็นข้อมูล
    r = env.post(f"/academic/student-accounts/{x['cid']}/create")
    assert r.status_code == 200
    cards = dict(re.findall(r'class="v">([^<]+)</div>\s*<div class="k">รหัสผ่าน</div><div class="v">(\d{6})<', r.text))
    assert len(cards) == 2
    ua = next(u for u in cards if u.startswith("90001."))
    assert env.post(f"/academic/student-accounts/{x['cid']}/create", follow_redirects=False).status_code == 303
    c, r = _login(ua, cards[ua])
    assert r.status_code == 303
    # ป.5 ต้องเปลี่ยนรหัสก่อน
    assert c.get("/student", follow_redirects=False).headers["location"] == "/account/password"
    from app.accounts import acc_session, Account
    db = acc_session(); u = db.query(Account).filter_by(username=ua).first(); u.must_change_password = False; db.commit(); db.close()
    c, r = _login(ua, cards[ua])
    assert "ปิดการดูข้อมูลนักเรียน" in c.get("/student").text
    env.post("/academic/student-accounts/toggle", data={"on": "1"})
    page = c.get("/student").text
    assert "เด็กชายเอ" in page and "60.0%" in page          # มา 3 จาก 5 วัน
    # ยังไม่เผยแพร่ = ไม่เห็นเกรด
    assert "ยังไม่มีวิชาที่ครูเผยแพร่" in c.get("/student/grades").text
    env.post(f"/academic/student-accounts/{x['cid']}/publish", data={"subject_id": x["sid"], "term": 0, "on": "1"})
    g = c.get("/student/grades").text
    assert "คณิตศาสตร์" in g and "81" in g and "37.25" not in g   # ไม่เห็นคะแนนเพื่อน
    # ปิดทุกหน้าอื่น
    for path in ("/", "/academic", "/finance", "/procurement", "/students", "/settings", "/lunch",
                 "/academic/student-accounts", "/hr/staff", "/account/profile", "/search?q=a"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/student", path
    r = c.post(f"/academic/student-accounts/{x['cid']}/publish", data={"subject_id": x["sid"], "on": "0"},
               follow_redirects=False)
    assert r.headers["location"] == "/student"
    assert c.get(f"/student/grades?student_id={x['b']}").text.count("37.25") == 0
    # ปิดบัญชีแล้วเข้าไม่ได้
    env.post(f"/academic/student-accounts/{x['cid']}/active", data={"student_id": x["a"], "on": "0"})
    assert c.get("/student", follow_redirects=False).headers["location"] == "/login"
    # รีเซ็ต = รหัสใหม่ใช้ได้ รหัสเดิมใช้ไม่ได้
    r = env.post(f"/academic/student-accounts/{x['cid']}/reset", data={"student_id": x["a"]})
    pw = re.search(r'รหัสผ่าน</div><div class="v">(\d{6})<', r.text).group(1)
    assert _login(ua, pw)[1].status_code == 303
    assert _login(ua, cards[ua])[1].status_code == 401 or pw == cards[ua]


def test_trial_school_cannot_use_student_accounts(env):
    x = _seed(env)
    r = env.post(f"/academic/student-accounts/{x['cid']}/create")
    ua, pw = re.search(r'class="v">([^<]+)</div>\s*<div class="k">รหัสผ่าน</div><div class="v">(\d{6})<', r.text).groups()
    from app.accounts import acc_session, Tenant
    db = acc_session(); t = db.query(Tenant).first(); t.plan = "trial"; db.commit(); db.close()
    assert _login(ua, pw)[1].status_code == 403
    assert "เฉพาะโรงเรียนที่เป็นสมาชิก" in env.get("/academic/student-accounts").text


def test_one_student_typo_does_not_lock_school_ip(env):
    _seed(env)
    for _ in range(9):
        _login("nobody.x", "wrong")
    _, r = _login("demo", "Demo!2569")
    assert r.status_code == 303
