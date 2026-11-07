"""One school-day calendar shared by academic and school lunch workflows."""
from datetime import date,datetime,timedelta
from calendar import monthrange
from bisect import bisect_left
from urllib.parse import urlsplit,urlencode
import re
from app.models import AcadCalendar
from app.services.academic import academic_ce_year,parse_days_csv,auto_open_days

MONTHS=[(5,'พ.ค.'),(6,'มิ.ย.'),(7,'ก.ค.'),(8,'ส.ค.'),(9,'ก.ย.'),(10,'ต.ค.'),
        (11,'พ.ย.'),(12,'ธ.ค.'),(1,'ม.ค.'),(2,'ก.พ.'),(3,'มี.ค.'),(4,'เม.ย.')]

def safe_return(value):
    text=str(value or '')
    try:parts=urlsplit(text)
    except ValueError:return ''
    if parts.scheme or parts.netloc or parts.query or '\\' in text:return ''
    if re.fullmatch(r'/lunch/(?:\d+/rounds|round/\d+/(?:edit|plan))',parts.path) and parts.fragment in ('','installments'):
        return parts.path+('#'+parts.fragment if parts.fragment else '')
    return ''

def settings_link(year,back=''):
    params={'year':year}
    if safe_return(back):params['return_to']=safe_return(back)
    return '/settings/calendar?'+urlencode(params)

def state(db,year):
    key=('school-calendar',int(year))
    if key in db.info:return db.info[key]
    saved={r.month:set(parse_days_csv(r.days_csv)) for r in db.query(AcadCalendar).filter_by(year=year)}
    values={}
    for month,_ in MONTHS:
        ce=academic_ce_year(year,month)
        days=saved.get(month)
        if days is None:days=set(auto_open_days(year,month,db))
        for day in range(1,monthrange(ce,month)[1]+1):values[date(ce,month,day).isoformat()]=day in days
    db.info[key]=values
    return values

def open_dates(db,year):return [date.fromisoformat(s) for s,v in state(db,year).items() if v]

def days(db,year,start,end):
    if not start or not end:return []
    a=start.date() if isinstance(start,datetime) else start
    b=end.date() if isinstance(end,datetime) else end
    return [d for d in open_dates(db,year) if a<=d<=b]

def ranges(db,year,start,lengths):
    if isinstance(start,datetime):start=start.date()
    if not start:raise ValueError('กรอกวันเริ่มรอบก่อนคำนวณงวด')
    if not lengths or any(n<=0 for n in lengths) or sum(lengths)>366:raise ValueError('จำนวนวันของงวดไม่ถูกต้อง')
    available=open_dates(db,year);pos=bisect_left(available,start);out=[]
    for n in lengths:
        part=available[pos:pos+n]
        if len(part)!=n:raise ValueError('วันเรียนในปีการศึกษานี้ไม่พอสำหรับจำนวนวันที่กำหนด กรุณาตรวจปฏิทินหรือจำนวนวัน')
        out.append(part);pos+=n
    return out

def may_edit(request,db):
    if request.session.get('owner'):return True
    from app.modules import parse_modules
    from app.accounts import can_use_module
    mods=parse_modules(request.session.get('mods',''))
    tid=request.session.get('tid')
    if 'lunch' in mods and can_use_module(tid,'lunch'):return True
    return ('academic' in mods and not request.session.get('person_id') and can_use_module(tid,'academic'))

def may_read(request,db):
    if may_edit(request,db) or request.session.get('director'):return True
    from app.modules import parse_modules
    from app.accounts import can_use_module
    return 'academic' in parse_modules(request.session.get('mods','')) and can_use_module(request.session.get('tid'),'academic')

def redirect(request,year,flag='',back=''):
    from fastapi.responses import RedirectResponse
    base='/settings/calendar' if request.url.path.startswith('/settings/') else '/academic/calendar'
    params={'year':year}
    ret=safe_return(back)
    if ret:params['return_to']=ret
    url=base+'?'+urlencode(params)
    if flag:url+='&'+flag
    return RedirectResponse(url,303)

def apply_exclusions(db,year,previous_holidays=None,terms=False):
    """Closing a newly added holiday updates saved calendar months, keeping make-up days."""
    from app.models import AcadYearSetting
    from app.services.academic import holiday_map,in_term
    closed=set(holiday_map(year,db))-(previous_holidays or set()) if previous_holidays is not None else set()
    setting=db.query(AcadYearSetting).filter_by(year=year).first()
    for row in db.query(AcadCalendar).filter_by(year=year):
        valid=[d for d in parse_days_csv(row.days_csv) if (row.month,d) not in closed
            and (not terms or in_term(year,row.month,d,setting))]
        row.days_csv=','.join(map(str,valid))
    db.info.pop(('school-calendar',int(year)),None)
