from datetime import datetime,timedelta
from urllib.parse import urlencode
from app.services import school_calendar as calendar
from app.thai_utils import be_date_input,parse_be_date

def daily_context(request,db,prog,edit,default):
    selected=edit.date if edit and edit.date else parse_be_date(request.query_params.get('d','')) or parse_be_date(request.query_params.get('week','')) or default
    start=parse_be_date(request.query_params.get('week','')) or selected
    start=start-timedelta(days=start.weekday());start=start.replace(hour=0,minute=0,second=0,microsecond=0)
    entries={}
    for m in sorted(prog.menus,key=lambda m:m.id):
        if m.date:entries.setdefault(m.date.date(),[]).append(m)
    state=calendar.state(db,prog.year);back=request.query_params.get('back','')
    def link(**kw):
        if back:kw['back']=back
        return f'/lunch/{prog.id}/menu?'+urlencode(kw)
    names=['จันทร์','อังคาร','พุธ','พฤหัสบดี','ศุกร์','เสาร์','อาทิตย์'];days=[]
    for i in range(7):
        d=start+timedelta(days=i);items=entries.get(d.date(),[])
        days.append(dict(name=names[i],date=d,be=be_date_input(d),open=state.get(d.date().isoformat(),False),menu=items[0] if items else None,active=d.date()==selected.date(),href=link(d=be_date_input(d))))
    obj=edit if edit else (entries.get(selected.date()) or [None])[0]
    return dict(days=days,start=start,end=start+timedelta(days=6),previous=link(week=be_date_input(start-timedelta(days=7))),next=link(week=be_date_input(start+timedelta(days=7))),selected=selected,menu=obj,open=state.get(selected.date().isoformat(),False),duplicates=len(entries.get(selected.date(),[])))
