from tests.test_subsidy import env
from app.accounts import acc_session, Account, Tenant, AiQuestion, hash_password


def _enable(on=True):
    with acc_session() as db:
        t = db.get(Tenant, db.query(Account).filter_by(username='demo').one().tenant_id)
        t.ai_help = on
        t.plan = 'trial'   # ทดลองใช้: ขึ้นกับปุ่มเปิดในคอนโซล
        db.commit()
        return t.id


def test_member_on_automatically_trial_off(env):
    from app.services import ai_help as ai
    with acc_session() as db:
        t = db.get(Tenant, db.query(Account).filter_by(username='demo').one().tenant_id)
        t.plan = 'member'; t.ai_help = False; db.commit()
        assert ai.on_for(t)
        t.plan = 'trial'; db.commit()
    assert env.get('/ai/status').json()['why'] == 'off'
    assert env.post('/ai/ask', data={'q': 'ยอดยกมา'}).status_code == 403
    assert 'id="aiHelpOpen"' in env.get('/finance').text


def test_ai_ask_quota_and_log(env, monkeypatch):
    from app.services import ai_help as ai
    tid = _enable()
    monkeypatch.setattr(ai, 'configured', lambda: True)
    seen = {}

    def fake(q, hist, path):
        seen.update(q=q, hist=hist, path=path)
        return 'ไปที่ `/finance/accounts` ครับ', 1.5
    monkeypatch.setattr(ai, 'ask', fake)
    r = env.post('/ai/ask', data={'q': 'กรอกยอดยกมาที่ไหน', 'path': '/finance', 'history': '[{"role":"me","text":"hi"}]'})
    assert r.status_code == 200, r.text
    assert r.json() == {'answer': 'ไปที่ `/finance/accounts` ครับ', 'left': ai.DAILY_LIMIT - 1}
    assert seen['path'] == '/finance' and seen['hist'][0]['text'] == 'hi'
    with acc_session() as db:
        row = db.query(AiQuestion).one()
        assert row.tenant_id == tid and row.cost_thb == 1.5
        for _ in range(ai.DAILY_LIMIT - 1):
            db.add(AiQuestion(tenant_id=tid, account_id=row.account_id, question='x'))
        db.commit()
    r = env.post('/ai/ask', data={'q': 'อีกข้อ'})
    assert r.status_code == 429 and 'ครบ' in r.json()['detail']
    assert env.post('/ai/ask', data={'q': 'x'}, headers={'Origin': 'https://evil.test'}).status_code == 403


def test_ai_teacher_blocked_and_no_key(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ai_help as ai
    tid = _enable()
    monkeypatch.setattr(ai, 'configured', lambda: False)
    assert env.post('/ai/ask', data={'q': 'x'}).status_code == 503
    assert env.get('/ai/status').json()['why'] == 'nokey'
    with acc_session() as db:
        db.add(Account(username='t1.ai', password_hash=hash_password('Teach!12345'), tenant_id=tid, person_id=1))
        db.commit()
    teacher = TestClient(app)
    teacher.post('/login', data={'username': 't1.ai', 'password': 'Teach!12345'})
    assert teacher.get('/ai/status').json()['why'] == 'teacher'


def test_console_toggle(env, monkeypatch):
    from app.services import ai_help as ai
    monkeypatch.setattr(ai, 'configured', lambda: True)
    from fastapi.testclient import TestClient
    from app.main import app
    with acc_session() as db:
        db.add(Account(username='boss-ai', password_hash=hash_password('Chat!12345'), role='superadmin'))
        db.commit()
    name = 'boss-ai'
    tid = _enable(False)
    staff = TestClient(app)
    staff.post('/login', data={'username': name, 'password': 'Chat!12345'})
    assert staff.post(f'/admin-console/tenant/{tid}/ai', data={'on': '1'}).status_code == 200
    assert env.get('/ai/status').json()['ok']
    assert staff.get('/admin-console/ai').status_code == 200


def test_school_message_emails_owner_once(env, monkeypatch):
    from app.routers import support_chat as sc
    sent = []
    monkeypatch.setattr(sc, '_notified', {})
    monkeypatch.setattr('app.services.mailer.send_email', lambda to, subject, html: sent.append(subject))
    monkeypatch.setattr('app.services.notifications.notification_email', lambda: 'owner@example.com')
    monkeypatch.setattr('threading.Thread', lambda target, daemon: type('T', (), {'start': lambda self: target()})())
    env.post('/support/chat/send', data={'body': 'ช่วยด้วย', 'nonce': 'a1'})
    env.post('/support/chat/send', data={'body': 'อีกข้อ', 'nonce': 'a2'})
    assert len(sent) == 1 and 'ข้อความใหม่' in sent[0]
