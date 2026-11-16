"""Edit standalone ledger entries; linked money is edited at its source."""
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from app import models as m
from app.thai_utils import parse_be_date


FIELDS = ('date', 'kind', 'amount', 'category', 'ref', 'note', 'remark', 'place',
          'item_id', 'eb_code', 'due_date', 'refund_date')


def source(db, t):
    if t.disburse_id:
        return f'/finance/disburse/{t.disburse_id}', 'แก้ที่บันทึกขอเบิกจ่าย'
    if t.loan_id:
        return f'/finance/loans/{t.loan_id}/money', 'แก้ที่รายการเงินยืม'
    if t.loan_return_id:
        returned = db.get(m.LoanReturn,t.loan_return_id)
        return (f'/finance/loans/{returned.loan_id}/money' if returned else '/finance/loans'), 'แก้ที่ส่งใช้เงินยืม'
    row = db.query(m.LunchLedger).filter_by(finance_txn_id=t.id).first()
    if row:
        return f'/lunch/{row.program_id}#ledger', 'แก้ที่อาหารกลางวัน'
    row = db.query(m.RevenueRemit).filter_by(txn_id=t.id).first()
    if row:
        return '/finance/revenue', 'แก้ที่นำส่งรายได้'
    if db.query(m.CheckPayment).filter_by(txn_id=t.id).first():
        return f'/finance/checks?year={t.fiscal_year}', 'ตรวจรายการเช็ค/โอนก่อนแก้ไข'
    if db.query(m.WithholdingCertificate).filter_by(txn_id=t.id).first():
        return f'/finance/withholding/payment/{t.id}?source_locked=1', 'ตรวจหนังสือรับรองภาษีก่อนแก้ไข'
    if db.query(m.SubsidyReceiptLink).filter_by(txn_id=t.id).first():
        return '/finance/subsidy', 'แก้ที่รับเงินอุดหนุน'
    if t.no_count:
        return '', 'รายการโอนภายในต้องจัดการคู่รับ–จ่ายพร้อมกัน จึงยังแก้แยกรายการไม่ได้'
    return None


def token(db, t):
    values = {c.name: str(getattr(t, c.name)) for c in t.__table__.columns}
    values['receipts'] = [[str(getattr(r,c.name)) for c in r.__table__.columns]
                          for r in db.query(m.Receipt).filter_by(txn_id=t.id).order_by(m.Receipt.id)]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def save(db, t, form):
    if source(db,t):
        raise ValueError('รายการนี้เชื่อมกับงานต้นทาง กรุณาแก้จากงานต้นทาง')
    if form.get('version') != token(db,t):
        raise ValueError('รายการนี้มีการเปลี่ยนแปลงแล้ว กรุณาเปิดรายการใหม่ก่อนแก้ไข')
    date = parse_be_date(str(form.get('date','')))
    if not date or date.year+543+(date.month>=10) != t.fiscal_year:
        raise ValueError(f'กรุณาระบุวันที่ให้ถูกต้องและอยู่ในปีงบ {t.fiscal_year}')
    try:
        amount = Decimal(str(form.get('amount','')).replace(',',''))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
        value = float(amount)
        if not math.isfinite(value): raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('จำนวนเงินต้องมากกว่า 0 และมีทศนิยมไม่เกิน 2 ตำแหน่ง')
    kind = str(form.get('kind',''))
    if kind not in ('in','out'): raise ValueError('กรุณาเลือก รับ หรือ จ่าย')
    iid = str(form.get('item_id','')).strip()
    item = db.get(m.AccountItem, int(iid)) if iid.isdigit() else None
    if iid and (not item or item.account_id != t.account_id or item.fiscal_year != t.fiscal_year):
        raise ValueError('หมวดเงินไม่อยู่ในบัญชีและปีงบนี้')
    place = str(form.get('place',''))
    if place not in ('','cash','bank','agency'): raise ValueError('ที่เก็บเงินไม่ถูกต้อง')
    from app.services.ebudget_cat import EXPENSE, INCOME
    eb = str(form.get('eb_code','')).strip()
    codes = {code for _, group in (EXPENSE if kind=='out' else INCOME) for code, _ in group}
    if eb and eb not in codes:
        raise ValueError('หมวด e-Budget ไม่ตรงกับประเภทรายการ')
    note = str(form.get('note','')).strip()
    if not note: raise ValueError('กรุณาระบุรายละเอียดรายการ')
    dates = {}
    for key in ('due_date','refund_date'):
        raw = str(form.get(key,'')).strip()
        dates[key] = parse_be_date(raw) if raw else None
        if raw and not dates[key]: raise ValueError('วันที่ครบกำหนดหรือวันที่คืนเงินไม่ถูกต้อง')
    changes = dict(date=date,kind=kind,amount=value,item_id=item.id if item else None,place=place,eb_code=eb)
    for key in ('note','category','ref','remark'):
        changes[key]=str(form.get(key,'')).strip()[:300]
    changes.update(dates)
    original=[getattr(m.FinanceTxn,c.name)==getattr(t,c.name) for c in t.__table__.columns]
    if db.query(m.FinanceTxn).filter(*original).update(changes,synchronize_session=False) != 1:
        raise ValueError('รายการนี้มีการเปลี่ยนแปลงแล้ว กรุณาเปิดรายการใหม่ก่อนแก้ไข')
    db.refresh(t)
    for receipt in db.query(m.Receipt).filter_by(txn_id=t.id):
        receipt.date,receipt.amount,receipt.kind,receipt.note = date,value,'จ่าย' if kind=='out' else 'รับ',t.note
    db.flush()
