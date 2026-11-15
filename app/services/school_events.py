"""Tenant-scoped school activity CRUD, visibility and calendar presentation."""
import json,calendar,re
from datetime import datetime,date,time,timedelta
from fastapi import HTTPException
from app.models import SchoolEvent,AcadClass
from app.services.academic import academic_ce_year
from app.thai_utils import parse_be_date,be_date_input,thai_date,thai_today

KINDS={'activity':'กิจกรรมโรงเรียน','meeting':'ประชุม','trip':'ทัศนศึกษา','exam':'สอบ','other':'อื่น ๆ'}
MONTHS=['','มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม']

def editable(request,db):
    from app.services import school_calendar
    return bool(request.session.get('owner') or (not request.session.get('person_id') and not request.session.get('director') and school_calendar.may_edit(request,db)))

def targets(event):
    try:return json.loads(event.targets_json or '[]')
    except (ValueError,TypeError):return []

def classes_for(db,pid=None):
    q=db.query(AcadClass)
    if pid:
        from app.routers.academic import _Scope
        q=q.filter(AcadClass.id.in_(_Scope(int(pid),db).class_ids or {-1}))
    return q.all()

def visible(db,years,pid=None):
    rows=db.query(SchoolEvent).filter(SchoolEvent.year.in_(years)).order_by(SchoolEvent.start_at,SchoolEvent.id).all()
    if not pid:return rows
    classes=classes_for(db,pid)
    by_year={y:({c.id for c in classes if c.year==y},{c.level for c in classes if c.year==y}) for y in years}
    return [e for e in rows if e.audience=='school' or (e.audience=='class' and bool(set(targets(e)) & by_year[e.year][0])) or (e.audience=='level' and bool(set(targets(e)) & by_year[e.year][1]))]

def audience_label(e,classes):
    if e.audience=='school':return 'ทั้งโรงเรียน'
    if e.audience=='level':return 'ระดับชั้น '+', '.join(targets(e))
    by_id={c.id:f'{c.level}/{c.room}' for c in classes}
    return 'ห้อง '+', '.join(by_id.get(i,'ห้องเดิมที่ถูกลบ') for i in targets(e))

def payload(e,classes,base='/academic/calendar'):
    return dict(id=e.id,year=e.year,title=e.title,kind=e.kind,kind_label=KINDS.get(e.kind,'กิจกรรม'),
        start=e.start_at.date().isoformat(),end=e.end_at.date().isoformat(),start_input=be_date_input(e.start_at),end_input=be_date_input(e.end_at),
        start_time=e.start_at.strftime('%H:%M'),end_time=e.end_at.strftime('%H:%M'),all_day=e.all_day,
        date_label=thai_date(e.start_at)+(' – '+thai_date(e.end_at) if e.end_at.date()!=e.start_at.date() else ''),
        time_label='ทั้งวัน' if e.all_day else e.start_at.strftime('%H:%M')+' – '+e.end_at.strftime('%H:%M'),
        audience=e.audience,targets=targets(e),audience_label=audience_label(e,classes),location=e.location or '',organizer=e.organizer or '',note=e.note or '',version=e.version,
        href=f'{base}?year={e.year}&month={e.start_at.month}&event={e.id}')

def validate(form,db):
    try:y=int(form.get('year',''))
    except (ValueError,TypeError):raise ValueError('เลือกปีการศึกษาให้ถูกต้อง')
    if not 2500<=y<=2800:raise ValueError('ปีการศึกษาไม่ถูกต้อง')
    title=(form.get('title') or '').strip()
    if not title or len(title)>200:raise ValueError('กรอกชื่อกิจกรรมไม่เกิน 200 ตัวอักษร')
    start=parse_be_date(form.get('start_date'));end=parse_be_date(form.get('end_date') or form.get('start_date'))
    if not start or not end:raise ValueError('กรอกวันเริ่มและวันสิ้นสุดให้ถูกต้อง')
    if not datetime(y-543,5,1)<=start<=end<datetime(y-542,5,1):raise ValueError('ช่วงกิจกรรมต้องอยู่ในปีการศึกษาที่เลือก (พฤษภาคม–เมษายน)')
    all_day=form.get('all_day')=='1'
    if not all_day:
        try:
            if not all(re.fullmatch(r'\d{2}:\d{2}',str(form.get(n,''))) for n in ('start_time','end_time')):raise ValueError()
            a=time.fromisoformat(str(form.get('start_time','')));b=time.fromisoformat(str(form.get('end_time','')))
            start=datetime.combine(start.date(),a);end=datetime.combine(end.date(),b)
        except ValueError:raise ValueError('กรอกเวลาเริ่มและสิ้นสุดให้ครบ')
        if end<=start:raise ValueError('เวลาสิ้นสุดต้องหลังเวลาเริ่ม')
    kind=form.get('kind','activity');audience=form.get('audience','school')
    if kind not in KINDS or audience not in ('school','level','class'):raise ValueError('ประเภทกิจกรรมหรือผู้เข้าร่วมไม่ถูกต้อง')
    classes=db.query(AcadClass).filter_by(year=y).all();chosen=[]
    if audience=='level':
        chosen=list(dict.fromkeys(form.getlist('levels')))
        if not chosen or not set(chosen)<={c.level for c in classes}:raise ValueError('เลือกระดับชั้นที่มีในปีการศึกษานี้')
    elif audience=='class':
        try:chosen=list(dict.fromkeys(int(x) for x in form.getlist('classes')))
        except (ValueError,TypeError):raise ValueError('ห้องเรียนไม่ถูกต้อง')
        if not chosen or not set(chosen)<={c.id for c in classes}:raise ValueError('เลือกห้องเรียนที่มีในปีการศึกษานี้')
    data=dict(year=y,title=title,kind=kind,start_at=start,end_at=end,all_day=all_day,audience=audience,targets_json=json.dumps(chosen,ensure_ascii=False))
    for name,limit in [('location',300),('organizer',200),('note',3000)]:
        value=str(form.get(name,'')).strip()
        if len(value)>limit:raise ValueError('ข้อความรายละเอียดกิจกรรมยาวเกินกำหนด')
        data[name]=value
    return data

