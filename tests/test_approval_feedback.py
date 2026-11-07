import io, os, zipfile
from pathlib import Path
from tests.test_approval import env, _latest
from app.models import Approval, Person
from app.tenancy import session_for


def send(c, tid, pid, stage='proc_order'):
    assert c.post(f'/procurement/{pid}/approval', data={'kind':stage,'action':'send'}, follow_redirects=False).status_code==303
    return _latest(tid, stage, pid)[0]


def test_owner_without_person_gets_result_notice_email_after_commit_and_read_is_private(env, monkeypatch):
    from app.accounts import Account, acc_session
    from app.services.approval_feedback import notices
    c,tid,ids=env
    with acc_session() as s:
        user=s.query(Account).filter_by(tenant_id=tid,username='demo').one()
        uid=user.id;user.person_id=None;user.is_director=False;user.username='owner@example.org';s.commit()
    c.post('/login',data={'username':'owner@example.org','password':'Demo!2569'})
    aid=send(c,tid,ids['proc'])
    with session_for(tid) as s:
        a=s.get(Approval,aid);assert a.sent_uid==uid and a.sent_pid is None
    with acc_session() as s:
        user=s.get(Account,uid);user.person_id=ids['person'];user.is_director=True;s.commit()
    c.post('/login',data={'username':'owner@example.org','password':'Demo!2569'})
    mail=[]
    def smtp(to,subject,html):
        with session_for(tid) as s:assert s.get(Approval,aid).status=='approved'
        mail.append((to,subject,html));return True
    monkeypatch.setattr('app.services.mailer.send_email',smtp)
    assert c.post(f'/approvals/doc/{aid}/decide',data={'action':'sign'},follow_redirects=False).status_code==303
    assert len(mail)==1 and mail[0][0]=='owner@example.org' and 'ลายเซ็น ผอ.' in mail[0][2]
    assert f'/approvals/result/{aid}' in c.get('/finance').text
    with session_for(tid) as s:
        assert len(notices(s,uid))==1 and notices(s,uid+1000)==[]
        s.get(Approval,aid).sent_uid=uid+1000;s.commit()
    assert c.get(f'/approvals/result/{aid}',follow_redirects=False).headers['location']=='/'
    with session_for(tid) as s:
        a=s.get(Approval,aid);assert a.result_read_at is None;a.sent_uid=uid;s.commit()
    assert c.get(f'/approvals/result/{aid}',follow_redirects=False).headers['location']==f'/approvals/doc/{aid}'
    with session_for(tid) as s:assert notices(s,uid)==[]
    c.post(f'/approvals/doc/{aid}/decide',data={'action':'sign'})
    assert len(mail)==1


def test_batch_deduplicates_failed_items_and_mail_failure_does_not_undo_decision(env,monkeypatch):
    c,tid,ids=env
    with session_for(tid) as s:
        s.get(Person,ids['person']).email='teacher@example.org';s.commit()
    aid=send(c,tid,ids['proc'])
    attempted=[]
    def smtp(*args):attempted.append(args);raise RuntimeError('SMTP down')
    monkeypatch.setattr('app.services.mailer.send_email',smtp)
    response=c.post('/approvals/docs/decide-many',data={'aid':[str(aid),str(aid),'99999'],'action':'approve'},follow_redirects=False)
    assert response.status_code==303 and len(attempted)==1
    assert _latest(tid,'proc_order',ids['proc'])[1]=='approved'
    assert 'err=' in response.headers['location']


def test_return_email_escapes_text_and_new_send_does_not_erase_history(env,monkeypatch):
    c,tid,ids=env
    with session_for(tid) as s:s.get(Person,ids['person']).email='teacher@example.org';s.commit()
    aid=send(c,tid,ids['proc']);mail=[]
    monkeypatch.setattr('app.services.mailer.send_email',lambda *a:mail.append(a) or True)
    c.post(f'/approvals/doc/{aid}/decide',data={'action':'return','comment':'ตรวจ <script>alert(1)</script>'})
    assert len(mail)==1 and '&lt;script&gt;' in mail[0][2] and '<script>' not in mail[0][2]
    new=send(c,tid,ids['proc']);assert new!=aid
    with session_for(tid) as s:assert s.get(Approval,aid).status=='returned' and s.get(Approval,new).status=='pending'


def test_rendered_director_controls_and_signature_scope(env,monkeypatch):
    c,tid,ids=env;monkeypatch.setattr('app.services.mailer.send_email',lambda *a:True)
    aid=send(c,tid,ids['proc']);send(c,tid,ids['proc'],'proc_pay')
    inbox=c.get('/approvals');assert inbox.status_code==200 and 'ap-review-btn' in inbox.text
    detail=c.get(f'/approvals/doc/{aid}');assert 'ลายเซ็นของ ผอ. เท่านั้น' in detail.text
    if os.environ.get('APPROVAL_CAPTURE'):
        out=Path(os.environ['APPROVAL_CAPTURE']);(out/'inbox.html').write_text(inbox.text,encoding='utf-8')
        (out/'detail.html').write_text(detail.text,encoding='utf-8')
    from app.models import School
    from PIL import Image
    from app.services.signature import signatures_dir
    from tests.test_approval import SIG_BYTES
    path=signatures_dir()/'staff-test.png';Image.new('RGBA',(150,40),(180,0,0,255)).save(path)
    with session_for(tid) as s:
        s.add(Person(name='นายเจ้าหน้าที่ ทดสอบ',signature='staff-test.png'));s.query(School).first().officer_name='นายเจ้าหน้าที่ ทดสอบ';s.commit()
    c.post(f'/approvals/doc/{aid}/decide',data={'action':'sign'})
    response=c.get(f'/approvals/doc/{aid}/file',params={'doc':'ใบสั่งซื้อ/สั่งจ้าง'})
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        images=[z.read(n) for n in z.namelist() if n.startswith('word/media/')]
        assert SIG_BYTES in images and path.read_bytes() not in images


def test_legacy_recipient_resolution_is_unambiguous_and_scoped_to_school(env):
    from app.accounts import Account,Tenant,acc_session
    from app.services.approval_feedback import recipient
    c,tid,ids=env
    with acc_session() as accounts:
        current=accounts.query(Account).filter_by(tenant_id=tid,username='demo').one();uid=current.id
        other=Tenant(name='Other school',slug='approval-other');accounts.add(other);accounts.flush()
        outsider=Account(tenant_id=other.id,username='outsider@example.org',display_name=current.display_name,password_hash='unused',active=True)
        accounts.add(outsider);accounts.commit();other_uid=outsider.id;name=current.display_name
    with session_for(tid) as db:
        old=Approval(kind='proc_order',ref_id=ids['proc'],sent_by=name)
        recipient(db,old,tid);assert old.sent_uid==uid
        old.sent_uid=other_uid;assert recipient(db,old,tid)==''
        old.sent_uid=None
        with acc_session() as accounts:
            accounts.add(Account(tenant_id=tid,username='ambiguous@example.org',display_name=name,password_hash='unused',active=True));accounts.commit()
        assert recipient(db,old,tid)=='' and old.sent_uid is None
