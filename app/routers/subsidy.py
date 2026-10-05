"""Versioned subsidy estimates, explicit receipts and reviewed budget contributions."""
import json
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (FinanceAccount, FinanceTxn, SubsidySnapshot, SubsidyReceiptLink,
                        SubsidyTermSetting, SubsidyBudgetHistory)
from app.templating import templates
from app.thai_utils import current_academic_year
from app.routers.pages import get_school, serve_generated
from app.services import subsidy as sub

router = APIRouter()


def _year(db):
    return int(getattr(get_school(db), 'academic_year', 0) or current_academic_year())


def _redirect(ay, term, message='saved'):
    return RedirectResponse(f'/finance/subsidy?year={ay}&term={term}&message={message}', status_code=303)


def _snapshot(db, sid):
    row = db.get(SubsidySnapshot, sid)
    if not row:
        raise HTTPException(404, 'ไม่พบฉบับที่ยืนยัน')
    return row


def _page(request, db, ay, term, error='', posted=None, receipt_year=None):
    try:
        data = sub.state(db, ay, term)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    received, links, used = sub.receipt_summary(db, ay, term)
    ry = receipt_year or data['fiscal_year']
    previous = db.query(SubsidyTermSetting).filter_by(fiscal_year=data['fiscal_year']-1, term=term).first()
    extra_entries = {}
    for key, _ in sub.EXTRAS:
        saved = data['config']['extras'].get(key)
        rows = saved.get('entries', [saved]) if saved else [{'amount': '', 'ref': ''}]
        if posted is not None:
            amounts, refs = posted.getlist('extra_'+key), posted.getlist('extra_ref_'+key)
            rows = [{'amount': amounts[i] if i < len(amounts) else '', 'ref': refs[i] if i < len(refs) else ''}
                    for i in range(max(len(amounts), len(refs)))] or [{'amount': '', 'ref': ''}]
        extra_entries[key] = rows
    return templates.TemplateResponse('finance_subsidy.html', {
        'request': request, 's': data, 'levels': sub.LEVELS, 'keys': sub.keys_for(term),
        'names': sub.NAMES, 'extras': sub.EXTRAS, 'error': error, 'posted': posted,
        'extra_entries': extra_entries, 'budget_bases': sub.BUDGET_BASES,
        'previous_rates': json.loads(previous.payload)['rates'] if previous else {},
        'received': received, 'links': links, 'receipt_used': used, 'receipt_year': ry,
        'receipts': db.query(FinanceTxn).filter_by(kind='in', fiscal_year=ry).order_by(FinanceTxn.date.desc(), FinanceTxn.id.desc()).all(),
        'accounts': db.query(FinanceAccount).order_by(FinanceAccount.name).all(),
        'budget_history': db.query(SubsidyBudgetHistory).join(SubsidySnapshot, SubsidySnapshot.id == SubsidyBudgetHistory.snapshot_id).filter(
            SubsidySnapshot.academic_year == ay, SubsidySnapshot.term == term).order_by(SubsidyBudgetHistory.id.desc()).all(),
    }, status_code=422 if error else 200)


@router.get('/finance/subsidy')
def page(request: Request, db: Session = Depends(get_db), year: int | None = None,
         term: int = 1, receipt_year: int | None = None):
    return _page(request, db, year or _year(db), term, receipt_year=receipt_year)


@router.post('/finance/subsidy')
async def save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        ay, term = int(form.get('academic_year', 0)), int(form.get('term', 0))
        sub.fiscal_year(ay, term)
    except ValueError:
        raise HTTPException(400, 'ปีการศึกษาหรือภาคเรียนไม่ถูกต้อง')
    try:
        sub.save(db, ay, term, form)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _page(request, db, ay, term, str(exc), form)
    return _redirect(ay, term)


@router.post('/finance/subsidy/confirm')
async def confirm(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        ay, term = int(form.get('academic_year', 0)), int(form.get('term', 0))
        row = sub.confirm(db, ay, term, form.get('token'))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    return RedirectResponse(f'/finance/subsidy/snapshots/{row.id}', status_code=303)


@router.get('/finance/subsidy/snapshots/{sid}')
def snapshot_page(sid: int, request: Request, db: Session = Depends(get_db)):
    row = _snapshot(db, sid)
    return templates.TemplateResponse('finance_subsidy_snapshot.html', {
        'request': request, 'snapshot': row, 's': json.loads(row.payload), 'names': sub.NAMES,
        'keys': sub.keys_for(row.term),
    })


@router.post('/finance/subsidy/receipts')
async def receipt_link(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        ay, term = int(form.get('academic_year', 0)), int(form.get('term', 0))
        sub.link_receipt(db, ay, term, int(form.get('txn_id', 0)), form.get('item_key'), form.get('round'), form.get('amount'))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    return _redirect(ay, term, 'linked')


@router.post('/finance/subsidy/receipts/{lid}/unlink')
def receipt_unlink(lid: int, db: Session = Depends(get_db)):
    sub.lock(db)
    row = db.get(SubsidyReceiptLink, lid)
    if not row:
        raise HTTPException(404, 'ไม่พบรายการเชื่อม')
    ay, term = row.academic_year, row.term
    db.delete(row)
    db.commit()
    return _redirect(ay, term, 'unlinked')


@router.get('/finance/subsidy/budget-preview')
def budget_preview(request: Request, snapshot_id: int, account_id: int, db: Session = Depends(get_db)):
    row = _snapshot(db, snapshot_id)
    current = sub.state(db, row.academic_year, row.term)
    if current['changed'] or not current['latest'] or current['latest'].id != row.id:
        raise HTTPException(409, 'กรุณายืนยันข้อมูลล่าสุดก่อนตั้งงบ')
    try:
        preview = sub.budget_preview(db, row, account_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return templates.TemplateResponse('finance_subsidy_budget.html', {
        'request': request, 'snapshot': row, 'p': preview, 'token': sub.fingerprint(preview),
        'account': db.get(FinanceAccount, account_id),
    })


@router.post('/finance/subsidy/to-budget')
async def to_budget(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        row = _snapshot(db, int(form.get('snapshot_id', 0)))
        aid = int(form.get('account_id', 0))
        if form.get('reviewed') != '1':
            raise ValueError('ตรวจยอดเดิมและยืนยันว่าไม่มีการนับเงินก้อนนี้ซ้ำก่อนตั้งงบ')
        sub.apply_budget(db, row, aid, form.get('token'))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    return RedirectResponse(f'/finance/accounts/{aid}?year={row.fiscal_year}', status_code=303)


@router.get('/finance/subsidy.docx')
def document(db: Session = Depends(get_db), year: int | None = None, term: int = 1, snapshot_id: int | None = None):
    from app.services.subsidy_report import render
    if snapshot_id:
        row = _snapshot(db, snapshot_id)
        data = json.loads(row.payload)
    else:
        try:
            data = sub.state(db, year or _year(db), term)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    return serve_generated(render(get_school(db), data, snapshot_id),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
