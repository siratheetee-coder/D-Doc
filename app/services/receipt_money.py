"""Receipt evidence links do not create or duplicate cash movements."""
import math
from app.models import FinanceTxn, Receipt, LunchLedger


def eligible(db, receipt, txn):
    if not txn or not math.isfinite(txn.amount or 0) or txn.amount <= 0:
        return False
    kind = 'out' if receipt.kind == 'จ่าย' else 'in'
    if (txn.account_id,txn.fiscal_year,txn.kind)!=(receipt.account_id,receipt.fiscal_year,kind):
        return False
    if round(txn.amount-(receipt.amount or 0),2)!=0:
        return False
    if db.query(Receipt).filter(Receipt.txn_id==txn.id,Receipt.id!=receipt.id).first():
        return False
    return not db.query(LunchLedger).filter_by(finance_txn_id=txn.id).first()


def candidates(db, receipt):
    if receipt.txn_id:
        return []
    return [t for t in db.query(FinanceTxn).filter_by(account_id=receipt.account_id,
        fiscal_year=receipt.fiscal_year,kind='out' if receipt.kind=='จ่าย' else 'in')
        .order_by(FinanceTxn.date.desc(),FinanceTxn.id.desc()) if eligible(db,receipt,t)]


def release_for_deleted_txn(db, txn):
    for receipt in db.query(Receipt).filter_by(txn_id=txn.id).all():
        if receipt.linked_existing:
            receipt.txn_id=None
            receipt.linked_existing=False
        else:
            db.delete(receipt)
