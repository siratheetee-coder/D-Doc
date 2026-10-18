"""Payment provenance and duplicate checks. Never guess links from similar text."""
import math
from sqlalchemy import or_, update
from app.models import (School, FinanceTxn, DisburseMemo, Procurement,
                        LunchLedger, LunchHireRound, FinanceAccount, AccountItem)


def lock(db):
    db.execute(update(School).values(id=School.id))


def summary(db, memo):
    proc = db.get(Procurement, memo.procurement_id) if memo.procurement_id else None
    own = db.query(FinanceTxn).filter_by(disburse_id=memo.id).all()
    rows = list(own)
    lunch_ids = set()
    managed = False
    if proc:
        mids = db.query(DisburseMemo.id).filter_by(procurement_id=proc.id)
        ledgers = db.query(LunchLedger).filter_by(procurement_id=proc.id).all()
        lunch_ids = {x.finance_txn_id for x in ledgers if x.finance_txn_id}
        managed = bool(ledgers or db.query(LunchHireRound).filter_by(procurement_id=proc.id).first())
        rows = db.query(FinanceTxn).filter(FinanceTxn.kind == 'out', or_(
            FinanceTxn.disburse_id.in_(mids), FinanceTxn.id.in_(lunch_ids))).all()
    rows = sorted({x.id: x for x in rows}.values(), key=lambda x: x.id)
    total = round(float((proc.total_amount if proc else memo.amount) or 0), 2)
    paid = round(sum(x.amount or 0 for x in rows), 2)
    return dict(rows=rows, own=own, total=total, paid=paid, remaining=round(total-paid, 2),
                lunch_ids=lunch_ids, managed=managed, proc=proc)


def validate_amount(value):
    if not math.isfinite(value or 0) or value <= 0:
        raise ValueError('จำนวนเงินที่จ่ายต้องมากกว่า 0')


def validate_new(db, memo, excluding=None):
    validate_amount(memo.amount)
    if not db.get(FinanceAccount, memo.account_id):
        raise ValueError('กรุณาเลือกบัญชีที่จ่ายเงิน')
    if memo.item_id:
        item = db.get(AccountItem, memo.item_id)
        if not item or (item.account_id, item.fiscal_year) != (memo.account_id, memo.fiscal_year):
            raise ValueError('หมวดไม่ตรงกับบัญชีหรือปีงบประมาณ กรุณาเลือกใหม่')
    info = summary(db, memo)
    paid = sum(x.amount or 0 for x in info['rows'] if x.id != excluding)
    if round(paid + memo.amount - info['total'], 2) > 0:
        raise ValueError('ยอดที่เบิกครั้งนี้เกินยอดคงเหลือของเรื่อง กรุณาตรวจรายการจ่ายเดิม')
    if info['managed']:
        raise ValueError('เรื่องนี้ลงจ่ายจากงานอาหารกลางวัน กรุณาลงจ่ายที่ต้นทางแล้วเชื่อมรายการเดิม')


def compatible(db, memo, txn):
    if not txn or txn.disburse_id or txn.kind != 'out':
        return False
    if (txn.account_id, txn.item_id, txn.fiscal_year) != (memo.account_id, memo.item_id, memo.fiscal_year):
        return False
    if not math.isfinite(txn.amount or 0) or round((txn.amount or 0) - (memo.amount or 0), 2) != 0 or txn.amount <= 0:
        return False
    proc = db.get(Procurement, memo.procurement_id) if memo.procurement_id else None
    project_id = memo.project_id or (proc.project_id if proc else None)
    if txn.project_id and txn.project_id != project_id:
        return False
    ledger = db.query(LunchLedger).filter_by(finance_txn_id=txn.id).first()
    return not ledger or bool(memo.procurement_id and ledger.procurement_id == memo.procurement_id)


def candidates(db, memo):
    return [t for t in db.query(FinanceTxn).filter_by(kind='out', account_id=memo.account_id,
            fiscal_year=memo.fiscal_year, disburse_id=None).order_by(FinanceTxn.date.desc(), FinanceTxn.id.desc())
            if compatible(db, memo, t)]


def detach_original(db, txn):
    if txn.disburse_id and txn.linked_existing:
        memo = db.get(DisburseMemo, txn.disburse_id)
        if memo:
            memo.status = 'อนุมัติ'
        txn.disburse_id = None
        txn.linked_existing = False
