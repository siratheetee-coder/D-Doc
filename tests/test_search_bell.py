from tests.test_subsidy import env
from app.accounts import acc_session, Account, hash_password


def _school_db():
    from app.tenancy import session_for
    with acc_session() as db:
        tid = db.query(Account).filter_by(username='demo').one().tenant_id
    return tid, session_for(tid)


def test_search_menus_people_money_and_suggest(env):
    from datetime import datetime
    from app.models import FinanceAccount, FinanceTxn, Project
    tid, db = _school_db()
    acc = db.query(FinanceAccount).first() or FinanceAccount(name='เงินอุดหนุน')
    db.add(acc); db.flush()
    db.add(FinanceTxn(account_id=acc.id, fiscal_year=2570, date=datetime(2569, 11, 3), kind='out', amount=127200, note='ค่าอาหารกลางวัน'))
    db.add(Project(name='โครงการพัฒนาห้องสมุดมีชีวิต', plan_year=2570))
    db.commit(); db.close()
    html = env.get('/search?q=ทะเบียนคุมเงิน').text
    assert 'href="/finance/accounts"' in html
    html = env.get('/search?q=127,200').text
    assert 'ค่าอาหารกลางวัน' in html
    assert 'ห้องสมุดมีชีวิต' in env.get('/search?q=ห้องสมุด').text
    sg = env.get('/search/suggest?q=ห้องสมุด').json()['groups']
    assert any(it['title'] == 'โครงการพัฒนาห้องสมุดมีชีวิต' for g in sg for it in g['items'])
    assert env.get('/search/suggest?q=ห').json() == {'groups': []}
    assert 'search-suggest.js' in env.get('/finance').text


def test_search_hides_modules_without_permission(env):
    from fastapi.testclient import TestClient
    from app.main import app
    with acc_session() as db:
        tid = db.query(Account).filter_by(username='demo').one().tenant_id
        db.add(Account(username='sub-admin', password_hash=hash_password('Sub!123456'), tenant_id=tid, modules='admin'))
        db.commit()
    sub = TestClient(app)
    sub.post('/login', data={'username': 'sub-admin', 'password': 'Sub!123456'})
    html = sub.get('/search?q=ทะเบียนคุมเงิน').text
    assert 'href="/finance/accounts"' not in html
    assert 'href="/admin/incoming"' in sub.get('/search?q=หนังสือรับ').text


def test_bell_shows_finance_and_hr_items(env):
    from datetime import date
    from app.models import Person, LeaveRequest
    tid, db = _school_db()
    p = Person(name='ครูทดสอบลา'); db.add(p); db.flush()
    db.add(LeaveRequest(person_id=p.id, leave_type='ลาป่วย', start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), status='pending'))
    db.commit(); db.close()
    html = env.get('/finance').text
    assert 'ใบลารอฝ่ายบุคคลตรวจ 1 เรื่อง' in html
    assert 'class="bell-tag"' in html
