from fastapi import APIRouter,Request,Depends,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import DisburseMemo,FinanceTxn,WithholdingCertificate as Certificate
from app.services import withholding as wh
from app.services.disburse_payments import lock
from app.routers.pages import get_school,serve_generated
from app.templating import templates
from app.thai_utils import current_fiscal_year,fiscal_year_options,be_date_input

router=APIRouter()
DOCX='application/vnd.openxmlformats-officedocument.wordprocessingml.document'

@router.get('/finance/withholding',response_class=HTMLResponse)
def hub(request:Request,year:int|None=None,q:str='',page:int=1,db:Session=Depends(get_db)):
    year=year or current_fiscal_year()
    if not 2500<=year<=2800:raise HTTPException(400,'ปีงบประมาณไม่ถูกต้อง')
    items=wh.rows(db,year,q[:200]);count=len(items);pages=max(1,(count+29)//30);page=max(1,min(page,pages))
    linked=db.query(Certificate.txn_id).filter(Certificate.txn_id.isnot(None))
    choices=wh.payment_query(db).filter(FinanceTxn.fiscal_year==year,FinanceTxn.id.notin_(linked))
    if q.strip():
        from sqlalchemy import or_
        choices=choices.filter(or_(FinanceTxn.note.contains(q[:200]),FinanceTxn.ref.contains(q[:200]),FinanceTxn.category.contains(q[:200])))
    all_years=[y for y, in db.query(FinanceTxn.fiscal_year).distinct()]+[y for y, in db.query(DisburseMemo.fiscal_year).distinct()]
    return templates.TemplateResponse('finance_withholding.html',dict(request=request,rows=items[(page-1)*30:page*30],
        count=count,page=page,pages=pages,q=q[:200],fiscal_year=year,years=fiscal_year_options(all_years,year,5,1),
        choices=choices.order_by(FinanceTxn.date.desc(),FinanceTxn.id.desc()).limit(200).all(),be_date=be_date_input))

@router.get('/finance/withholding/from-payment')
def pick_payment(txn_id:int,db:Session=Depends(get_db)):
    wh.load(db,'payment',txn_id)
    return RedirectResponse(f'/finance/withholding/payment/{txn_id}',status_code=303)

@router.get('/finance/withholding/{kind}/{rid}',response_class=HTMLResponse)
def review(kind:str,rid:int,request:Request,db:Session=Depends(get_db)):
    data=wh.context(db,kind,rid)
    return templates.TemplateResponse('finance_withholding_edit.html',dict(request=request,**data,error='',be_date=be_date_input))

@router.post('/finance/withholding/{kind}/{rid}')
async def save(kind:str,rid:int,request:Request,db:Session=Depends(get_db)):
    form=await request.form()
    lock(db)
    try:
        wh.save(db,kind,rid,form);db.commit()
    except ValueError as exc:
        db.rollback();data=wh.context(db,kind,rid)
        for key in ('payee','tax_id','address','income_type','ref_no','base_amount','tax_amount'):
            if key in form and not (kind=='memo' and key in ('payee','base_amount','tax_amount')):data['values'][key]=form[key]
        return templates.TemplateResponse('finance_withholding_edit.html',dict(request=request,**data,error=str(exc),be_date=be_date_input),status_code=400)
    if form.get('intent')=='download':return serve_generated(wh.render(db,kind,rid,get_school(db)),DOCX)
    return RedirectResponse(f'/finance/withholding/{kind}/{rid}?saved=1',status_code=303)

@router.post('/finance/withholding/{kind}/{rid}/delete')
def delete(kind:str,rid:int,db:Session=Depends(get_db)):
    lock(db);source,cert=wh.load(db,kind,rid)
    if cert:db.delete(cert);db.commit()
    return RedirectResponse(f'/finance/withholding?year={source.fiscal_year}',status_code=303)
