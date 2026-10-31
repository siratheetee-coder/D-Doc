"""School-scoped officer choices and immutable-by-default case signatures."""
import json
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, object_session
from fastapi import HTTPException
from app.models import School, StaffOfficer, Procurement, DisburseMemo, MoneyLoan, BankRecon, RevenueRemit

ROLES = {'officer_name':'เจ้าหน้าที่พัสดุ', 'head_officer_name':'หัวหน้าเจ้าหน้าที่พัสดุ',
         'finance_officer_name':'เจ้าหน้าที่การเงิน', 'finance_head_name':'หัวหน้าเจ้าหน้าที่การเงิน',
         'admin_officer_name':'เจ้าหน้าที่ธุรการ', 'academic_head_name':'หัวหน้าฝ่ายวิชาการ'}
CASE_ROLES = tuple(list(ROLES)[:4])
MODELS = (Procurement, DisburseMemo, MoneyLoan, BankRecon, RevenueRemit)

def defaults(school):
    return {key:(getattr(school,key,'') or '').strip() for key in CASE_ROLES}

def read(record):
    try:
        raw=json.loads(getattr(record,'staff_snapshot','') or '{}')
        return {k:str(v) for k,v in raw.items() if k in CASE_ROLES and isinstance(v,str)}
    except (ValueError,AttributeError,TypeError):
        return {}

def initial(db, record, school):
    selected=defaults(school)
    # A payment originating from a procurement carries its selected signers.
    procurement_id=record.get('procurement_id') if isinstance(record,dict) else getattr(record,'procurement_id',None)
    if procurement_id:
        selected.update(read(db.get(Procurement,procurement_id)))
    selected.update(read(record))
    return selected

def roster(db, school):
    result={key:[] for key in ROLES}
    for person in db.query(StaffOfficer).order_by(StaffOfficer.id):
        if person.role in result and person.name not in result[person.role]: result[person.role].append(person.name)
    for key in ROLES:
        name=(getattr(school,key,'') or '').strip()
        if name and name not in result[key]: result[key].insert(0,name)
    return result

def apply(db, record, payload=None):
    school=db.query(School).first()
    values=initial(db,record,school)
    if payload is not None:
        try:
            chosen=json.loads(payload)
            if not isinstance(chosen,dict) or any(k not in CASE_ROLES or not isinstance(v,str) for k,v in chosen.items()): raise ValueError()
        except (ValueError,TypeError):
            raise HTTPException(400,'ข้อมูลผู้รับผิดชอบไม่ถูกต้อง กรุณาเลือกใหม่')
        choices=roster(db,school)
        for key,value in chosen.items():
            if value and value != values.get(key) and value not in choices[key]:
                raise HTTPException(400,'ไม่พบเจ้าหน้าที่ที่เลือกในโรงเรียนนี้ กรุณาโหลดหน้าใหม่')
            values[key]=value
    record.staff_snapshot=json.dumps(values,ensure_ascii=False)

class _SchoolView:
    def __init__(self,school,values): self._school,self._values=school,values
    def __getattr__(self,key):
        return self._values[key] if key in self._values else getattr(self._school,key)

def school_for(record,school):
    return _SchoolView(school,read(record))

def context(request,record=None,finance=False):
    from app.tenancy import session_for
    db=object_session(record) if record is not None and inspect(record,raiseerr=False) is not None else None
    own=db is None
    if own: db=session_for(request.session.get('tid'))
    try:
        school=db.query(School).first()
        selected=initial(db,record,school)
        choices=roster(db,school)
        roles=CASE_ROLES[2:] if finance else CASE_ROLES
        for key in roles:
            if selected[key] and selected[key] not in choices[key]: choices[key].append(selected[key])
        return dict(roles=[(k,ROLES[k]) for k in roles],choices=choices,selected=selected)
    finally:
        if own: db.close()

@event.listens_for(Session,'before_flush')
def capture_signers(db,flush_context,instances):
    pending=[obj for obj in db.new if isinstance(obj,MODELS)]
    schools=[obj for obj in db.dirty if isinstance(obj,School)]
    if not pending and not schools: return
    school=next(iter(schools),None) or next((o for o in db.new if isinstance(o,School)),None) or db.query(School).first()
    if school is None: return
    previous={key:(getattr(school,key,'') or '').strip() for key in ROLES}
    persisted=(db.connection().execute(select(School.__table__).where(School.id==school.id)).mappings().first()
               if inspect(school).persistent else None)
    changed=False
    for key in ROLES:
        history=inspect(school).attrs[key].history
        if history.has_changes():
            previous[key]=(persisted[key] or '') if persisted else ((history.deleted[0] or '') if history.deleted else previous[key])
            changed=True
    if changed:
        # Freeze legacy rows BEFORE a school-wide default changes; never overwrite a saved choice.
        for cls in MODELS:
            for record in db.query(cls).filter((cls.staff_snapshot=='') | cls.staff_snapshot.is_(None)):
                record.staff_snapshot=json.dumps({k:previous[k] for k in CASE_ROLES},ensure_ascii=False)
        existing={(p.role,p.name) for p in list(db.query(StaffOfficer))+list(db.new) if isinstance(p,StaffOfficer)}
        for key,name in previous.items():
            if name and (key,name) not in existing:
                db.add(StaffOfficer(role=key,name=name));existing.add((key,name))
    for record in pending:
        if not record.staff_snapshot:
            record.staff_snapshot=json.dumps(initial(db,record,school),ensure_ascii=False)
