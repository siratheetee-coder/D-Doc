"""Certificate metadata. All payments remain owned by the original finance workflow."""
from decimal import Decimal,InvalidOperation
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from app.models import WithholdingCertificate as Certificate, DisburseMemo, FinanceTxn, Procurement, Vendor

def payment_query(db):
    from app.models import RevenueRemit
    remit=db.query(RevenueRemit.id).filter(RevenueRemit.txn_id==FinanceTxn.id).exists()
    return db.query(FinanceTxn).options(selectinload(FinanceTxn.account)).filter(
        FinanceTxn.kind=='out',FinanceTxn.no_count.isnot(True),FinanceTxn.loan_id.is_(None),FinanceTxn.disburse_id.is_(None),~remit)

def load(db,kind,rid):
    cert=db.query(Certificate).filter_by(**{('memo_id' if kind=='memo' else 'txn_id'):rid}).first() if kind in ('memo','payment') else None
    if kind=='memo':
        source=db.get(DisburseMemo,rid)
        if source is not None and (source.wht or 0)<=0 and cert is None:
            raise HTTPException(400,'กรอกและบันทึกยอดภาษีหัก ณ ที่จ่ายในบันทึกขอเบิกก่อน')
    elif kind=='payment':
        source=db.get(FinanceTxn,rid) if cert else payment_query(db).filter(FinanceTxn.id==rid).first()
    else:source=None
    if source is None:raise HTTPException(404,'ไม่พบรายการต้นทางที่ออกหนังสือรับรองได้ในโรงเรียนนี้')
    return source,cert

def vendor(db,memo):
    proc=db.get(Procurement,memo.procurement_id) if memo.procurement_id else None
    if proc and proc.vendor:return proc.vendor,proc
    return (db.query(Vendor).filter(Vendor.name==(memo.payee or '').strip()).first(),proc)

def context(db,kind,rid):
    source,cert=load(db,kind,rid)
    v,proc=vendor(db,source) if kind=='memo' else (None,None)
    initial={
        'payee':source.payee if kind=='memo' else '',
        'tax_id':v.tax_id if v else '', 'address':v.address if v else '',
        'income_type':('ค่าสินค้า' if source.proc_kind=='จัดซื้อ' else 'ค่าจ้างทำของ' if source.proc_kind=='จัดจ้าง' else '') if kind=='memo' else '',
        'ref_no':((proc.order_no or '') if proc else '') or ((source.memo_no or '') if kind=='memo' else (source.ref or f'จ่าย-{source.id}')),
        'base_amount':float(source.amount or 0)-float(source.vat or 0) if kind=='memo' else float(source.amount or 0),
        'tax_amount':float(source.wht or 0) if kind=='memo' else 0,
    }
    if cert:
        for key in ('payee','tax_id','address','income_type','ref_no','base_amount','tax_amount'):initial[key]=getattr(cert,key)
    if kind=='memo':
        initial.update(payee=source.payee or '',base_amount=float(source.amount or 0)-float(source.vat or 0),tax_amount=float(source.wht or 0))
    return dict(kind=kind,rid=rid,source=source,certificate=cert,values=initial,
                posted=kind=='payment' or bool(db.query(FinanceTxn.id).filter_by(disburse_id=rid).first()),
                source_href=f'/finance/disburse/{rid}' if kind=='memo' else f'/finance/accounts/{source.account_id}?year={source.fiscal_year}#txn-history')

def money(value,label):
    try:
        n=Decimal(str(value))
        if not n.is_finite() or n<=0 or n>Decimal('1000000000000'):raise ValueError()
        result=n.quantize(Decimal('.01'))
        if result<=0:raise ValueError()
        return float(result)
    except (ValueError,InvalidOperation):raise ValueError(label+'ต้องมากกว่า 0 และเป็นจำนวนเงินที่ถูกต้อง')

