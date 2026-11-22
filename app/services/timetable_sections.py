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


def merged_columns(periods):
    """คาบประถม+มัธยมรวมเป็นคอลัมน์เดียวเมื่อเวลาตรงกัน (ตารางสอนรายครู) เรียงตามเวลาเริ่ม
    คืน list ของ SimpleNamespace(id, ids, name, time_label, is_break, seq)"""
    from types import SimpleNamespace
    cols = {}
    for p in periods:
        key = (p.time_label or "").strip() or f"#{p.seq}:{p.name}"
        c = cols.setdefault(key, SimpleNamespace(id=p.id, ids=[], name=p.name, time_label=p.time_label,
                                                 is_break=True, seq=p.seq or 0))
        c.ids.append(p.id)
        if not p.is_break:
            c.is_break = False
            c.name = p.name
    def start(c):
        r = interval(c.time_label)
        return (r[0] if r else 9999 + c.seq, c.seq)
    out = []
    for c in sorted(cols.values(), key=start):
        prev = out[-1] if out else None
        a, b = (interval(prev.time_label) if prev else None), interval(c.time_label)
        # คาบพักของประถม/มัธยมที่เวลาเหลื่อมกัน (เช่น พักเที่ยง 11:30 กับ 12:00) รวมเป็นคอลัมน์พักเดียว
        if prev and prev.is_break and c.is_break and a and b and b[0] <= a[1]:
            prev.ids += c.ids
            if c.time_label and c.time_label not in prev.time_label:
                prev.time_label = f"{prev.time_label} / {c.time_label}"
            continue
        out.append(c)
    return out
