"""Reusable school-local menu sets and reviewed, calendar-aware application."""
from datetime import datetime
import hashlib,json
from app.models import LunchMenuSet,LunchMenuSetItem,LunchMenu
from app.services import school_calendar as calendar
from app.thai_utils import parse_be_date

def fields(form):
    name=(form.get('name') or '').strip()
    try:n=int(form.get('days','0'))
    except ValueError:n=0
    mains=form.getlist('main');desserts=form.getlist('dessert');notes=form.getlist('note')
    if not name or len(name)>120:raise ValueError('กรอกชื่อชุดเมนู ไม่เกิน 120 ตัวอักษร')
    if not 1<=n<=366 or len(mains)!=n or len(desserts)!=n:raise ValueError('จำนวนวันกับรายการเมนูต้องตรงกัน (1–366 วัน)')
    rows=[]
    for i in range(n):
        main=mains[i].strip();dessert=desserts[i].strip();note=notes[i].strip() if i<len(notes) else ''
        if not main:raise ValueError(f'กรอกอาหารคาวของวันที่ {i+1}')
        if max(len(main),len(dessert),len(note))>500:raise ValueError('ข้อความเมนูยาวเกิน 500 ตัวอักษร')
        groups=','.join(g for g in ['1','2','3','4','5'] if g in form.getlist('groups_'+str(i)))
        rows.append(dict(main=main,dessert=dessert,note=note,groups=groups))
    return name,rows

def save(db,obj,name,rows):
    obj.name=name;db.add(obj);db.flush()
    obj.items[:]=[LunchMenuSetItem(seq=i+1,**row) for i,row in enumerate(rows)]
    db.flush();return obj

def preview(db,prog,ids,start,end,mode):
    if mode not in ('skip','replace'):raise ValueError('เลือกวิธีจัดการวันที่มีเมนูเดิม')
    if not ids or len(ids)>50:raise ValueError('เลือกและเรียงชุดเมนูก่อน (ไม่เกิน 50 ชุดต่อครั้ง)')
    sets=[];cycle=[]
    for raw in ids:
        try:obj=db.get(LunchMenuSet,int(raw),populate_existing=True)
        except (ValueError,TypeError):obj=None
        if obj:db.expire(obj,['items'])
        if not obj or not obj.items:raise ValueError('ไม่พบชุดเมนูที่เลือก กรุณาเลือกใหม่')
        sets.append(obj)
        for i in obj.items:cycle.append((obj,i))
    a=parse_be_date(start);b=parse_be_date(end)
    if not a or not b or b<a:raise ValueError('กรอกวันที่เริ่มและสิ้นสุดให้ถูกต้อง')
    state=calendar.state(db,prog.year)
    if a.date().isoformat()<min(state) or b.date().isoformat()>max(state):raise ValueError('เลือกช่วงวันภายในปีการศึกษาของโครงการนี้')
    dates=calendar.days(db,prog.year,a,b)
    if not dates:raise ValueError('ช่วงนี้ไม่มีวันเรียน กรุณาตรวจปฏิทินโรงเรียน')
    old=db.query(LunchMenu).filter(LunchMenu.program_id==prog.id,LunchMenu.date>=a,LunchMenu.date<=b).order_by(LunchMenu.id).all()
    existing={}
    for m in old:existing.setdefault(m.date.date(),[]).append(m)
    if mode=='replace' and any(len(v)>1 for v in existing.values()):raise ValueError('ช่วงที่เลือกมีเมนูซ้ำในวันเดียวกัน กรุณาตรวจเมนูรายวันก่อนแทนที่')
    rows=[]
    for n,d in enumerate(dates):
        obj,item=cycle[n%len(cycle)];prior=existing.get(d,[])
        action='skip' if prior and mode=='skip' else 'replace' if prior else 'create'
        rows.append(dict(date=d,set_name=obj.name,seq=item.seq,item=item,old=prior,action=action))
    payload=[prog.id,prog.year,ids,start,end,mode,state,
        [(o.id,o.name,[(i.id,i.seq,i.main,i.dessert,i.note,i.groups) for i in o.items]) for o in sets],
        [(m.id,m.date,m.main,m.dessert,m.note,m.groups) for m in old]]
    token=hashlib.sha256(json.dumps(payload,default=str,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(rows=rows,token=token,total=len(rows),created=sum(r['action']=='create' for r in rows),replaced=sum(r['action']=='replace' for r in rows),skipped=sum(r['action']=='skip' for r in rows))

def apply(db,prog,ids,start,end,mode,token,confirmed):
    from app.services.subsidy import lock
    lock(db);db.info.pop(('school-calendar',prog.year),None)
    plan=preview(db,prog,ids,start,end,mode)
    if not token or token!=plan['token']:raise ValueError('ชุดเมนู ปฏิทิน หรือเมนูรายวันเปลี่ยนแล้ว กรุณาดูตัวอย่างใหม่ก่อนยืนยัน')
    if plan['replaced'] and not confirmed:raise ValueError('กรุณายืนยันว่าต้องการแทนที่เมนูเดิมตามตัวอย่าง')
    for row in plan['rows']:
        if row['action']=='skip':continue
        item=row['item'];obj=row['old'][0] if row['old'] else LunchMenu(program_id=prog.id,date=datetime.combine(row['date'],datetime.min.time()))
        obj.main=item.main;obj.dessert=item.dessert;obj.note=item.note;obj.groups=item.groups;db.add(obj)
    db.flush();return plan
