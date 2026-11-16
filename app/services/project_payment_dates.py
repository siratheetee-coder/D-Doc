"""Show document and actual payment dates separately, following explicit source links only."""
from collections import defaultdict
from sqlalchemy import or_
from app.models import DisburseMemo, FinanceTxn, LunchLedger
from app.thai_utils import thai_date_short


def attach(db, groups):
    docs=[d for g in groups for d in g['docs']]
    proc_ids={d['id'] for d in docs if d['type']=='proc'}
    memo_ids={d['id'] for d in docs if d['type']=='memo'}
    loan_ids={d['id'] for d in docs if d['type']=='loan'}
    memos={m.id:m for m in db.query(DisburseMemo).filter(or_(DisburseMemo.id.in_(memo_ids),
                                                           DisburseMemo.procurement_id.in_(proc_ids)))}
    ledgers=list(db.query(LunchLedger).filter(LunchLedger.procurement_id.in_(proc_ids),
                                             LunchLedger.finance_txn_id.isnot(None))) if proc_ids else []
    ledger_proc={r.finance_txn_id:r.procurement_id for r in ledgers}
    by_doc=defaultdict(dict)
    txns=db.query(FinanceTxn).filter(FinanceTxn.kind=='out',FinanceTxn.no_count.isnot(True),or_(
        FinanceTxn.disburse_id.in_(memos),FinanceTxn.id.in_(ledger_proc),FinanceTxn.loan_id.in_(loan_ids)))
    for t in txns:
        fact={'id':t.id,'date':thai_date_short(t.date) if t.date else 'ยังไม่ระบุวันที่',
              'ref':t.ref or f'รายการ #{t.id}',
              'url':f'/finance/accounts/{t.account_id}?year={t.fiscal_year}#t{t.id}'}
        memo=memos.get(t.disburse_id)
        if memo:
            by_doc[('memo',memo.id)][t.id]=fact
            if memo.procurement_id:by_doc[('proc',memo.procurement_id)][t.id]=fact
        if t.id in ledger_proc:by_doc[('proc',ledger_proc[t.id])][t.id]=fact
        if t.loan_id:by_doc[('loan',t.loan_id)][t.id]=fact
    for d in docs:
        d['payments']=list(by_doc[(d['type'],d['id'])].values())
    return groups
