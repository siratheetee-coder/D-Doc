"""Budget reservation for procurement claims, including drafts; never infer payment links."""
import math,hashlib,json
from app.models import DisburseMemo,FinanceTxn


def state(db,proc,exclude=None):
    rows=db.query(DisburseMemo).filter_by(procurement_id=proc.id)
    if exclude is not None:rows=rows.filter(DisburseMemo.id!=exclude)
    rows=rows.order_by(DisburseMemo.id).all()
    values=[float(m.amount or 0) for m in rows]
    valid=all(math.isfinite(v) and v>=0 for v in values)
    claimed=round(sum(values),2) if valid else 0
    total=round(float(proc.total_amount or 0),2)
    payments=list(db.query(FinanceTxn.disburse_id,FinanceTxn.amount).filter(FinanceTxn.disburse_id.in_([m.id for m in rows]),
                     FinanceTxn.kind=='out',FinanceTxn.amount>0,FinanceTxn.no_count.isnot(True))) if rows else []
    paid={}
    for mid,amount in payments:
        if math.isfinite(amount):paid[mid]=paid.get(mid,0)+amount
    actual=round(sum(paid.values()),2)
    pending=[m for m in rows if round(paid.get(m.id,0)-float(m.amount or 0),2)<0]
    preferred=pending if actual<total and pending else [m for m in rows if m.id in paid]
    resume=preferred[0] if preferred else (rows[0] if rows else None)
    version=hashlib.sha256(json.dumps([proc.id,str(total),[(m.id,str(m.amount)) for m in rows]]).encode()).hexdigest()
    return {'version':version,'rows':rows,'total':total,'claimed':claimed,'remaining':round(total-claimed,2),
            'valid':valid and math.isfinite(total),'resume':resume}


def validate(db,proc,amount,exclude=None):
    data=state(db,proc,exclude)
    if not data['valid'] or not math.isfinite(amount or 0) or (amount or 0)<0:
        raise ValueError('ยอดขอเบิกหรือวงเงินเรื่องพัสดุไม่ถูกต้อง กรุณาตรวจข้อมูลก่อน')
    if round(float(amount or 0)-data['remaining'],2)>0:
        raise ValueError(f"วงเงินเรื่อง {data['total']:,.2f} บาท มีบันทึกขอเบิกแล้ว {data['claimed']:,.2f} บาท เพิ่มได้อีก {max(data['remaining'],0):,.2f} บาท กรุณาเปิดบันทึกเดิมหรือระบุเฉพาะยอดส่วนที่เหลือ")
    return data
