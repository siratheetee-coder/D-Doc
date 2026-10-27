"""เวียนหนังสือรับ: ธุรการเสนอ -> ผอ. สั่งการ -> ครูรับทราบ / ธุรการบันทึกแทน"""
from tests.test_subsidy import env  # noqa: F401


def _login(username, password):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    return c


def test_route_letter_director_teacher_ack(env):
    from app.accounts import acc_session, Account, hash_password, add_teacher_account
    from app.tenancy import session_for
    from app.models import IncomingLetter, LetterRecipient, Person, Notification

    with acc_session() as adb:
        tid = adb.query(Account).filter_by(username="demo").one().tenant_id
        boss = Account(username="dir-route", password_hash=hash_password("Route!12345"), tenant_id=tid,
                       is_director=True, must_change_password=False, active=True)
        adb.add(boss); adb.commit()
    db = session_for(tid)
    try:
        people = db.query(Person).filter(Person.active == True).order_by(Person.id).limit(3).all()  # noqa: E712
        p1, p2, p3 = (p.id for p in people)
    finally:
        db.close()
    res = add_teacher_account(tid, p1, "routeteach", "Route!12345", "ครูทดสอบ")
    assert res.get("ok"), res
    res3 = add_teacher_account(tid, p3, "routeother", "Route!12345", "ครูอื่น")
    teacher = _login(res["username"], "Route!12345")
    other = _login(res3["username"], "Route!12345")
    director = _login("dir-route", "Route!12345")

    env.post("/admin/incoming", data={"fiscal_year": 2570, "subject": "ขอเชิญประชุมเวียน", "from_org": "สพป."})
    db = session_for(tid)
    try:
        rid = db.query(IncomingLetter).filter_by(subject="ขอเชิญประชุมเวียน").one().id
    finally:
        db.close()

    # ธุรการเสนอ ผอ. พร้อมผู้รับที่เสนอ (ครูยังไม่เห็น)
    r = env.post(f"/admin/incoming/{rid}/route", data={"action": "director", "note": "เพื่อโปรดทราบ", "pid": [p1, p2]},
                 follow_redirects=False)
    assert r.status_code == 303
    assert "ขอเชิญประชุมเวียน" not in teacher.get("/me/letters").text
    assert "ขอเชิญประชุมเวียน" in director.get("/approvals").text

    # ผอ. อ่านอย่างเดียว: ส่งเวียนเองไม่ได้ แต่สั่งการได้
    assert director.post(f"/admin/incoming/{rid}/route", data={"action": "send", "pid": [p1]}).status_code == 403
    r = director.post(f"/admin/incoming/{rid}/endorse", data={"order": "ทราบ แจ้งครูทุกคนทราบ", "pid": [p1, p2]},
                      follow_redirects=False)
    assert r.status_code == 303
    db = session_for(tid)
    try:
        let = db.get(IncomingLetter, rid)
        assert let.route_status == "sent" and let.director_order == "ทราบ แจ้งครูทุกคนทราบ" and let.director_at
        rcs = {x.person_id: x.id for x in let.recipients}
        assert set(rcs) == {p1, p2}
        assert db.query(Notification).filter_by(person_id=p1, link=f"/me/letters/{rcs[p1]}").count() == 1
    finally:
        db.close()

    # ครูเห็นและรับทราบ คนอื่นเปิดของคนนี้ไม่ได้ และเข้าทะเบียนธุรการไม่ได้
    assert "ขอเชิญประชุมเวียน" in teacher.get("/me/letters").text
    page = teacher.get(f"/me/letters/{rcs[p1]}")
    assert page.status_code == 200 and "ทราบ แจ้งครูทุกคนทราบ" in page.text
    assert teacher.post(f"/me/letters/{rcs[p1]}/ack", follow_redirects=False).status_code == 303
    assert other.get(f"/me/letters/{rcs[p1]}", follow_redirects=False).headers["location"] == "/me/letters"
    assert other.post(f"/me/letters/{rcs[p1]}/ack", follow_redirects=False).status_code == 303
    assert teacher.get(f"/admin/incoming/{rid}").status_code == 403

    # ธุรการบันทึกรับทราบแทนคนที่ไม่มีบัญชี + เห็นสรุปในทะเบียน
    env.post(f"/admin/incoming/{rid}/ack/{rcs[p2]}")
    db = session_for(tid)
    try:
        a1, a2 = db.get(LetterRecipient, rcs[p1]), db.get(LetterRecipient, rcs[p2])
        assert a1.ack_at and not a1.ack_by
        assert a2.ack_at and a2.ack_by
    finally:
        db.close()
    assert "รับทราบ 2/2" in env.get("/admin/incoming?year=2570").text
    assert "รับทราบแล้ว 2 จาก 2" in env.get(f"/admin/incoming/{rid}").text

    # เวียนเพิ่มภายหลัง + ลบหนังสือแล้วผู้รับหายตาม
    env.post(f"/admin/incoming/{rid}/route", data={"action": "add", "pid": [p3]})
    assert "ขอเชิญประชุมเวียน" in other.get("/me/letters").text
    env.post(f"/admin/incoming/{rid}/delete")
    db = session_for(tid)
    try:
        assert db.query(LetterRecipient).count() == 0
    finally:
        db.close()


