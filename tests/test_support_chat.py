from tests.test_subsidy import env
from app.accounts import acc_session, Account, Tenant, hash_password, SupportMessage


def test_chat_roundtrip_isolation_unread_and_retry(env):
    from fastapi.testclient import TestClient
    from app.main import app
    with acc_session() as db:
        school=db.query(Account).filter_by(username='demo').one().tenant_id
        admin=db.query(Account).filter_by(role='superadmin').first()
        if not admin:  # บางลำดับการรันชุดทดสอบไม่มีบัญชีผู้ดูแลตั้งต้น
            admin=Account(username='boss-chat',role='superadmin');db.add(admin)
        admin.password_hash=hash_password('Chat!12345');admin.must_change_password=False
        admin_name=admin.username
        other=Tenant(name='โรงเรียนอื่น',active=True,modules='');db.add(other);db.flush()
        db.add(Account(username='other-chat',password_hash=hash_password('Chat!12345'),tenant_id=other.id,is_owner=True))
        other_id=other.id;db.commit()
    staff=TestClient(app);staff.post('/login',data={'username':admin_name,'password':'Chat!12345'})
    stranger=TestClient(app);stranger.post('/login',data={'username':'other-chat','password':'Chat!12345'})
    assert env.get('/admin-console/chat/inbox').status_code==403
    payload={'body':'สอบถาม <script>alert(1)</script>','nonce':'one','tenant_id':other_id}
    r=env.post('/support/chat/send',data=payload);assert r.status_code==200,r.text
    mid=r.json()['id']
    assert env.post('/support/chat/send',data=payload).json()['id']==mid
    assert stranger.get(f'/support/chat/messages?tenant_id={school}').json()['messages']==[]
    assert stranger.post('/support/chat/read',data={'last_id':mid}).status_code==400
    inbox=staff.get('/admin-console/chat/inbox').json()
    row=next(r for r in inbox if r['id']==school)
    assert row['unread']==1 and row['waiting'] and row['sender'] and row['at'].endswith('Z')
    msgs=staff.get(f'/admin-console/chat/messages?tenant_id={school}').json()['messages']
    assert msgs[0]['body']==payload['body']
    assert staff.post('/admin-console/chat/read',data={'tenant_id':school,'last_id':mid}).status_code==200
    reply=staff.post('/admin-console/chat/send',data={'tenant_id':school,'body':'ตอบกลับ','nonce':'reply'}).json()['id']
    assert env.get('/support/chat/messages?summary=true').json()['unread']==1
    assert env.get('/support/chat/messages').json()['unread']==1  # Fetch alone does not mark read.
    env.post('/support/chat/read',data={'last_id':reply})
    env.post('/support/chat/read',data={'last_id':mid})
    assert env.get('/support/chat/messages?summary=true').json()['unread']==0
    assert env.post('/support/chat/send',data={'body':'x'*4001,'nonce':'long'}).status_code==400
    assert env.post('/support/chat/send',data={'body':'x','nonce':'cross'},headers={'Origin':'https://evil.test'}).status_code==403
    assert not next(r for r in staff.get('/admin-console/chat/inbox').json() if r['id']==school)['waiting']
    assert 'รอตอบ' in staff.get('/admin-console/chat').text
    assert env.get('/support').status_code==200
    with acc_session() as db:
        assert db.query(SupportMessage).count()==2


def test_chat_history_pagination(env):
    with acc_session() as db:
        user=db.query(Account).filter_by(username='demo').one()
        for i in range(105):db.add(SupportMessage(tenant_id=user.tenant_id,sender_id=user.id,sender_name='ครู',staff=False,body=str(i),nonce=str(i)))
        db.commit()
    latest=env.get('/support/chat/messages').json()
    assert len(latest['messages'])==100 and latest['more']
    older=env.get('/support/chat/messages?before='+str(latest['messages'][0]['id'])).json()
    assert len(older['messages'])==5 and not older['more']
    assert older['messages'][0]['body']=='0'
