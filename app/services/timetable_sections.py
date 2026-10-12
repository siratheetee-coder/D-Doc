"""Primary/secondary period selection and real-time overlap checks."""
import re
from app.models import AcadPeriod, AcadTimetableConfig, AcadClass, AcadTimetable, SubstituteAssignment
from app.services.academic import is_secondary


def separated(db, year):
    row=db.get(AcadTimetableConfig,year)
    return bool(row and row.separated)


def section_for(db, year, level):
    return 'secondary' if separated(db,year) and is_secondary(level) else 'primary'


def periods(db, year, section=None, level=None):
    if level is not None:section=section_for(db,year,level)
    q=db.query(AcadPeriod).filter_by(year=year)
    if section is not None:q=q.filter_by(school_section=section)
    return q.order_by(AcadPeriod.seq,AcadPeriod.id).all()


def interval(label):
    match=re.fullmatch(r'\s*(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\s*',label or '')
    if not match:return None
    h,m,j,n=map(int,match.groups())
    if h>23 or j>23 or m>59 or n>59 or h*60+m>=j*60+n:return None
    return h*60+m,j*60+n


def overlaps(a,b):
    if not a or not b:return True  # Unknown times cannot establish teacher availability.
    if a.id==b.id:return True
    x,y=interval(a.time_label),interval(b.time_label)
    if x and y:return max(x[0],y[0])<min(x[1],y[1])
    return a.school_section!=b.school_section or a.seq==b.seq


def enable(db,year):
    # Serialize enable requests so repeated clicks cannot duplicate periods.
    db.connection().exec_driver_sql('UPDATE acad_period SET seq=seq WHERE year=?',(year,))
    if separated(db,year):return
    old=periods(db,year,'primary');mapping={}
    for p in old:
        copy=AcadPeriod(year=year,school_section='secondary',seq=p.seq,name=p.name,time_label=p.time_label,is_break=p.is_break)
        db.add(copy);db.flush();mapping[p.id]=copy.id
    secondary=[c.id for c in db.query(AcadClass).filter_by(year=year) if is_secondary(c.level)]
    for old_id,new_id in mapping.items():
        db.query(AcadTimetable).filter(AcadTimetable.class_id.in_(secondary),AcadTimetable.period_id==old_id).update({AcadTimetable.period_id:new_id},synchronize_session=False)
        db.query(SubstituteAssignment).filter(SubstituteAssignment.class_id.in_(secondary),SubstituteAssignment.period_id==old_id).update({SubstituteAssignment.period_id:new_id},synchronize_session=False)
    config=db.get(AcadTimetableConfig,year)
    if not config:config=AcadTimetableConfig(year=year);db.add(config)
    config.separated=True
    db.flush()
