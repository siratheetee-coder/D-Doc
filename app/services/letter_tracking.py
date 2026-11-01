"""Incoming-letter assignments; acknowledgement and completion are independent."""
from datetime import datetime

from app.models import LetterTask
from app.thai_utils import parse_be_date

LABELS = {'pending': 'ยังไม่รายงานผล', 'submitted': 'รอตรวจผล',
          'returned': 'ให้แก้ไขรายงาน', 'done': 'เสร็จสิ้น'}

def overdue(task):
    return bool(task.due_at and task.due_at.date() < datetime.now().date()
                and task.status in ('pending', 'returned'))

def task_context(r):
    tasks = [rc.task for rc in r.recipients if rc.task]
    return dict(tasks=tasks, task_labels=LABELS, task_overdue=overdue,
                task_pids=[t.recipient.person_id for t in tasks],
                task_instruction=tasks[0].instruction if tasks else '',
                task_due=tasks[0].due_at if tasks else None)

def read_assignment(form, recipient_ids):
    """Validate everything before modifying recipients or sending notifications."""
    if form.get('work_mode') != 'task':
        return None
    try:
        selected = set(int(v) for v in form.getlist('task_pid'))
    except (TypeError, ValueError):
        raise ValueError('กรุณาเลือกผู้รับผิดชอบจากรายชื่อผู้รับหนังสือ')
    if not selected or not selected.issubset(set(recipient_ids)):
        raise ValueError('เลือกผู้รับผิดชอบอย่างน้อย 1 คน และต้องเลือกคนนั้นเป็นผู้รับหนังสือด้วย')
    text = (form.get('task_instruction') or '').strip()
    if not text or len(text) > 4000:
        raise ValueError('กรุณาระบุสิ่งที่ต้องดำเนินการ ไม่เกิน 4,000 ตัวอักษร')
    raw = (form.get('task_due') or '').strip()
    due = parse_be_date(raw)
    if raw and not due:
        raise ValueError('กำหนดส่งไม่ถูกต้อง กรุณาระบุวัน/เดือน/ปี พ.ศ.')
    return selected, text, due

def configure_tasks(r, assignment):
    for rc in r.recipients:
        if assignment and rc.person_id in assignment[0]:
            if not rc.task:
                rc.task = LetterTask()
            rc.task.instruction, rc.task.due_at = assignment[1:]
        elif rc.task:
            rc.task = None
