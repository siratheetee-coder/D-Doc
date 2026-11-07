"""Contract register: validated edits, delivery alerts and reviewed source imports."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib,json
from app.models import Contract, Procurement, LunchHireRound
from app.thai_utils import parse_be_date, be_date_input

TYPES=['สัญญาจ้าง','สัญญาซื้อ','ใบสั่งจ้าง','ใบสั่งซื้อ','ข้อตกลง']
STATUSES=['ระหว่างดำเนินการ','ส่งมอบแล้ว','ตรวจรับแล้ว','จ่ายแล้ว','สิ้นสุด']
DELIVERED=set(STATUSES[1:])
FIELDS=['contract_no','ctype','party','subject','amount','sign_date','start_date','end_date','status']
LABELS=dict(contract_no='เลขที่สัญญา/ใบสั่ง',ctype='ประเภท',party='คู่สัญญา',subject='เรื่อง/งาน',amount='วงเงิน',
            sign_date='วันทำสัญญา',start_date='วันเริ่มงาน',end_date='ครบกำหนดส่งมอบ',status='สถานะ')

class InvalidContract(ValueError):
    def __init__(self, errors):
        self.errors=errors
        super().__init__(' · '.join(errors.values()))

def alert(c,today):
    if c.status in DELIVERED or not c.end_date:return None,None
    days=(c.end_date.date()-today).days
    return days,'overdue' if days<0 else 'soon' if days<=15 else None

def values(c):
    out={k:getattr(c,k) for k in FIELDS}
    for k in ('contract_no','party','subject'):out[k]=out[k] or ''
    out['ctype']=out['ctype'] or 'ใบสั่งจ้าง';out['status']=out['status'] or 'ระหว่างดำเนินการ'
    out['amount']=out['amount'] or 0
    return out

def validate(form,existing=None):
    result=values(existing) if existing else dict(contract_no='',ctype='ใบสั่งจ้าง',party='',subject='',amount=0,
        sign_date=None,start_date=None,end_date=None,status='ระหว่างดำเนินการ')
    errors={}
    for k in ('contract_no','ctype','party','subject','status'):
        if k in form:result[k]=str(form[k]).strip()
    if not any(result[k] for k in ('contract_no','party','subject')):errors['subject']='กรอกชื่อเรื่อง เลขที่สัญญา หรือคู่สัญญาอย่างน้อยหนึ่งช่อง'
    for k in ('contract_no','party','subject'):
        if len(result[k])>1000:errors[k]=LABELS[k]+'ยาวเกินไป'
    if result['ctype'] not in TYPES:errors['ctype']='เลือกประเภทสัญญาจากรายการ'
    if result['status'] not in STATUSES:errors['status']='เลือกสถานะจากรายการ'
    if 'amount' in form:
        try:
            n=Decimal(str(form['amount']).strip().replace(',',''))
            if not n.is_finite() or n<0 or n>Decimal('999999999999.99') or n!=n.quantize(Decimal('.01')):raise ValueError()
            result['amount']=float(n)
        except (InvalidOperation,ValueError):errors['amount']='กรอกวงเงินตั้งแต่ 0 บาท และไม่เกิน 2 ตำแหน่งทศนิยม'
    for k in ('sign_date','start_date','end_date'):
        if k not in form:continue
        text=str(form[k]).strip();result[k]=parse_be_date(text) if text else None
        if text and result[k] is None:errors[k]=LABELS[k]+'ไม่ถูกต้อง กรุณากรอกวัน/เดือน/ปี พ.ศ.'
    if result['sign_date'] and result['end_date'] and result['end_date']<result['sign_date']:
        errors['end_date']='วันครบกำหนดต้องไม่ก่อนวันทำสัญญา'
    if result['start_date'] and result['end_date'] and result['end_date']<result['start_date']:
        errors['end_date']='วันครบกำหนดต้องไม่ก่อนวันเริ่มงาน'
    if errors:raise InvalidContract(errors)
    return result

def serialize(c,today=None):
    days,level=alert(c,today or datetime.now().date())
    out={k:(be_date_input(v) if v else '') if k.endswith('_date') else v for k,v in values(c).items()}
    out.update(id=c.id,fiscal_year=c.fiscal_year,days_left=days,level=level,
               missing_due=not c.end_date and c.status not in DELIVERED,
               source=c.source,ref_id=c.ref_id)
    return out

def source_link(c):
    if c.source=='procurement' and c.ref_id:return f'/procurement/{c.ref_id}'
    if c.source=='lunch' and c.ref_id:return f'/lunch/round/{c.ref_id}/edit'
    return ''

def _proc(p,rounds=()):
    status=p.status if p.status in STATUSES else 'ตรวจรับแล้ว' if p.status=='เบิกจ่ายแล้ว' else 'ระหว่างดำเนินการ'
    linked=[r for r in rounds if r.procurement_id==p.id and (r.order_no or '').strip()==(p.order_no or '').strip()]
    if linked and all(r.status=='จ่ายแล้ว' for r in linked):status='จ่ายแล้ว'
    return dict(contract_no=(p.order_no or '').strip(),ctype='ใบสั่งจ้าง' if p.proc_type=='จ้าง' else 'ใบสั่งซื้อ',
        party=p.vendor.name if p.vendor else '',subject=p.subject,amount=round(p.total_amount or 0,2),
        sign_date=p.order_date,start_date=min((r.start_date for r in linked if r.start_date),default=None),
        end_date=p.delivery_due_date or max((r.end_date for r in linked if r.end_date),default=None),status=status)

def _date_year(d):return d.year+543+(d.month>=10) if d else None

def display(k,v):
    if k.endswith('_date'):return be_date_input(v) if v else 'ยังไม่ระบุ'
    if k=='amount':return f'{v or 0:,.2f} บาท'
    return str(v or 'ยังไม่ระบุ')

def candidates(db,fy,kind):
    """A linked lunch order shares the procurement identity; never merge by number alone."""
    procs={p.id:p for p in db.query(Procurement).all()}
    rounds=db.query(LunchHireRound).all()
    contracts=db.query(Contract).populate_existing().order_by(Contract.id).all()
    raw=[];excluded=0
    if kind=='procurement':
        for p in procs.values():
            if p.fiscal_year!=fy or not (p.order_no or '').strip():continue
            aliases={('procurement',p.id)}|{('lunch',r.id) for r in rounds if r.procurement_id==p.id and (r.order_no or '').strip()==p.order_no.strip()}
            raw.append((f'procurement:{p.id}',p.id,_proc(p,rounds),aliases,''))
    elif kind=='lunch':
        for r in rounds:
            if not (r.order_no or '').strip():continue
            p=procs.get(r.procurement_id)
            linked=bool(p and (p.order_no or '').strip() and p.order_no.strip()==r.order_no.strip())
            year=p.fiscal_year if linked else _date_year(r.order_date)
            if year and year!=fy:excluded+=1;continue
            reason='' if year else 'ยังไม่มีวันทำใบสั่งจ้าง จึงยังระบุปีงบประมาณไม่ได้'
            if p and (p.order_no or '').strip() and not linked:reason='เลขใบสั่งจ้างไม่ตรงกับเรื่องจัดจ้างที่ผูกไว้ กรุณาตรวจต้นทาง'
            if linked:
                data=_proc(p,rounds)
                aliases={('procurement',p.id)}|{('lunch',x.id) for x in rounds if x.procurement_id==p.id and (x.order_no or '').strip()==r.order_no.strip()}
                raw.append((f'procurement:{p.id}',p.id,data,aliases,reason))
            else:
                data=dict(contract_no=r.order_no.strip(),ctype='ใบสั่งจ้าง',party=r.vendor.name if r.vendor else '',
                    subject=f'จ้างเหมาประกอบอาหารกลางวัน รอบที่ {r.seq}',amount=round(r.amount or 0,2),
                    sign_date=r.order_date,start_date=r.start_date,end_date=r.end_date,
                    status='จ่ายแล้ว' if r.status=='จ่ายแล้ว' else 'ระหว่างดำเนินการ')
                raw.append((f'lunch:{r.id}',r.id,data,{('lunch',r.id)},reason))
    else:raise ValueError('ไม่พบประเภทข้อมูลต้นทาง')
    out=[];seen=set()
    for key,ref,data,aliases,reason in raw:
        if key in seen:continue
        seen.add(key)
        matches=[c for c in contracts if (c.source,c.ref_id) in aliases]
        if len(matches)>1:reason='พบทะเบียนเดิมซ้ำจากเรื่องเดียวกัน กรุณาตรวจรายการเดิมก่อน'
        old=matches[0] if len(matches)==1 else None
        if old and old.fiscal_year!=fy:reason=f'เคยลงทะเบียนไว้ในปีงบ {old.fiscal_year} แล้ว กรุณาตรวจปีของรายการเดิม'
        if not matches and data['party']:
            manual_matches=[c for c in contracts if c.fiscal_year==fy and c.contract_no==data['contract_no'] and c.party==data['party']]
            if manual_matches:
                matches=manual_matches
                reason='มีเลขที่และคู่สัญญานี้ในทะเบียนแล้ว กรุณาตรวจรายการเดิมก่อน'
        if old and old.status=='สิ้นสุด':data['status']='สิ้นสุด'
        # Preserve a manually entered start date when procurement has no such field.
        if old and data['start_date'] is None:data['start_date']=old.start_date
        diffs=[dict(field=k,label=LABELS[k],before=display(k,getattr(old,k)),after=display(k,v))
               for k,v in data.items() if old and getattr(old,k)!=v]
        action='blocked' if reason else 'add' if not old else 'update' if diffs else 'same'
        out.append(dict(key=key,source=key.split(':')[0],ref_id=ref,data=data,matches=matches,existing_id=old.id if old else None,
            action=action,reason=reason,diffs=diffs,old=old,
            href=f'/procurement/{ref}' if key.startswith('procurement:') else f'/lunch/round/{ref}/edit'))
    return out,excluded

def preview(db,fy,kind):
    rows,excluded=candidates(db,fy,kind)
    payload=[(r['key'],r['data'],r['action'],r['existing_id'],values(r['old']) if r['old'] else None,r['reason']) for r in rows]
    token=hashlib.sha256(json.dumps([fy,kind,payload],ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    return dict(rows=rows,excluded=excluded,token=token,kind=kind,
                selectable=sum(r['action'] in ('add','update') for r in rows))

def apply(db,fy,kind,selected,expected):
    from app.services.subsidy import lock
    lock(db)
    view=preview(db,fy,kind)
    if view['token']!=expected:raise ValueError('ข้อมูลต้นทางหรือทะเบียนเปลี่ยนแล้ว กรุณาเปิดรายการตรวจสอบใหม่')
    allowed={r['key']:r for r in view['rows'] if r['action'] in ('add','update')}
    if not selected or set(selected)-allowed.keys():raise ValueError('เลือกรายการที่เพิ่มหรืออัปเดตได้อย่างน้อยหนึ่งรายการ')
    added=updated=0
    for key in set(selected):
        r=allowed[key]
        # Validate source dates/amounts as well as manually entered data.
        form={k:be_date_input(v) if isinstance(v,datetime) else '' if v is None else str(v) for k,v in r['data'].items()}
        data=validate(form,r['old'])
        if r['old']:c=r['old'];updated+=1
        else:
            c=Contract(fiscal_year=fy,source=r['source'],ref_id=r['ref_id']);db.add(c);added+=1
        for k,v in data.items():setattr(c,k,v)
    db.flush()
    return added,updated
