"""School-scoped support conversations stored in the central account database."""
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, Form, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.accounts import acc_session, Account, Tenant, SupportMessage as Message, SupportRead
from app.templating import templates

router = APIRouter()

# อีเมลแจ้งผู้ขายเมื่อโรงเรียนส่งข้อความ · โรงเรียนเดียวกันแจ้งไม่ถี่กว่า 10 นาทีครั้ง (ส่งรัว ๆ ไม่ท่วมกล่องเมล)
NOTIFY_GAP = 600
_notified: dict[int, float] = {}


def notify_staff(tid, school, sender, body):
    import threading, time
    now = time.time()
    if now - _notified.get(tid, 0) < NOTIFY_GAP:
        return
    _notified[tid] = now

    def run():
        try:
            from html import escape
            from app.services.mailer import send_email
            from app.services.notifications import notification_email
            to = notification_email()
            if not to:
                return
            from app.seller_config import SELLER
            base = SELLER.get('base_url', '')
            html = (f'<div style="font-family:Tahoma,sans-serif;font-size:15px;line-height:1.7">'
                    f'<p><b>{escape(school)}</b> ส่งข้อความในแชทติดต่อเจ้าหน้าที่</p>'
                    f'<p style="background:#f1f5f9;border-radius:10px;padding:10px 14px;white-space:pre-wrap">'
                    f'<b>{escape(sender)}:</b> {escape(body[:1000])}</p>'
                    f'<p><a href="{base}/admin-console/chat">เปิดแชทเพื่อตอบ</a></p>'
                    f'<p style="color:#888;font-size:13px">โรงเรียนเดียวกันจะแจ้งไม่ถี่กว่า 10 นาทีครั้ง</p></div>')
            send_email(to, f'💬 ข้อความใหม่จาก {school}', html)
        except Exception as e:  # noqa: BLE001
            print('[support-chat] ส่งอีเมลแจ้งไม่ได้:', e)
    threading.Thread(target=run, daemon=True).start()


def identity(request, db, tenant_id):
    user = db.get(Account, request.session.get('uid'))
    if not user or not user.active:
        raise HTTPException(401, 'กรุณาเข้าสู่ระบบใหม่')
    staff = user.role == 'superadmin'
    if request.url.path.startswith('/admin-console/') != staff:
        raise HTTPException(403)
    tid = tenant_id if staff else user.tenant_id
    if not tid or not db.get(Tenant, tid):
        raise HTTPException(404, 'ไม่พบโรงเรียน')
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.url.netloc:
            raise HTTPException(403)
    return user, tid, staff


def unread(db, user, tid, staff):
    cursor = db.get(SupportRead, (user.id, tid))
    return db.query(Message).filter(Message.tenant_id == tid, Message.staff != staff,
                                   Message.id > (cursor.last_id if cursor else 0)).count()


@router.get('/admin-console/chat')
def console(request: Request):
    with acc_session() as db:
        user = db.get(Account, request.session.get('uid'))
        if not user or not user.active or user.role != 'superadmin':
            raise HTTPException(403)
    return templates.TemplateResponse('support_chat_console.html', {'request': request})


@router.get('/admin-console/chat/inbox')
def inbox(request: Request):
    with acc_session() as db:
        user = db.get(Account, request.session.get('uid'))
        if not user or not user.active or user.role != 'superadmin':
            raise HTTPException(403)
        latest = dict(db.query(Message.tenant_id, func.max(Message.id)).group_by(Message.tenant_id).all())
        messages = {m.id: m for m in db.query(Message).filter(Message.id.in_(latest.values())).all()}
        # Aggregate unread messages per school without loading their bodies.
        counts = dict(db.query(Message.tenant_id, func.count(Message.id)).outerjoin(
            SupportRead, (SupportRead.tenant_id == Message.tenant_id) & (SupportRead.account_id == user.id)
        ).filter(Message.staff == False, Message.id > func.coalesce(SupportRead.last_id, 0)).group_by(Message.tenant_id).all())
        rows = []
        for t in db.query(Tenant).all():
            last = messages.get(latest.get(t.id))
            rows.append(dict(id=t.id, name=t.name, unread=counts.get(t.id, 0),
                             preview=last.body[:100] if last else '', last=last.id if last else 0))
        return sorted(rows, key=lambda r: (bool(r['unread']), r['last']), reverse=True)


@router.get('/support/chat/messages')
@router.get('/admin-console/chat/messages')
def messages(request: Request, tenant_id: int = 0, after: int = 0, before: int = 0, summary: bool = False):
    with acc_session() as db:
        user, tid, staff = identity(request, db, tenant_id)
        count = unread(db, user, tid, staff)
        if summary:
            return {'unread': count}
        query = db.query(Message).filter(Message.tenant_id == tid)
        if before:
            query = query.filter(Message.id < before)
        elif after:
            query = query.filter(Message.id > after)
        rows = query.order_by(Message.id.asc() if after and not before else Message.id.desc()).limit(101).all()
        more = len(rows) > 100
        rows = sorted(rows[:100], key=lambda m: m.id)
        return {'unread': count, 'more': more, 'messages': [dict(id=m.id, body=m.body,
            sender=m.sender_name, staff=m.staff, mine=m.sender_id == user.id,
            time=m.created_at.isoformat()+'Z') for m in rows]}


@router.post('/support/chat/send')
@router.post('/admin-console/chat/send')
def send(request: Request, tenant_id: int = Form(0), body: str = Form(''), nonce: str = Form('')):
    body = body.strip()
    if not body or len(body) > 4000 or not nonce or len(nonce) > 80:
        raise HTTPException(400, 'กรอกข้อความ 1–4,000 ตัวอักษร')
    with acc_session() as db:
        user, tid, staff = identity(request, db, tenant_id)
        existing = db.query(Message).filter_by(sender_id=user.id, nonce=nonce).first()
        if existing:
            if existing.tenant_id != tid or existing.body != body:
                raise HTTPException(409, 'กรุณาส่งข้อความใหม่')
            return {'id': existing.id}
        msg = Message(tenant_id=tid, sender_id=user.id, sender_name=user.display_name or user.username,
                      staff=staff, body=body, nonce=nonce)
        db.add(msg)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'ข้อความกำลังส่ง กรุณาลองอีกครั้ง')
        if not staff:
            notify_staff(tid, db.get(Tenant, tid).name, msg.sender_name, body)
        return {'id': msg.id}


@router.post('/support/chat/read')
@router.post('/admin-console/chat/read')
def read(request: Request, tenant_id: int = Form(0), last_id: int = Form(0)):
    with acc_session() as db:
        user, tid, staff = identity(request, db, tenant_id)
        message = db.get(Message, last_id)
        if not message or message.tenant_id != tid:
            raise HTTPException(400)
        # SQLite upsert keeps cursors monotonic even with several open tabs.
        from sqlalchemy.dialects.sqlite import insert
        statement = insert(SupportRead).values(account_id=user.id, tenant_id=tid, last_id=last_id)
        db.execute(statement.on_conflict_do_update(index_elements=['account_id', 'tenant_id'],
                   set_={'last_id': func.max(SupportRead.last_id, last_id)}))
        db.commit()
        return {'ok': True}
