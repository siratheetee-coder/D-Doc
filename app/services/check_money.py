"""Link payment-method records to existing ledger expenses, never post twice."""
import math
from app.models import FinanceTxn, CheckPayment, LunchLedger


def eligible(db, check, txn):
    if not txn or txn.kind != 'out' or not math.isfinite(txn.amount or 0) or txn.amount <= 0:
        return False
    if (txn.account_id, txn.fiscal_year) != (check.account_id, check.fiscal_year):
        return False
    if round(txn.amount - (check.amount or 0), 2) != 0:
        return False
    if not txn.date or not check.date or txn.date.date() != check.date.date():
        return False
    if db.query(CheckPayment).filter(CheckPayment.txn_id==txn.id, CheckPayment.id!=check.id).first():
        return False
    # Lunch edits can replace its mirrored transaction; keep those at their source for now.
    return not db.query(LunchLedger).filter_by(finance_txn_id=txn.id).first()


def candidates(db, check):
    if check.txn_id:
        return []
    return [t for t in db.query(FinanceTxn).filter_by(account_id=check.account_id,
            fiscal_year=check.fiscal_year,kind='out').order_by(FinanceTxn.date.desc(),FinanceTxn.id.desc())
            if eligible(db,check,t)]
