"""Correct an existing payment's date without reposting or changing its memo date."""
from app import models as m
from app.services.finance_txn_edit import token
from app.thai_utils import parse_be_date


def restriction(db, memo, txn):
    if txn.disburse_id != memo.id or txn.kind!='out' or txn.no_count:
        return 'รายการนี้ไม่ได้เป็นรายการจ่ายของบันทึกนี้'
    if db.query(m.LunchLedger).filter_by(finance_txn_id=txn.id).first():
        return 'รายการนี้มาจากอาหารกลางวัน กรุณาแก้วันที่ที่อาหารกลางวัน'
    if txn.loan_id or txn.loan_return_id:
        return 'รายการนี้เชื่อมกับเงินยืม กรุณาแก้ที่เงินยืม'
    if db.query(m.CheckPayment).filter_by(txn_id=txn.id).first():
        return 'รายการนี้เชื่อมทะเบียนเช็ค/โอน กรุณาตรวจและยกเลิกการเชื่อมก่อนแก้วันที่จ่าย'
    if (db.query(m.WithholdingCertificate).filter_by(txn_id=txn.id).first()
            or db.query(m.WithholdingCertificate).filter_by(memo_id=memo.id).first()):
        return 'รายการนี้มีหนังสือรับรองภาษี กรุณาตรวจและยกเลิกหนังสือรับรองก่อนแก้วันที่จ่าย'
    return ''


def context(db,memo,txns):
    result={}
    for txn in txns:
        if txn.disburse_id!=memo.id:continue
        why=restriction(db,memo,txn)
        result[txn.id]={'restriction':why,'version':token(db,txn) if not why else '',
            'recon':db.query(m.BankRecon).filter_by(account_id=txn.account_id,fiscal_year=txn.fiscal_year).first() is not None}
    return result


def save(db,memo,txn,paid_date,version):
    why=restriction(db,memo,txn)
    if why:raise ValueError(why)
    if not version or version!=token(db,txn):
        raise ValueError('รายการจ่ายเปลี่ยนแปลงแล้ว กรุณาตรวจวันที่ล่าสุดและลองใหม่')
    date=parse_be_date(paid_date)
    if not date:raise ValueError('กรุณากรอกวันที่จ่ายเงินจริงให้ถูกต้อง เช่น 05/10/2569')
    fy=date.year+543+(date.month>=10)
    if fy!=txn.fiscal_year:
        raise ValueError(f'วันที่จ่ายต้องอยู่ในปีงบ {txn.fiscal_year} การย้ายข้ามปีต้องตรวจยอดยกมาแยกต่างหาก')
    old=txn.date
    changed=db.query(m.FinanceTxn).filter(m.FinanceTxn.id==txn.id,m.FinanceTxn.disburse_id==memo.id,
                                         m.FinanceTxn.date==old).update({'date':date},synchronize_session=False)
    if changed!=1:raise ValueError('รายการจ่ายเปลี่ยนแปลงแล้ว กรุณาเปิดรายการใหม่')
    for receipt in db.query(m.Receipt).filter_by(txn_id=txn.id):receipt.date=date
    db.refresh(txn)
    db.flush()
