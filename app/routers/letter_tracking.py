"""Director tracking, per-recipient reports and protected report attachments."""
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import update
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import IncomingLetter, LetterRecipient, LetterTask, LetterTaskReport
from app.templating import templates
from app.thai_utils import current_fiscal_year, fiscal_year_options
from app.services.letter_tracking import LABELS, overdue

router = APIRouter()

def back(url, message, error=False):
    return RedirectResponse(url + '?' + urlencode({'err' if error else 'msg': message}), status_code=303)

def manager(request):
    return bool(request.session.get('owner') or request.session.get('director'))

def report_dir():
    from app.tenancy import get_data_dir, current_school_id
    sid = current_school_id.get()
    if not sid:
        raise RuntimeError('No school selected')
    folder = get_data_dir() / 'schools' / str(sid) / 'letter_reports'
    folder.mkdir(parents=True, exist_ok=True)
    return folder

@router.get('/admin/incoming-tracking')
def tracking(request: Request, db: Session = Depends(get_db), year: int | None = None,
             status: str = '', q: str = ''):
    fy = current_fiscal_year() if year is None else year
    query = (db.query(IncomingLetter).options(selectinload(IncomingLetter.recipients)
             .selectinload(LetterRecipient.task)).filter_by(route_status='sent'))
    if fy:
        query = query.filter(IncomingLetter.fiscal_year == fy)
    rows = query.order_by(IncomingLetter.sent_at.desc(), IncomingLetter.id.desc()).all()
    cards = []
    for r in rows:
        tasks = [x.task for x in r.recipients if x.task]
        c = dict(r=r, total=len(r.recipients), acked=sum(bool(x.ack_at) for x in r.recipients),
                 review=sum(t.status == 'submitted' for t in tasks),
                 done=sum(t.status == 'done' for t in tasks), tasks=len(tasks),
                 overdue=sum(overdue(t) for t in tasks))
        cards.append(c)
    counts = dict(total=len(cards), unread=sum(c['acked'] < c['total'] for c in cards),
                  review=sum(c['review'] for c in cards), overdue=sum(c['overdue'] for c in cards))
    if status == 'unread': cards = [c for c in cards if c['acked'] < c['total']]
    if status == 'review': cards = [c for c in cards if c['review']]
    if status == 'overdue': cards = [c for c in cards if c['overdue']]
    if q.strip(): cards = [c for c in cards if q.strip().casefold() in (c['r'].subject or '').casefold()]
    years = fiscal_year_options([x[0] for x in db.query(IncomingLetter.fiscal_year).distinct()], fy or current_fiscal_year())
    return templates.TemplateResponse('incoming_tracking.html', dict(request=request, cards=cards,
        counts=counts, fiscal_year=fy, years=years, status=status, q=q))

