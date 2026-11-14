"""Explicit lunch installment -> finance memo provenance; one payment, two views."""
import hashlib
import math
from datetime import datetime
from fastapi import HTTPException
from app.models import (LunchDisburseLink, LunchHireRound, LunchInstallment, LunchLedger,
                        DisburseMemo, FinanceTxn, FinanceAccount, Receipt, CheckPayment,
                        WithholdingCertificate)
from app.services import lunch_meals as meals, lunch_approval as la


def source(db, iid=None, rid=None, require_ready=True):
    if bool(iid)==bool(rid):raise HTTPException(400,'เลือกงวดหรือรอบอาหารกลางวันอย่างใดอย่างหนึ่ง')
    inst=db.get(LunchInstallment,iid) if iid else None
    rnd=inst.round if inst else db.get(LunchHireRound,rid) if rid else None
    if not rnd:raise HTTPException(404,'ไม่พบงวดหรือรอบอาหารกลางวันในโรงเรียนนี้')
    if rnd.program.operate_mode!='hire':raise HTTPException(400,'การเชื่อมนี้ใช้กับงวดจ้างเหมาอาหารกลางวัน')
    if bool(inst)==meals.pays_by_round(rnd):raise HTTPException(400,'รูปแบบการจ่ายเปลี่ยนแล้ว กรุณากลับไปเลือกจากหน้าอาหารกลางวัน')
    pay=meals.summary(db,inst) if inst else meals.round_pay(db,rnd)
    ready=inst.status in meals.DONE_INSPECT if inst else pay['ready']
    if require_ready and not ready:raise HTTPException(400,'กรุณาบันทึกผลตรวจรับก่อนทำเรื่องขอเบิก')
    key=f'i:{inst.id}' if inst else f'r:{rnd.id}'
    fingerprint=la.fp_round(rnd)+'|'+(la.fp_inst(inst) if inst else la.fp_pay(rnd))
    return dict(key=key,inst=inst,rnd=rnd,program=rnd.program,ready=ready,
        title=f'ค่าจ้างเหมาอาหารกลางวัน รอบที่ {rnd.seq}'+(f' งวดที่ {inst.seq}' if inst else ' (จ่ายทั้งรอบ)'),
        amount=round(pay['amount'],2),wht=pay['wht'],fine=pay['penalty'],
        date=inst.inspect_date or inst.end_date if inst else rnd.end_date,
        paid=inst.status=='จ่ายแล้ว' if inst else rnd.status=='จ่ายแล้ว',
        fingerprint=hashlib.sha256(fingerprint.encode()).hexdigest(),
        back=f'/lunch/round/{rnd.id}/plan#'+(f'inst-{inst.id}' if inst else 'installments'))


def link_of(db,memo):return db.query(LunchDisburseLink).filter_by(memo_id=memo.id).first()


def existing(db,src):
    link=db.query(LunchDisburseLink).filter_by(source_key=src['key']).first()
    if link:return db.get(DisburseMemo,link.memo_id)
    # Exact historical ledger provenance is safe to reuse; similar names/amounts are not.
    ids={t.disburse_id for l in ledgers(db,src) if l.finance_txn_id
         for t in [db.get(FinanceTxn,l.finance_txn_id)] if t and t.disburse_id}
    return db.get(DisburseMemo,next(iter(ids))) if len(ids)==1 else None


def for_memo(db,memo):
    link=link_of(db,memo)
    if not link:return None
    src=source(db,link.installment_id,None if link.installment_id else link.round_id,False)
    src.update(link=link,stale=src['fingerprint']!=link.fingerprint)
    return src


def ledgers(db,src):
    q=db.query(LunchLedger)
    return q.filter_by(installment_id=src['inst'].id).all() if src['inst'] else q.filter_by(round_id=src['rnd'].id).all()


def attach(db,memo,src):
    db.add(LunchDisburseLink(source_key=src['key'],round_id=src['rnd'].id,
        installment_id=src['inst'].id if src['inst'] else None,memo_id=memo.id,fingerprint=src['fingerprint']))
    db.flush()


def validate(db,memo,src,posting=False):
    if len(memo.splits or [])>=2:raise ValueError('งวดอาหารกลางวันใช้บัญชีเดียว กรุณาเลือกบัญชีอาหารกลางวัน')
    if round(memo.amount or 0,2)!=src['amount'] or round(memo.wht or 0,2)!=round(src['wht'],2) or round(memo.fine or 0,2)!=round(src['fine'],2):
        raise ValueError('ยอดขอเบิก ภาษี หรือค่าปรับไม่ตรงกับงวด กรุณาปรับข้อมูลจากงวดล่าสุด')
    if not all(math.isfinite(v or 0) for v in (memo.amount,memo.wht,memo.fine)) or memo.amount<=0:
        raise ValueError('ยอดขอเบิกไม่ถูกต้อง')
    if not db.get(FinanceAccount,memo.account_id):raise ValueError('กรุณาเลือกบัญชีที่จ่ายเงิน')
    if src['program'].finance_account_id and memo.account_id!=src['program'].finance_account_id:
        raise ValueError('กรุณาใช้บัญชีเงินอาหารกลางวันที่ตั้งไว้ในโครงการ')
    if posting:
        if src['stale']:raise ValueError('ข้อมูลงวดเปลี่ยนแล้ว กรุณาปรับข้อมูลจากงวดล่าสุดก่อนจ่าย')
        if not src['ready']:raise ValueError('ยังตรวจรับไม่ครบ กรุณากลับไปตรวจรับก่อน')
        if src['paid'] or ledgers(db,src):raise ValueError('งวดนี้มีการจ่ายแล้ว กรุณาเชื่อมรายการจ่ายเดิม ไม่ลงจ่ายซ้ำ')
        from app.services import approval
        if approval.enabled(db) and not approval.approved_for(db,'disburse',memo.id,memo):
            raise ValueError('กรุณาส่งบันทึกขอเบิกให้ ผอ. อนุมัติก่อนบันทึกจ่ายจริง')


