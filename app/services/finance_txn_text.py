"""Payment register descriptions come from the linked case, never the payee."""
import re
from sqlalchemy.orm import object_session
from app.models import DisburseMemo, Procurement

def memo_subject(memo, db=None, procurements=None):
    subject = (memo.subject or '').strip()
    if subject:
        return subject
    pid = memo.procurement_id
    if pid:
        if procurements is not None:
            proc = procurements.get(pid)
        else:
            db = db or object_session(memo)
            proc = db.get(Procurement, pid) if db else None
        if proc:
            return (proc.subject or '').strip()
    return ''

def payment_note(memo, n=None, total=None):
    subject = memo_subject(memo) or '(ยังไม่ระบุชื่อเรื่อง)'
    note = subject if subject.startswith('จ่าย ') else 'จ่าย ' + subject
    if n:
        note += f' (ส่วนที่ {n} จาก {total} ของยอด {float(memo.amount or 0):,.2f} บาท)'
    return note

def display_notes(txns, db=None):
    """Resolve existing linked entries without rewriting notes or any money data.

    Bulk-load sources so a combined register does not query once per row.
    Unlinked/manual transactions keep their original description.
    """
    rows = [t for t in txns if t.kind == 'out' and getattr(t, 'disburse_id', None)]
    if not rows:
        return {}
    if db is None:
        db = next((object_session(t) for t in rows if getattr(t, '_sa_instance_state', None)
                   and object_session(t) is not None), None)
    if db is None:
        return {}
    mids = {t.disburse_id for t in rows}
    memos = {m.id:m for m in db.query(DisburseMemo).filter(DisburseMemo.id.in_(mids)).all()}
    pids = {m.procurement_id for m in memos.values() if not (m.subject or '').strip() and m.procurement_id}
    procs = {p.id:p for p in db.query(Procurement).filter(Procurement.id.in_(pids)).all()} if pids else {}
    result = {}
    for txn in rows:
        memo = memos.get(txn.disburse_id)
        if memo is None:
            continue
        subject = memo_subject(memo, db, procs) or '(ยังไม่ระบุชื่อเรื่อง)'
        note = subject if subject.startswith('จ่าย ') else 'จ่าย ' + subject
        split = re.search(r' (\(ส่วนที่ \d+ จาก \d+ ของยอด [\d,.]+ บาท\))$', txn.note or '')
        result[txn.id] = note + (' ' + split.group(1) if split else '')
    return result
