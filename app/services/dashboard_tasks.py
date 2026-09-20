from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import selectinload
from app.models import MoneyLoan, DisburseMemo, LeaveRequest, TravelRequest


def loan_state(loan, today):
    left = round(float(loan.amount or 0) - sum(float(x.amount or 0) for x in loan.returns), 2)
    if left <= 0.005:
        return 'settled', left
    if not loan.due_date:
        return 'undated', left
    due = loan.due_date.date()
    return ('overdue' if due < today else 'soon' if due <= today + timedelta(days=7) else 'later'), left


def finance_tasks(db, year, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Bangkok')).date()
    groups = {key: [] for key in ('overdue', 'soon', 'undated')}
    for loan in db.query(MoneyLoan).options(selectinload(MoneyLoan.returns)).all():
        state, left = loan_state(loan, today)
        if state in groups:
            groups[state].append(dict(title=loan.borrower or 'ไม่ระบุผู้ยืม',
                detail=f'สัญญา {loan.contract_no or "-"} · ปีงบ {loan.fiscal_year} · คงค้าง {left:,.2f} บาท',
                due=loan.due_date, href=f'/finance/loans?year={loan.fiscal_year}#loan-{loan.id}'))
    cards = []
    for key, label in [('overdue','เงินยืมเกินกำหนด'),('soon','ครบกำหนดวันนี้–7 วันข้างหน้า'),('undated','เงินยืมยังไม่ระบุวันครบกำหนด')]:
        items = sorted(groups[key], key=lambda x: x['due'] or datetime.max)
        cards.append(dict(label=label, count=len(items), items=items[:5], href=f'/finance/loans?attention={key}', tone='urgent' if key=='overdue' else 'normal'))
    memos = db.query(DisburseMemo).filter(DisburseMemo.fiscal_year==year, DisburseMemo.status.in_(['ร่าง','อนุมัติ'])).order_by(DisburseMemo.id).all()
    cards.append(dict(label=f'บันทึกเบิกจ่ายยังไม่จ่าย · ปี {year}', count=len(memos), tone='normal', href=f'/finance/disburse?attention=1&year={year}',
        items=[dict(title=m.subject or m.memo_no or 'บันทึกเบิกจ่าย', detail=m.status, href=f'/finance/disburse/{m.id}') for m in memos[:5]]))
    return cards


def hr_tasks(db):
    cards=[]
    for model,path,label in [(LeaveRequest,'leave-requests','ใบลา'),(TravelRequest,'travel-requests','ไปราชการ')]:
        for status,stage in [('pending','รอบุคคลตรวจ'),('personnel','รอ ผอ. อนุมัติ')]:
            count=db.query(model).filter(model.status==status).count()
            cards.append(dict(label=f'{label} · {stage}',count=count,items=[],tone='normal',href=f'/hr/{path}?status={status}'))
    return cards
