from uuid import uuid4
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import School, Project, PlanBudget, PlanFunding, ProjectFunding, SubsidySnapshot, AccountItem
from app.templating import templates
from app.services import plan_funding as pf
from app.services import subsidy as sub

router=APIRouter()


def required(db, year):
    p=pf.plan(db,year)
    if not p: raise ValueError('กำหนดช่วงแผนก่อนนำงบมาใช้')
    return p


def error_page(request,message,back):
    return templates.TemplateResponse('plan_budget_error.html',dict(request=request,message=message,back=back),status_code=409)


def page_context(db, year, requested_mode=None):
    p=pf.plan(db,year)
    school=db.query(School).first()
    mode=p.mode if p else (getattr(school,'project_year_mode','budget') or 'budget')
    if not p and requested_mode in ('budget','academic'): mode=requested_mode
    start,end=(p.start_date,p.end_date) if p else pf.defaults(year,mode)
    latest={}
    for s in db.query(SubsidySnapshot).order_by(SubsidySnapshot.id.desc()):
        if (s.academic_year==year if mode=='academic' else s.fiscal_year==year):
            latest.setdefault((s.academic_year,s.term),s)
    return dict(plan=p,year=year,mode=mode,start=start,end=end, funding=pf.summary(db,p),snapshots=list(latest.values()),nonce=str(uuid4()))


@router.get('/plan-budget/{year}')
def page(year:int,request:Request,mode:str='',db:Session=Depends(get_db)):
    try: ctx=page_context(db,year,mode)
    except ValueError as e: raise HTTPException(400,str(e))
    return templates.TemplateResponse('plan_budget.html',dict(request=request,**ctx))


@router.post('/plan-budget/{year}/period')
async def period(year:int,request:Request,db:Session=Depends(get_db)):
    f=await request.form()
    try:
        pf.save_period(db,year,f.get('mode'),f.get('start'),f.get('end'));db.commit()
    except ValueError as e:
        db.rollback();return error_page(request,str(e),f'/plan-budget/{year}')
    return RedirectResponse(f'/plan-budget/{year}?saved=1',303)


@router.get('/plan-budget/{year}/review')
def review(year:int,request:Request,kind:str='subsidy',snapshot_id:int=0,db:Session=Depends(get_db)):
    try:
        p=required(db,year);data=pf.preview(db,p,kind,snapshot_id)
    except ValueError as e: return error_page(request,str(e),f'/plan-budget/{year}')
    return templates.TemplateResponse('plan_budget_review.html',dict(request=request,year=year,data=data,token=sub.fingerprint(data)))


@router.post('/plan-budget/{year}/apply')
async def apply(year:int,request:Request,db:Session=Depends(get_db)):
    f=await request.form()
    try:
        pf.apply(db,required(db,year),f.get('kind'),int(f.get('snapshot_id',0)),f.get('token'),f.getlist('selected'));db.commit()
    except ValueError as e:
        db.rollback();return error_page(request,str(e),f'/plan-budget/{year}')
    return RedirectResponse(f'/plan-budget/{year}?saved=1',303)


@router.post('/plan-budget/{year}/other')
async def other(year:int,request:Request,db:Session=Depends(get_db)):
    f=await request.form()
    try:
        sub.lock(db);p=required(db,year)
        name=str(f.get('name','')).strip()
        if not name or len(name)>200: raise ValueError('ระบุชื่อเงินอื่น ๆ ไม่เกิน 200 ตัวอักษร')
        # Form nonce makes retries idempotent; scope to this plan.
        nonce=str(f.get('nonce',''))
        from uuid import UUID
        UUID(nonce)
        key=f'other:{p.id}:{nonce}'
        if not db.query(PlanFunding).filter_by(source_key=key).first():
            db.add(PlanFunding(plan_id=p.id,source_key=key,kind='other',name=name,amount=pf.amount(f.get('amount')),payload='{}'))
        db.commit()
    except ValueError as e:
        db.rollback();return error_page(request,str(e),f'/plan-budget/{year}')
    return RedirectResponse(f'/plan-budget/{year}?saved=1',303)


@router.post('/plan-budget/{year}/remove/{fid}')
def remove(year:int,fid:int,request:Request,db:Session=Depends(get_db)):
    try:
        sub.lock(db);p=required(db,year);s=db.get(PlanFunding,fid)
        if not s or s.plan_id!=p.id: raise ValueError('ไม่พบรายการเงินในแผนนี้')
        if pf.allocated(db,fid): raise ValueError('ต้องยกเลิกการจัดสรรให้โครงการก่อนนำเงินออกจากแผน')
        db.delete(s);db.commit()
    except ValueError as e:
        db.rollback();return error_page(request,str(e),f'/plan-budget/{year}')
    return RedirectResponse(f'/plan-budget/{year}',303)


@router.post('/plan-budget/project/{pid}/allocate')
async def allocate(pid:int,request:Request,db:Session=Depends(get_db)):
    f=await request.form()
    try:
        project=db.get(Project,pid)
        if not project: raise ValueError('ไม่พบโครงการ')
        p=required(db,project.plan_year)
        pf.allocate(db,p,project,{k[5:]:v for k,v in f.items() if k.startswith('fund_')},f.get('token'));db.commit()
    except ValueError as e:
        db.rollback();return error_page(request,str(e),f'/projects/{pid}')
    return RedirectResponse(f'/projects/{pid}?saved=1#project-funding',303)


def project_context(db,project):
    p=pf.plan(db,project.plan_year) if project.plan_year else None
    allocations={a.funding_id:a.amount for a in db.query(ProjectFunding).filter_by(project_id=project.id)}
    return dict(funding_plan=p, funding_rows=[dict(source=s,item=db.get(AccountItem,s.account_item_id) if s.account_item_id else None,value=allocations.get(s.id,0),available=round(s.amount-pf.allocated(db,s.id,project.id),2)) for s in pf.sources(db,p)],
                funding_token=pf.allocation_token(db,p,project), funding_assigned=sum(allocations.values()),
                actual_paid=pf.actual_paid(db,project))
