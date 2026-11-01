"""Eligibility and links between approved travel requests and finance memos."""
from fastapi import HTTPException
from app.models import TravelRequest, DisburseMemo

def eligible(request):
    if request is None or request.status != 'approved':
        return False
    flag=(request.reimburse or '').strip()
    # Older requests predate the explicit expense choice; keep funded ones usable.
    return flag == 'yes' or (not flag and (request.budget or 0) > 0)

def source(db, request_id):
    request=db.get(TravelRequest,request_id)
    if request is None:
        raise HTTPException(404,'ไม่พบคำขอไปราชการในโรงเรียนนี้')
    if not eligible(request):
        raise HTTPException(400,'ใช้ได้เฉพาะคำขอไปราชการที่อนุมัติและขอเบิกค่าใช้จ่ายไว้')
    return request

def existing(db, request_id):
    return db.query(DisburseMemo).filter_by(travel_request_id=request_id).order_by(DisburseMemo.id.desc()).first()


def pending(db):
    """Approved expense requests without a finance memo, across all fiscal years."""
    from sqlalchemy import or_, and_, func
    from sqlalchemy.orm import selectinload
    flag=func.trim(func.coalesce(TravelRequest.reimburse, ''))
    claimed=db.query(DisburseMemo.id).filter(DisburseMemo.travel_request_id==TravelRequest.id).exists()
    return (db.query(TravelRequest).options(selectinload(TravelRequest.person))
            .filter(TravelRequest.status=='approved',
                    or_(flag=='yes',and_(flag=='',TravelRequest.budget>0)), ~claimed))