def context(db,request,year,month=None,event_id=None):
    if not 2500<=year<=2800:raise HTTPException(400,'ปีการศึกษาไม่ถูกต้อง')
    now=thai_today();month=month if month is not None else (now.month if now.year==academic_ce_year(year,now.month) else 5)
    if not 1<=month<=12:raise HTTPException(400,'เดือนไม่ถูกต้อง')
    pid=None if request.session.get('owner') or request.session.get('director') else request.session.get('person_id')
    classes=db.query(AcadClass).filter_by(year=year).order_by(AcadClass.level,AcadClass.room).all()
    rows=visible(db,[year],pid);base='/academic/calendar' if request.url.path.startswith('/academic/') else '/settings/calendar'
    events=[payload(e,classes,base) for e in rows]
    selected=next((e for e in events if e['id']==event_id),None)
    if event_id and not selected:raise HTTPException(404,'ไม่พบกิจกรรมที่คุณมีสิทธิ์ดู')
    ce=academic_ce_year(year,month);first=date(ce,month,1);last=date(ce,month,calendar.monthrange(ce,month)[1])
    monthly=[e for e in events if e['start']<=last.isoformat() and e['end']>=first.isoformat()]
    upcoming=[e for e in events if e['end']>=now.isoformat()][:3]
    from app.services.teacher_home_acad import year_events
    from app.services.school_calendar import state
    # Existing holidays/term markers are read-only decoration in the activity view.
    markers=[e for e in year_events(db,year) if first.isoformat()<=e['d']<=last.isoformat()]
    dates=[];opened=state(db,year)
    for d in range(1,last.day+1):
        day=date(ce,month,d);iso=day.isoformat()
        dates.append(dict(iso=iso,day=d,weekend=day.weekday()>=5,today=day==now,open=opened.get(iso,False),events=[e for e in monthly if e['start']<=iso<=e['end']],markers=[e for e in markers if e['d']==iso]))
    prev=first-timedelta(days=1);nxt=last+timedelta(days=1)
    ay=lambda d:d.year+543-(1 if d.month<5 else 0)
    return dict(events=events,monthly=monthly,upcoming=upcoming,selected=selected or (upcoming[0] if upcoming else (monthly[0] if monthly else None)),days=dates,lead=first.weekday(),month=month,month_label=f'{MONTHS[month]} {ce+543}',can_edit=editable(request,db),classes=[dict(id=c.id,name=f'{c.level}/{c.room}') for c in classes],levels=sorted({c.level for c in classes}),kinds=KINDS,
        prev=f'{base}?year={ay(prev)}&month={prev.month}',next=f'{base}?year={ay(nxt)}&month={nxt.month}',today=f'{base}?year={ay(now)}&month={now.month}',base=base,initial_day=first.isoformat(),today_iso=now.isoformat())

def home_events(db,year,pid):
    classes=db.query(AcadClass).filter(AcadClass.year.in_([year-1,year,year+1])).all();rows=visible(db,[year-1,year,year+1],pid)
    events=[payload(e,classes) for e in rows];daily=[]
    for e in events:
        d=date.fromisoformat(e['start']);last=date.fromisoformat(e['end'])
        while d<=last:
            daily.append(dict(d=d.isoformat(),name=e['title'],kind=e['kind'],href=e['href'],audience_label=e['audience_label']));d+=timedelta(days=1)
    today=thai_today().isoformat()
    return daily,[e for e in events if e['end']>=today][:3]