@router.post('/me/letters/{rcid}/report')
async def submit_report(rcid: int, request: Request, db: Session = Depends(get_db),
                        body: str = Form(''), version: int = Form(-1),
                        attachment: UploadFile | None = File(None)):
    from app.routers.admin import _my_rc
    rc = _my_rc(db, request, rcid)
    url = f'/me/letters/{rcid}'
    if not rc or not rc.task:
        return back('/me/letters', 'ไม่พบงานที่มอบหมายถึงคุณ', True)
    task = rc.task
    if task.status not in ('pending', 'returned'):
        return back(url, 'รายงานนี้ส่งแล้ว กรุณารอผลการตรวจ', True)
    body = body.strip()
    if not body or len(body) > 8000:
        return back(url, 'กรุณาระบุผลการดำเนินงาน ไม่เกิน 8,000 ตัวอักษร', True)
    data, ext, filename = b'', '', ''
    if attachment and attachment.filename:
        filename = Path(attachment.filename.replace('\\', '/')).name[:200]
        data = await attachment.read(10 * 1024 * 1024 + 1)
        if not data or len(data) > 10 * 1024 * 1024:
            return back(url, 'ไฟล์แนบต้องมีขนาดไม่เกิน 10 MB และไม่เป็นไฟล์ว่าง', True)
        if data.startswith(b'%PDF'): ext = 'pdf'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'): ext = 'png'
        elif data.startswith(b'\xff\xd8\xff'): ext = 'jpg'
        elif filename.lower().endswith('.docx'):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if 'word/document.xml' in z.namelist() and '[Content_Types].xml' in z.namelist(): ext = 'docx'
            except (zipfile.BadZipFile, OSError): pass
        if not ext:
            return back(url, 'รองรับไฟล์ PDF, Word (.docx), JPG และ PNG เท่านั้น', True)
    changed = db.execute(update(LetterTask).where(LetterTask.id == task.id,
        LetterTask.version == version, LetterTask.status.in_(('pending', 'returned')))
        .values(status='submitted', version=version + 1).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        return back(url, 'ข้อมูลเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่ก่อนส่งรายงาน', True)
    path = None
    try:
        name = uuid.uuid4().hex + '.' + ext if ext else ''
        if name:
            path = report_dir() / name
            path.write_bytes(data)
        db.add(LetterTaskReport(task_id=task.id, body=body, file_path=name, file_name=filename))
        # Deliberately do not set ack_at: submitting work and acknowledging are separate actions.
        db.commit()
    except Exception:
        db.rollback()
        if path: path.unlink(missing_ok=True)
        raise
    return back(url, 'ส่งรายงานผลแล้ว รอ ผอ. ตรวจผลการดำเนินงาน')

@router.post('/admin/incoming/{rid}/tasks/{taskid}/review')
async def review_report(rid: int, taskid: int, request: Request, db: Session = Depends(get_db)):
    url = f'/admin/incoming/{rid}'
    if not manager(request):
        return back(url, 'เฉพาะ ผอ. หรือผู้ดูแลหลักที่ตรวจผลได้', True)
    task = db.get(LetterTask, taskid)
    if not task or task.recipient.letter_id != rid or task.recipient.letter.route_status != 'sent':
        return back('/admin/incoming-tracking', 'ไม่พบงานนี้', True)
    form = await request.form()
    action, note = form.get('decision'), (form.get('review_note') or '').strip()
    if action not in ('done', 'returned') or len(note) > 4000 or (action == 'returned' and not note):
        return back(url, 'กรุณาระบุสิ่งที่ต้องแก้ไขก่อนส่งกลับ (ไม่เกิน 4,000 ตัวอักษร)', True)
    try: version = int(form.get('version', -1)); reportid = int(form.get('report_id', 0))
    except (TypeError, ValueError): return back(url, 'กรุณาเปิดหน้าใหม่ก่อนตรวจผล', True)
    latest = task.reports[-1] if task.reports else None
    if not latest or latest.id != reportid:
        return back(url, 'รายงานเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่', True)
    changed = db.execute(update(LetterTask).where(LetterTask.id == taskid,
        LetterTask.version == version, LetterTask.status == 'submitted')
        .values(status=action, version=version + 1).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        return back(url, 'รายงานนี้ตรวจแล้ว หรือข้อมูลเปลี่ยน กรุณาเปิดหน้าใหม่', True)
    latest.status, latest.review_note = action, note
    latest.reviewed_at = datetime.now()
    latest.reviewed_by = request.session.get('name') or 'ผู้ตรวจผล'
    from app.services.nav import create_notice
    create_notice(db, task.recipient.person_id, 'ผลตรวจงาน: ' + LABELS[action],
                  reason=note[:120], link=f'/me/letters/{task.recipient_id}', level='warn' if action == 'returned' else 'info')
    db.commit()
    return back(url, 'บันทึกผลตรวจแล้ว')

@router.get('/me/letters/{rcid}/reports/{reportid}/file')
def teacher_report_file(rcid: int, reportid: int, request: Request, db: Session = Depends(get_db)):
    from app.routers.admin import _my_rc
    rc = _my_rc(db, request, rcid)
    report = db.get(LetterTaskReport, reportid)
    if not rc or not rc.task or not report or report.task_id != rc.task.id:
        return back('/me/letters', 'ไม่พบไฟล์นี้', True)
    return download(report)

@router.get('/admin/incoming/{rid}/reports/{reportid}/file')
def admin_report_file(rid: int, reportid: int, db: Session = Depends(get_db)):
    report = db.get(LetterTaskReport, reportid)
    if not report or report.task.recipient.letter_id != rid or report.task.recipient.letter.route_status != 'sent':
        return back('/admin/incoming-tracking', 'ไม่พบไฟล์นี้', True)
    return download(report)

def download(report):
    from app.services.file_upload import SAFE_FILE_NAME
    if not report.file_path or not SAFE_FILE_NAME.fullmatch(report.file_path):
        return back('/me/letters', 'ไม่พบไฟล์แนบ', True)
    path = report_dir() / report.file_path
    if not path.is_file(): return back('/me/letters', 'ไม่พบไฟล์แนบ', True)
    return FileResponse(str(path), filename=report.file_name or path.name,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})
