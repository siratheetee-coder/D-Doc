"""Explain payments posted by another memo without changing financial ownership."""
import math
from app.models import DisburseMemo, FinanceAccount


def settled_elsewhere(db,memo,info):
    proc=info.get('proc')
    if not proc or info.get('own') or not info.get('rows'):return None
    total=float(info.get('total') or 0)
    requested=float(memo.amount or 0)
    if not math.isfinite(total) or not math.isfinite(requested) or not (0<requested<=total):return None
    if round(float(info.get('remaining') or 0),2)!=0:return None
    rows=info['rows']
    if any(t.kind!='out' or not math.isfinite(t.amount or 0) or (t.amount or 0)<=0
           or not t.disburse_id or t.disburse_id==memo.id for t in rows):return None
    account_ids={t.account_id for t in rows}
    if db.query(FinanceAccount).filter(FinanceAccount.id.in_(account_ids)).count()!=len(account_ids):return None
    ids={t.disburse_id for t in rows}
    owners=list(db.query(DisburseMemo).filter(DisburseMemo.id.in_(ids),DisburseMemo.procurement_id==proc.id)
                .order_by(DisburseMemo.id))
    if len(owners)!=len(ids):return None
    links=[{'id':m.id,'number':m.memo_no or f'บันทึก #{m.id}','subject':m.subject or '',
            'href':f'/finance/disburse/{m.id}#payment-records'} for m in owners]
    from app.services.procurement_claims import state
    claims=state(db,proc)
    return {'overclaimed':claims['valid'] and claims['claimed']>claims['total']+0.005,'claimed':claims['claimed'],'total':claims['total'],'owners':links,'href':links[0]['href'] if len(links)==1 else '#payment-records'}
