"""Frozen served dates for old installments; reviewed realignment against school days."""
from datetime import date,datetime,timedelta
from bisect import bisect_left
from sqlalchemy.orm import object_session
import json,hashlib
from app.models import LunchInstallment,LunchMealCount,LunchLedger
from app.services import school_calendar as sc

def legacy_days(prog,start,end):
    from app.services.thai_holidays import holiday_map,is_workday
    if not start or not end:return []
    base=prog.year-543;hs=set(holiday_map([base-1,base,base+1]))
    d=start.date() if isinstance(start,datetime) else start;e=end.date() if isinstance(end,datetime) else end
    result=[]
    while d<=e:
        if is_workday(d,hs):result.append(d)
        d+=timedelta(days=1)
    return result

def stored_days(obj,prog):
    raw=getattr(obj,'calendar_dates',None)
    if raw is not None:
        try:return [date.fromisoformat(d) for d in json.loads(raw)]
        except (ValueError,TypeError):pass
    # NULL identifies pre-upgrade records: preserve the old counting rule.
    return legacy_days(prog,obj.start_date,obj.end_date)

def freeze(obj,prog,db=None):
    db=db or object_session(obj) or object_session(prog)
    result=sc.days(db,prog.year,obj.start_date,obj.end_date)
    obj.calendar_dates=json.dumps([d.isoformat() for d in result])
    return result

def round_days(rnd):
    result=set(stored_days(rnd,rnd.program))
    for i in rnd.installments:
        if i.start_date and i.end_date:
            result={d for d in result if not i.start_date.date()<=d<=i.end_date.date()}
            result.update(stored_days(i,rnd.program))
    return sorted(result)

def preview(db,rnd):
    db.refresh(rnd)
    items=db.query(LunchInstallment).populate_existing().filter_by(round_id=rnd.id).order_by(LunchInstallment.seq,LunchInstallment.id).all()
    available=sc.open_dates(db,rnd.program.year)
    meal_rows=db.query(LunchMealCount).filter_by(program_id=rnd.program_id).all()
    recorded={r.date.date() for r in meal_rows if r.date}
    led_ids={x.installment_id for x in db.query(LunchLedger).filter(LunchLedger.installment_id.in_([i.id for i in items]))} if items else set()
    rows=[];errors=[];end_errors=[];required_end=None;cursor=rnd.start_date.date() if rnd.start_date else None
    for i in items:
        before=stored_days(i,rnd.program);target=int(i.days or len(before));reason='';after=before
        protected=rnd.status=='จ่ายแล้ว' or i.status not in ('ร่าง','') or i.id in led_ids
        if not i.start_date or not i.end_date or target<=0:
            errors.append(f'งวด {i.seq} ยังไม่มีช่วงวันที่หรือจำนวนวันครบถ้วน');reason='ข้อมูลช่วงวันที่ไม่ครบ'
        elif protected:
            reason='คงเดิม: ส่งมอบ ตรวจรับ หรือจ่ายแล้ว'
            if cursor and cursor>i.start_date.date():errors.append(f'การเลื่อนงวดก่อนหน้าจะชนกับงวด {i.seq} ที่ดำเนินการแล้ว')
            cursor=i.end_date.date()+timedelta(days=1)
        else:
            start=cursor or i.start_date.date();pos=bisect_left(available,start);after=available[pos:pos+target]
            if len(after)!=target:
                errors.append(f'วันเรียนไม่พอสำหรับงวด {i.seq} กรุณาตรวจปฏิทิน');after=before
            if (set(before)-set(after)) & recorded:
                errors.append(f'งวด {i.seq} มีวันที่บันทึกยอดนักเรียนแล้วซึ่งจะถูกตัดออก กรุณาตรวจข้อมูลก่อน');reason='มีข้อมูลยอดนักเรียนที่ต้องตรวจ'
            if len(after)==target and after and rnd.end_date and after[-1]>rnd.end_date.date():
                required_end=max(required_end,after[-1]) if required_end else after[-1]
                message=f'งวด {i.seq} จะสิ้นสุดหลังวันที่สิ้นสุดรอบ กรุณาตรวจและแก้ช่วงรอบก่อนยืนยัน'
                errors.append(message);end_errors.append(message)
            if after:cursor=after[-1]+timedelta(days=1)
        rows.append(dict(inst=i,before=before,after=after,protected=protected,reason=reason,
            changed=not protected and before!=after,start=after[0] if after else None,end=after[-1] if after else None,
            added=sorted(set(after)-set(before)),removed=sorted(set(before)-set(after))))
    payload=[rnd.id,rnd.start_date,rnd.end_date,rnd.status,sc.state(db,rnd.program.year),
        [(i.id,i.start_date,i.end_date,i.days,i.amount,i.status,i.deliver_date,i.inspect_date,i.calendar_dates) for i in items],
        [(r.id,r.date,r.class_id,r.count) for r in meal_rows],sorted(x for x in led_ids if x is not None)]
    token=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    return dict(rows=rows,errors=list(dict.fromkeys(errors)),display_errors=list(dict.fromkeys(e for e in errors if e not in end_errors)),token=token,required_end=required_end,changed=sum(r['changed'] for r in rows))

def apply(db,rnd,expected):
    from app.services.subsidy import lock
    lock(db);db.info.pop(('school-calendar',int(rnd.program.year)),None)
    plan=preview(db,rnd)
    if expected!=plan['token']:raise ValueError('ปฏิทินหรือข้อมูลงวดเปลี่ยนแล้ว กรุณาตรวจผลกระทบใหม่')
    if plan['errors']:raise ValueError(' · '.join(plan['errors']))
    count=0
    for row in plan['rows']:
        if row['protected'] or not row['changed']:continue
        i=row['inst'];old_end=i.end_date
        i.start_date=datetime.combine(row['start'],datetime.min.time());i.end_date=datetime.combine(row['end'],datetime.min.time())
        if i.deliver_date==old_end:i.deliver_date=i.end_date
        if i.inspect_date==old_end:i.inspect_date=i.end_date
        i.calendar_dates=json.dumps([d.isoformat() for d in row['after']]);count+=1
        # Preserve agreed amount, daily counts and financial transactions.
    db.flush();return count