def test_route_send_directly_without_director(env):
    from app.accounts import acc_session, Account
    from app.tenancy import session_for
    from app.models import IncomingLetter, Person
    with acc_session() as adb:
        tid = adb.query(Account).filter_by(username="demo").one().tenant_id
    env.post("/admin/incoming", data={"fiscal_year": 2570, "subject": "แจ้งวันหยุดเวียนเลย"})
    db = session_for(tid)
    try:
        rid = db.query(IncomingLetter).filter_by(subject="แจ้งวันหยุดเวียนเลย").one().id
        pid = db.query(Person).first().id
    finally:
        db.close()
    assert "ส่งเวียนหนังสือ" in env.get(f"/admin/incoming/{rid}").text
    # ไม่เลือกผู้รับ = ไม่เวียน
    env.post(f"/admin/incoming/{rid}/route", data={"action": "send", "note": "แจ้งทุกคน"})
    db = session_for(tid)
    try:
        assert not db.get(IncomingLetter, rid).route_status
    finally:
        db.close()
    env.post(f"/admin/incoming/{rid}/route", data={"action": "send", "note": "แจ้งทุกคน", "pid": [pid]})
    db = session_for(tid)
    try:
        r = db.get(IncomingLetter, rid)
        assert r.route_status == "sent" and r.director_order == "แจ้งทุกคน" and not r.director_name
        assert len(r.recipients) == 1
    finally:
        db.close()


def test_staff_accounts_and_letter_email(env, monkeypatch):
    """ไอดีหลักกดสร้างบัญชีครูทีเดียว ครูใส่อีเมลเอง แล้วหนังสือเวียนส่งเข้าอีเมลพร้อมลิงก์"""
    import time
    from app.accounts import acc_session, Account, list_teacher_accounts
    from app.tenancy import session_for
    from app.models import IncomingLetter, Person
    sent = []
    monkeypatch.setattr("app.services.mailer.send_email",
                        lambda to, s, h, attachments=None: sent.append((to, s, h)) or True)
    with acc_session() as adb:
        tid = adb.query(Account).filter_by(username="demo").one().tenant_id
    have = {a["person_id"] for a in list_teacher_accounts(tid)}
    db = session_for(tid)
    try:
        pids = [p.id for p in db.query(Person).filter(Person.active == True).order_by(Person.id)  # noqa: E712
                if p.id not in have][:2]
    finally:
        db.close()
    assert len(pids) == 2
    assert "บัญชีครูและอีเมล" in env.get("/admin/staff-accounts").text
    page = env.post("/admin/staff-accounts/create", data={"pid": pids})
    assert page.status_code == 200 and "สร้างบัญชีแล้ว 2 คน" in page.text
    accs = {a["person_id"]: a["username"] for a in list_teacher_accounts(tid)}
    assert set(pids) <= set(accs)
    # รหัสผ่านที่แสดงในหน้าใช้ล็อกอินได้จริง
    import re
    pw = re.findall(r"<td data-label=\"รหัสผ่าน\"><code>([^<]+)</code>", page.text)[0]
    teacher = _login(accs[pids[0]], pw)
    assert teacher.get("/me/letters").status_code == 200

    # ครูใส่อีเมลเอง (รูปแบบผิดไม่บันทึก)
    teacher.post("/me/email", data={"email": "ไม่ใช่อีเมล", "back": "/me/letters"})
    teacher.post("/me/email", data={"email": "kru.test@example.com", "back": "/account/profile"})
    assert "kru.test@example.com" in teacher.get("/account/profile").text
    db = session_for(tid)
    try:
        assert db.get(Person, pids[0]).email == "kru.test@example.com"
    finally:
        db.close()

    # ไอดีย่อยที่ไม่ใช่ไอดีหลัก สร้างบัญชีไม่ได้
    assert teacher.post("/admin/staff-accounts/create", data={"pid": pids[1:]}).status_code in (303, 403)

    env.post("/admin/incoming", data={"fiscal_year": 2570, "subject": "หนังสือส่งเข้าอีเมล"})
    db = session_for(tid)
    try:
        rid = db.query(IncomingLetter).filter_by(subject="หนังสือส่งเข้าอีเมล").one().id
    finally:
        db.close()
    env.post(f"/admin/incoming/{rid}/route", data={"action": "send", "note": "แจ้งทราบ", "pid": pids})
    for _ in range(40):
        if sent:
            break
        time.sleep(0.05)
    assert len(sent) == 1        # คนที่ 2 ไม่มีอีเมล ไม่ส่ง
    to, subject, html = sent[0]
    assert to == "kru.test@example.com" and "หนังสือส่งเข้าอีเมล" in subject and ("/me/letters/" in html or "%2Fme%2Fletters%2F" in html)