def payment_summary(db,memo):
    src=for_memo(db,memo)
    if not src:return None
    own=db.query(FinanceTxn).filter_by(disburse_id=memo.id).all()
    old=ledgers(db,src);ids={x.finance_txn_id for x in old if x.finance_txn_id}
    txns=db.query(FinanceTxn).filter(FinanceTxn.id.in_(ids)).all() if ids else []
    rows=sorted({t.id:t for t in own+txns}.values(),key=lambda t:t.id)
    paid=round(sum(t.amount or 0 for t in rows),2)
    return dict(rows=rows,own=own,total=src['amount'],paid=paid,remaining=round(src['amount']-paid,2),
        lunch_ids=ids,managed=False,proc=None,lunch_source=src)


def compatible_source(db,memo,txn):
    src=for_memo(db,memo)
    if not src:return None
    if txn and txn.project_id and txn.project_id!=memo.project_id:return False
    rows=ledgers(db,src)
    ledger=db.query(LunchLedger).filter_by(finance_txn_id=txn.id).first() if txn else None
    if ledger and ledger.id not in {l.id for l in rows}:return False
    if rows and (not txn or txn.id not in {l.finance_txn_id for l in rows}):return False
    # A previously paid source with no linked ledger must be reviewed, never guessed.
    if src['paid'] and not rows:return False
    return True


def sync_paid(db,memo):
    db.flush()
    src=for_memo(db,memo)
    if not src:return
    txns=db.query(FinanceTxn).filter_by(disburse_id=memo.id).all()
    if len(txns)!=1:raise ValueError('ไม่พบรายการจ่ายเดียวที่เชื่อมกับงวดนี้')
    txn=txns[0];old=ledgers(db,src)
    if len(old)>1 or (old and old[0].finance_txn_id!=txn.id):raise ValueError('งวดนี้มีรายการจ่ายอื่นอยู่แล้ว กรุณาตรวจการเชื่อม')
    if not old:
        ledger=LunchLedger(program_id=src['program'].id,installment_id=src['inst'].id if src['inst'] else None,
            round_id=None if src['inst'] else src['rnd'].id,kind='out',amount=txn.amount,
            date=txn.date,ref=txn.ref,detail=src['title'],finance_txn_id=txn.id,procurement_id=src['rnd'].procurement_id)
        db.add(ledger)
    if src['inst']:src['inst'].status='จ่ายแล้ว'
    else:src['rnd'].status='จ่ายแล้ว'
    src['link'].payment_date=txn.date
    memo.status='จ่ายแล้ว';db.flush()


def cancel_payment(db,memo):
    src=for_memo(db,memo)
    if not src:raise ValueError('บันทึกนี้ไม่ได้เชื่อมอาหารกลางวัน')
    txns=db.query(FinanceTxn).filter_by(disburse_id=memo.id).all()
    if len(txns)!=1 or txns[0].linked_existing:raise ValueError('รายการจ่ายเดิมให้ใช้ยกเลิกการเชื่อม โดยเก็บรายการเงินจริงไว้')
    txn=txns[0]
    if (db.query(Receipt).filter_by(txn_id=txn.id).first() or db.query(CheckPayment).filter_by(txn_id=txn.id).first()
        or db.query(WithholdingCertificate).filter((WithholdingCertificate.txn_id==txn.id)|(WithholdingCertificate.memo_id==memo.id)).first()):
        raise ValueError('รายการนี้เชื่อมใบสำคัญ เช็ค/โอน หรือหนังสือรับรองภาษี กรุณาตรวจและยกเลิกการเชื่อมก่อน')
    for ledger in ledgers(db,src):
        if ledger.finance_txn_id!=txn.id:raise ValueError('พบรายการจ่ายอื่นของงวด กรุณาตรวจข้อมูลก่อน')
        db.delete(ledger)
    db.delete(txn)
    if src['inst']:src['inst'].status='ตรวจรับแล้ว'
    else:src['rnd'].status='จ้างแล้ว'
    src['link'].payment_date=None;memo.status='อนุมัติ';db.flush()


def guard_source(db,rnd,inst=None):
    links=db.query(LunchDisburseLink).filter_by(round_id=rnd.id)
    if inst:links=links.filter_by(installment_id=inst.id)
    if links.first():raise ValueError('เรื่องนี้เชื่อมบันทึกขอเบิกในการเงินแล้ว กรุณาจัดการบันทึกที่งานการเงินก่อนเปลี่ยนสถานะจ่ายหรือลบงวด')


def view_map(db,rnd):
    links=db.query(LunchDisburseLink).filter_by(round_id=rnd.id).all()
    return {x.source_key:dict(id=x.memo_id,url=f'/finance/disburse/{x.memo_id}') for x in links}