def save(db,kind,rid,form):
    from app.services import staff
    source,cert=load(db,kind,rid)
    if kind=='payment' and not payment_query(db).filter(FinanceTxn.id==rid).first():raise ValueError('รายการต้นทางเปลี่ยนไปแล้ว กรุณาตรวจว่าเป็นรายการจ่ายปกติที่ยังไม่ผูกบันทึกขอเบิก')
    base=money((float(source.amount or 0)-float(source.vat or 0)) if kind=='memo' else form.get('base_amount'),'จำนวนเงินได้')
    tax=money(source.wht if kind=='memo' else form.get('tax_amount'),'ภาษีหัก ณ ที่จ่าย')
    if tax>base:raise ValueError('ยอดภาษีต้องไม่เกินจำนวนเงินได้')
    tax_id=''.join((form.get('tax_id') or '').split()).replace('-','')
    if tax_id and (not tax_id.isdigit() or len(tax_id)!=13):raise ValueError('เลขประจำตัวผู้เสียภาษีต้องเป็นตัวเลข 13 หลัก หรือเว้นว่างไว้กรอกภายหลัง')
    payee=(source.payee if kind=='memo' else form.get('payee') or '').strip()
    income_type=(form.get('income_type') or '').strip()
    if not payee or not income_type:raise ValueError('ระบุชื่อผู้ถูกหักภาษีและประเภทเงินได้ก่อนออกเอกสาร')
    if cert is None:
        cert=Certificate(**{('memo_id' if kind=='memo' else 'txn_id'):rid});db.add(cert)
    cert.payee=payee[:200];cert.tax_id=tax_id;cert.address=(form.get('address') or '').strip()[:1000]
    cert.income_type=income_type[:200];cert.ref_no=(form.get('ref_no') or '').strip()[:150]
    cert.base_amount=base;cert.tax_amount=tax
    staff.apply(db,cert,form.get('staff_selection'))
    db.flush()
    return cert

def render(db,kind,rid,school):
    from app.services.finance_forms_doc import render_wht_certificate
    source,cert=load(db,kind,rid)
    if cert is None:raise HTTPException(400,'ตรวจและบันทึกข้อมูลหนังสือรับรองก่อนดาวน์โหลด')
    if kind=='memo' and (source.wht or 0)<=0:raise HTTPException(400,'บันทึกขอเบิกไม่มียอดภาษีแล้ว กรุณาตรวจรายการต้นทาง')
    if kind=='payment' and not payment_query(db).filter(FinanceTxn.id==rid).first():raise HTTPException(400,'รายการจ่ายต้นทางเปลี่ยนไปแล้ว กรุณาตรวจใหม่ก่อนออกหนังสือรับรอง')
    if kind=='memo':
        memo=source
    else:
        memo=SimpleNamespace(id=cert.id,payee=cert.payee,amount=cert.base_amount,vat=0,wht=cert.tax_amount,fine=0,
            date=source.date,memo_no=cert.ref_no or f'จ่าย-{source.id}',staff_snapshot=cert.staff_snapshot)
    return render_wht_certificate(school,memo,payee_tax_id=cert.tax_id,payee_address=cert.address,pay_type=cert.income_type,ref_no=cert.ref_no or memo.memo_no)

def rows(db,year,q=''):
    out=[]
    posted={mid for mid, in db.query(FinanceTxn.disburse_id).filter(FinanceTxn.fiscal_year==year,FinanceTxn.disburse_id.isnot(None)).distinct()}
    for m in db.query(DisburseMemo).filter(DisburseMemo.fiscal_year==year,DisburseMemo.wht>0):
        out.append(dict(kind='memo',id=m.id,date=m.date,payee=m.payee or '-',ref=m.memo_no or '-',subject=m.subject or '',
            base=float(m.amount or 0)-float(m.vat or 0),tax=m.wht,posted=m.id in posted,label='บันทึกขอเบิก',source_href=f'/finance/disburse/{m.id}'))
    payments={t.id:t for t in db.query(FinanceTxn).filter(FinanceTxn.fiscal_year==year)}
    for c in db.query(Certificate).filter(Certificate.txn_id.in_(list(payments))):
        t=payments[c.txn_id]
        out.append(dict(kind='payment',id=t.id,date=t.date,payee=c.payee,ref=c.ref_no or t.ref or '-',subject=t.note or t.category or '',base=c.base_amount,tax=c.tax_amount,posted=True,label='รายการจ่ายเดิม',source_href=f'/finance/accounts/{t.account_id}?year={year}#txn-history'))
    q=q.strip().casefold()
    return sorted([r for r in out if not q or q in f"{r['payee']} {r['ref']} {r['subject']}".casefold()],key=lambda r:(r['date'].isoformat() if r['date'] else '',r['id']),reverse=True)
