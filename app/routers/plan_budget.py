"""ช่วงเวลาของแผน (ปีงบประมาณ หรือปีการศึกษา + วันเริ่ม/วันสิ้นสุด)

เดิมหน้านี้ใช้ "นำเงินเข้าแผน" แล้วจัดสรรให้โครงการด้วย เลิกใช้แล้วเพราะตัวเลขจัดสรรไม่ตรงกับเงินจริง ครูงง
ตอนนี้ดูงบโครงการกับเงินในทะเบียนคุมเงินแยกกัน (แบบที่ครูการเงินทำจริง) ข้อมูลจัดสรรเดิมยังเก็บไว้ในฐาน
ส่วนช่วงเวลาของแผนยังต้องใช้: ป้าย "ปีการศึกษา/ปีงบประมาณ" และการตรวจเรื่องที่ลงวันที่นอกปีของแผน
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import School
from app.templating import templates
from app.services import plan_funding as pf

router=APIRouter()


def error_page(request,message,back):
    return templates.TemplateResponse('plan_budget_error.html',dict(request=request,message=message,back=back),status_code=409)


def page_context(db, year, requested_mode=None):
    p=pf.plan(db,year)
    school=db.query(School).first()
    mode=p.mode if p else (getattr(school,'project_year_mode','budget') or 'budget')
    if not p and requested_mode in ('budget','academic'): mode=requested_mode
    start,end=(p.start_date,p.end_date) if p else pf.defaults(year,mode)
    return dict(plan=p,year=year,mode=mode,start=start,end=end)


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
