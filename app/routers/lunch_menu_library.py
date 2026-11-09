from datetime import datetime
from urllib.parse import urlencode
from fastapi import APIRouter,Depends,Request,HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import LunchProgram,LunchMenuSet,LunchMenu
from app.templating import templates
from app.services import lunch_menu_sets as service
from app.thai_utils import be_date_input,parse_be_date
router=APIRouter()

def context(request,db,pid,**extra):
    p=db.get(LunchProgram,pid)
    if not p:raise HTTPException(404,'ไม่พบโครงการอาหารกลางวัน')
    sets=db.query(LunchMenuSet).order_by(LunchMenuSet.id.desc()).all()
    out=dict(request=request,p=p,sets=sets,selected=sets[0] if sets else None,editing=False,creating=False,form_name='',form_days=10,form_rows=[],sequence=[],start='',end='',mode='skip',plan=None,error='',message=request.query_params.get('msg',''),be_date=be_date_input)
    rounds=[r for r in p.rounds if r.start_date]
    if rounds:
        current=max(rounds,key=lambda r:r.start_date);out['start']=be_date_input(current.start_date);out['end']=be_date_input(current.end_date) if current.end_date else ''
    out.update(extra);return out

def page(ctx,status=200):return templates.TemplateResponse('lunch_menu_sets.html',ctx,status_code=status)

@router.get('/lunch/{pid}/menu/sets')
def library(pid:int,request:Request,db:Session=Depends(get_db),selected:int|None=None,edit:int|None=None,new:bool=False,use:int|None=None):
    ctx=context(request,db,pid);chosen=db.get(LunchMenuSet,edit or selected) if edit or selected else ctx['sets'][0] if ctx['sets'] else None
    if (edit or selected) and not chosen:raise HTTPException(404,'ไม่พบชุดเมนู')
    ctx.update(selected=chosen,editing=bool(edit),creating=new,form_name=chosen.name if edit else '',form_days=len(chosen.items) if edit else 10,form_rows=chosen.items if edit else [])
    if use:
        if not db.get(LunchMenuSet,use):raise HTTPException(404,'ไม่พบชุดเมนู')
        ctx['sequence']=[str(use)]
    return page(ctx)

@router.post('/lunch/{pid}/menu/sets/save')
async def save(pid:int,request:Request,db:Session=Depends(get_db)):
    ctx=context(request,db,pid);f=await request.form(max_fields=4000);raw=f.get('set_id','');obj=db.get(LunchMenuSet,int(raw)) if str(raw).isdigit() else None
    if raw and not obj:raise HTTPException(404,'ไม่พบชุดเมนู')
    try:
        name,rows=service.fields(f);obj=service.save(db,obj or LunchMenuSet(),name,rows);db.commit()
    except ValueError as e:
        db.rollback();mains=f.getlist('main');desserts=f.getlist('dessert');notes=f.getlist('note')
        rows=[dict(main=x,dessert=desserts[i] if i<len(desserts) else '',note=notes[i] if i<len(notes) else '',groups=','.join(f.getlist('groups_'+str(i)))) for i,x in enumerate(mains)]
        ctx.update(selected=obj,editing=bool(obj),creating=not obj,form_name=f.get('name',''),form_days=len(rows) or 10,form_rows=rows,error=str(e));return page(ctx,422)
    return RedirectResponse('/lunch/'+str(pid)+'/menu/sets?'+urlencode(dict(selected=obj.id,msg='บันทึกชุดเมนูแล้ว')),303)

@router.post('/lunch/{pid}/menu/sets/{sid}/copy')
def copy(pid:int,sid:int,request:Request,db:Session=Depends(get_db)):
    context(request,db,pid);source=db.get(LunchMenuSet,sid)
    if not source:raise HTTPException(404,'ไม่พบชุดเมนู')
    rows=[dict(main=i.main,dessert=i.dessert,note=i.note,groups=i.groups) for i in source.items]
    obj=service.save(db,LunchMenuSet(),source.name[:110]+' (สำเนา)',rows);db.commit()
    return RedirectResponse(f'/lunch/{pid}/menu/sets?edit={obj.id}',303)

@router.post('/lunch/{pid}/menu/sets/use')
async def use(pid:int,request:Request,db:Session=Depends(get_db)):
    ctx=context(request,db,pid);f=await request.form(max_fields=4000);ids=f.getlist('set_ids');start=f.get('start','');end=f.get('end','');mode=f.get('mode','skip')
    ctx.update(sequence=ids,start=start,end=end,mode=mode)
    try:
        if f.get('action')=='apply':
            plan=service.apply(db,ctx['p'],ids,start,end,mode,f.get('token',''),f.get('confirm_replace')=='yes');db.commit()
            return RedirectResponse(f'/lunch/{pid}/menu?'+urlencode(dict(msg=f"สร้างเมนู {plan['created']} วัน แทนที่ {plan['replaced']} วัน ข้ามเมนูเดิม {plan['skipped']} วัน")),303)
        ctx['plan']=service.preview(db,ctx['p'],ids,start,end,mode)
    except ValueError as e:db.rollback();ctx['error']=str(e);return page(ctx,422)
    return page(ctx)

@router.post('/lunch/{pid}/menu/day')
async def save_day(pid:int,request:Request,db:Session=Depends(get_db)):
    from app.services import school_calendar as cal
    p=db.get(LunchProgram,pid)
    if not p:raise HTTPException(404,'ไม่พบโครงการ')
    f=await request.form(max_fields=4000);date=parse_be_date(f.get('date',''));main=f.get('main','').strip()
    if not date or not main:raise HTTPException(422,'กรอกวันที่และอาหารคาวให้ครบ')
    rows=db.query(LunchMenu).filter_by(program_id=pid,date=date).all()
    mid=f.get('mid','');explicit=db.get(LunchMenu,int(mid)) if str(mid).isdigit() else None
    if mid and (not explicit or explicit.program_id!=pid):raise HTTPException(404,'ไม่พบเมนูของโครงการนี้')
    if explicit and explicit.date and explicit.date!=date:raise HTTPException(422,'เมนูนี้อยู่คนละวัน กรุณาเปิดวันที่ที่ต้องการแก้ใหม่')
    if explicit and rows and explicit not in rows:raise HTTPException(422,'วันนี้มีเมนูแล้ว กรุณาเปิดเมนูของวันนี้แทน')
    if max(len(main),len(f.get('dessert','')),len(f.get('note','')))>500:raise HTTPException(422,'ข้อความเมนูยาวเกิน 500 ตัวอักษร')
    if len(rows)>1 and not explicit:raise HTTPException(422,'วันนี้มีเมนูซ้ำ กรุณาตรวจรายการเดิมด้านล่างก่อนบันทึก')
    if not rows and not cal.state(db,p.year).get(date.date().isoformat(),False):raise HTTPException(422,'วันนี้ไม่ใช่วันเรียนในปฏิทินโรงเรียน')
    obj=explicit or (rows[0] if rows else LunchMenu(program_id=pid,date=date))
    obj.date=date
    obj.main=main;obj.dessert=f.get('dessert','').strip();obj.note=f.get('note','').strip();obj.groups=','.join(g for g in ['1','2','3','4','5'] if g in f.getlist('groups'));db.add(obj);db.commit()
    from app.routers.lunch import _stay_url
    url=_stay_url(f'/lunch/{pid}/menu',f.get('back',''));url+=('&' if '?' in url else '?')+urlencode(dict(d=be_date_input(date),msg='บันทึกเมนูแล้ว'))
    return RedirectResponse(url,303)
