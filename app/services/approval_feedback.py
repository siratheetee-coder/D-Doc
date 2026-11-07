"""Approval results addressed to the submitting account, with post-commit mail."""
import logging
import re
from html import escape

log = logging.getLogger(__name__)


def recipient(db, a, tid):
    if not tid:
        return ''
    from app.accounts import Account, acc_session
    from app.models import Person
    person = db.get(Person, a.sent_pid) if a.sent_pid else None
    with acc_session() as accounts:
        q = accounts.query(Account).filter_by(tenant_id=tid, active=True)
        account = None
        if a.sent_uid:
            account = q.filter_by(id=a.sent_uid).first()
        elif a.sent_pid:
            matches = q.filter_by(person_id=a.sent_pid).all()
            if len(matches) == 1:
                account = matches[0]
        elif a.sent_by:
            # Old requests lack the account ID. Only accept an unambiguous exact match.
            matches = q.filter_by(display_name=a.sent_by).all()
            if len(matches) == 1:
                account = matches[0]
        if account and not a.sent_uid:
            a.sent_uid = account.id
        candidates = [person.email if person else '', account.username if account else '']
        email = next((v.strip() for v in candidates if re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', (v or '').strip())), '')
    return email


def title(a):
    return 'ผอ. ส่งกลับให้แก้' if a.status == 'returned' else 'ผอ. อนุมัติแล้ว'


def mail_payload(db, a, tid):
    to = recipient(db, a, tid)
    return dict(to=to, title=title(a), subject=a.title or '', comment=a.comment or '',
                with_sign=bool(a.with_sign), returned=a.status == 'returned', aid=a.id)


def deliver(payload):
    if not payload['to']:
        return
    from app.seller_config import SELLER
    from app.services.mailer import send_email
    url = (SELLER.get('base_url') or '').rstrip('/') + '/approvals/doc/' + str(payload['aid'])
    detail = ('กรุณาตรวจเหตุผลและแก้ไขก่อนส่งใหม่' if payload['returned'] else
              'อนุมัติพร้อมแปะลายเซ็น ผอ. ในเอกสารของขั้นนี้' if payload['with_sign'] else
              'อนุมัติในระบบแล้ว โดย ผอ. ลงนามด้วยมือในเอกสาร')
    body = ('<h2>' + escape(payload['title']) + '</h2><p>' + escape(payload['subject']) + '</p><p>' + detail + '</p>'
            + ('<p>ความเห็น: ' + escape(payload['comment']) + '</p>' if payload['comment'] else '')
            + '<p><a href="' + escape(url, quote=True) + '">เปิดดูผลการพิจารณา</a></p>')
    try:
        if not send_email(payload['to'], '[Easy Ekkasan] ' + payload['title'], body):
            log.warning('Approval result email was not delivered (approval %s)', payload['aid'])
    except Exception:
        log.warning('Approval result email failed (approval %s)', payload['aid'])


def notices(db, uid):
    from app.models import Approval
    if not uid:
        return []
    rows = (db.query(Approval).filter(Approval.sent_uid == uid, Approval.result_read_at.is_(None),
            Approval.status.in_(['approved', 'returned'])).order_by(Approval.decided_at.desc()).limit(30).all())
    return [dict(id='ap' + str(a.id), title=title(a), reason=(a.comment or a.title)[:200], tag='ผลอนุมัติ',
                 level='warn' if a.status == 'returned' else 'info', href=f'/approvals/result/{a.id}') for a in rows]
