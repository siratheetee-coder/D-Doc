"""Explicit loan cash movements; existing contracts never post automatically."""
from app.models import FinanceTxn, FinanceAccount, AccountItem, MoneyLoan, LoanReturn, LunchLedger
from app.services.disburse_payments import lock, validate_amount
from app.thai_utils import current_fiscal_year


def linked(db, loan_id, return_id=0):
    return db.query(FinanceTxn).filter_by(loan_id=loan_id, loan_return_id=return_id or None).first()


def details(db, loan, return_id=0):
    ret = db.get(LoanReturn, return_id) if return_id else None
    if return_id and (not ret or ret.loan_id != loan.id or ret.kind != 'เงินสด'):
        raise ValueError('เลือกได้เฉพาะรายการคืนเงินสดของสัญญานี้ ใบสำคัญไม่ต้องลงรับเงิน')
    amount = ret.amount if ret else loan.amount
    date = ret.date if ret else (loan.receive_date or loan.date)
    validate_amount(amount)
    if not date:
        raise ValueError('กรุณาระบุวันที่ได้รับเงินหรือวันที่คืนเงินสดให้ครบ')
    fy = current_fiscal_year(date)
    if not ret and fy != loan.fiscal_year:
        raise ValueError('วันที่จ่ายเงินยืมไม่ตรงกับปีงบประมาณของสัญญา กรุณาตรวจข้อมูล')
    return ret, amount, date, fy, 'in' if ret else 'out'


def eligible(db, txn, account_id, amount, fy, kind, item_id=None):
    if not txn or txn.disburse_id or txn.loan_id or txn.loan_return_id:
        return False
    if (txn.account_id, txn.fiscal_year, txn.kind, txn.item_id) != (account_id, fy, kind, item_id):
        return False
    if round((txn.amount or 0)-amount, 2) != 0:
        return False
    return not db.query(LunchLedger).filter_by(finance_txn_id=txn.id).first()


def record(db, loan_id, return_id, mode, account_id, item_id=None, txn_id=0):
    lock(db)
    loan = db.get(MoneyLoan, loan_id)
    if not loan:
        raise ValueError('ไม่พบสัญญายืมเงิน')
    ret, amount, date, fy, kind = details(db, loan, return_id)
    old = linked(db, loan_id, return_id)
    if old:
        return old
    if ret and not linked(db, loan_id):
        raise ValueError('กรุณาลงจ่ายเงินยืมหรือเชื่อมรายการจ่ายเดิมก่อนรับคืนเงินสด')
    if not db.get(FinanceAccount, account_id):
        raise ValueError('กรุณาเลือกบัญชีที่รับหรือจ่ายเงินจริง')
    if item_id:
        item = db.get(AccountItem, item_id)
        if not item or (item.account_id, item.fiscal_year) != (account_id, fy):
            raise ValueError('หมวดไม่ตรงกับบัญชีหรือปีงบประมาณของรายการ')
    if mode == 'link':
        txn = db.get(FinanceTxn, txn_id)
        if not eligible(db, txn, account_id, amount, fy, kind, item_id):
            raise ValueError('รายการเดิมต้องเป็นบัญชี หมวด ปี ประเภท และยอดตรงกัน และยังไม่เชื่อมเอกสารอื่น')
    elif mode == 'new':
        txn = FinanceTxn(account_id=account_id, item_id=item_id, fiscal_year=fy, date=date,
                         kind=kind, amount=amount, ref=(ret.receipt_no if ret else loan.contract_no) or '',
                         category='รับคืนเงินยืม' if ret else 'จ่ายเงินยืม', note=loan.borrower or '')
        db.add(txn)
    else:
        raise ValueError('เลือกลงรายการใหม่หรือเชื่อมรายการเดิม')
    txn.loan_id = loan.id
    txn.loan_return_id = return_id or None
    db.flush()
    return txn


def unlink(db, loan_id, return_id):
    lock(db)
    if not return_id and db.query(FinanceTxn).filter(FinanceTxn.loan_id==loan_id, FinanceTxn.loan_return_id.isnot(None)).first():
        raise ValueError('กรุณายกเลิกการเชื่อมรายการคืนเงินสดก่อนยกเลิกการเชื่อมจ่ายเงินยืม')
    txn = linked(db, loan_id, return_id)
    if txn:
        txn.loan_id = None
        txn.loan_return_id = None
