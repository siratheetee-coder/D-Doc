"""Read-only presentation data for the finance landing page."""
from app.models import DisburseMemo, Procurement, LunchHireRound, LunchDisburseLink, FinanceAccount, LunchLedger, FinanceTxn
from app.services import approval, disburse_payments as payments
from app.services.lunch_meals import pays_by_round, round_pay
from app.thai_utils import current_fiscal_year


def memo_status(db, memo, approval_on, own):
    if own:
        outgoing=all(t.kind=='out' and (t.amount or 0)>0 for t in own)
        complete=round(sum(t.amount or 0 for t in own)-float(memo.amount or 0),2)==0
        return dict(code='paid',label='จ่ายแล้ว',tone='green') if outgoing and complete else dict(code='review',label='ตรวจยอดรายการจ่าย',tone='amber')
    if memo.status=='จ่ายแล้ว':return dict(code='review',label='ตรวจรายการจ่าย',tone='amber')
    info=payments.summary(db,memo)
    proc=db.get(Procurement,memo.procurement_id) if memo.procurement_id else None
    if proc and proc.paid_before_system:return dict(code='legacy',label='จ่ายก่อนเริ่มระบบ',tone='muted')
    if info['managed'] or info['lunch_ids']:
        return dict(code='review',label='ตรวจการเชื่อมรายการจ่าย',tone='amber')
    if info['remaining'] < float(memo.amount or 0) or (memo.amount or 0)<=0 or not memo.account_id or not db.get(FinanceAccount,memo.account_id):
        return dict(code='review',label='ตรวจยอดหรือบัญชี',tone='amber')
    src=info.get('lunch_source')
    if src and (src['stale'] or not src['ready']):
        return dict(code='review',label='ตรวจข้อมูลงวด',tone='amber')
    if approval_on:
        state=approval.state(db,'disburse',memo.id,memo)['code']
        if state in ('approved','signed'):return dict(code='ready',label='รอจ่ายจริง',tone='amber')
        if state=='pending':return dict(code='draft',label='รออนุมัติ',tone='purple')
        if state in ('returned','stale'):return dict(code='draft',label='รอแก้ไข',tone='red')
        return dict(code='draft',label='ยังไม่ส่งอนุมัติ',tone='muted')
    if memo.status=='อนุมัติ':return dict(code='ready',label='รอจ่ายจริง',tone='amber')
    return dict(code='draft',label='ร่าง',tone='muted')


def claim_requests(db,year):
    """Only explicitly inspected sources; no inferred match by subject or amount."""
    claimed=db.query(DisburseMemo.id).filter(DisburseMemo.procurement_id==Procurement.id).exists()
    lunch=db.query(LunchHireRound.id).filter(LunchHireRound.procurement_id==Procurement.id).exists()
    rows=[dict(title=p.subject or 'เรื่องจัดซื้อ/จัดจ้าง',detail=p.memo_no or p.order_no or 'ไม่ระบุเลขที่',
               href=f'/finance/disburse?proc={p.id}&year={year}')
          for p in db.query(Procurement).filter(Procurement.fiscal_year==year,
              Procurement.status=='ตรวจรับแล้ว',Procurement.paid_before_system.isnot(True),~claimed,~lunch).order_by(Procurement.id.desc())]
    links={l.source_key for l in db.query(LunchDisburseLink)}
    # Historical payments already recorded at the source must not reappear as new claims.
    for ledger in db.query(LunchLedger):
        if ledger.installment_id:links.add(f'i:{ledger.installment_id}')
        if ledger.round_id:links.add(f'r:{ledger.round_id}')
    for rnd in db.query(LunchHireRound).order_by(LunchHireRound.id.desc()):
        if rnd.program.operate_mode!='hire' or rnd.status=='จ่ายแล้ว':continue
        if pays_by_round(rnd):
            if f'r:{rnd.id}' not in links and rnd.end_date and current_fiscal_year(rnd.end_date)==year and round_pay(db,rnd)['ready']:
                rows.append(dict(title=f'อาหารกลางวัน รอบที่ {rnd.seq} · จ่ายทั้งรอบ',detail=f'ปีการศึกษา {rnd.program.year}',href=f'/finance/disburse?lunch_round={rnd.id}'))
        else:
            for i in rnd.installments:
                d=i.inspect_date or i.end_date
                if i.status=='ตรวจรับแล้ว' and f'i:{i.id}' not in links and d and current_fiscal_year(d)==year:
                    rows.append(dict(title=f'อาหารกลางวัน รอบที่ {rnd.seq} งวดที่ {i.seq}',detail=f'ปีการศึกษา {rnd.program.year}',href=f'/finance/disburse?lunch_inst={i.id}'))
    return rows


def overview(db,year,cards):
    memos=db.query(DisburseMemo).filter_by(fiscal_year=year).order_by(DisburseMemo.id.desc()).all()
    on=approval.enabled(db)
    own={m.id:[] for m in memos}
    if own:
        for txn in db.query(FinanceTxn).filter(FinanceTxn.disburse_id.in_(own)):
            own[txn.disburse_id].append(txn)
    statuses={m.id:memo_status(db,m,on,own[m.id]) for m in memos}
    buckets={key:[] for key in ('ready','draft','review')}
    for m in memos:
        key=statuses[m.id]['code']
        if key in buckets:buckets[key].append(dict(title=m.subject or f'บันทึก {m.memo_no or m.id}',
            detail=f'{m.memo_no or "ไม่ระบุเลขที่"} · {statuses[m.id]["label"]}',href=f'/finance/disburse/{m.id}'))
    groups=[]
    # Reuse the existing loan/travel queues and their cross-year scope.
    for n,c in enumerate(cards):
        if c.get('key')=='travel-claim':key='travel'
        elif n<3:key=('overdue','soon','undated')[n]
        else:continue
        groups.append(dict(c,key=key,action='ทำเรื่องเบิก' if key=='travel' else 'ตรวจรายการ'))
    requests=claim_requests(db,year)
    groups.append(dict(key='claim',label='ตรวจรับแล้ว รอทำเรื่องขอเบิก',count=len(requests),icon='clipboard',tone='blue',items=requests,href=f'/finance?year={year}#fd-claim',action='เปิดรายการ'))
    for key,label,icon,tone,action in [('ready','อนุมัติแล้ว รอบันทึกจ่ายจริง','coins','amber','บันทึกจ่าย'),
            ('draft','บันทึกขอเบิกร่าง / รออนุมัติ','file','purple','เปิดรายการ'),
            ('review','บันทึกขอเบิกที่ต้องตรวจข้อมูล','alert','urgent','ตรวจรายการ')]:
        groups.append(dict(key=key,label=label,count=len(buckets[key]),icon=icon,tone=tone,
            items=buckets[key][:5],href=f'/finance/disburse?year={year}',action=action))
    rank={'overdue':0,'claim':1,'ready':2,'travel':3,'review':4,'draft':5,'soon':6,'undated':7}
    groups.sort(key=lambda c:rank[c['key']])
    return dict(groups=groups,active=[c for c in groups if c['count']],ready=len(buckets['ready']),
        count=sum(c['count'] for c in groups),recent=memos[:5],statuses=statuses)
