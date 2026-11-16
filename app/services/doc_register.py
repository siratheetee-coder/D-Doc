"""Read-only register projection. Never renumber or silently repair historical documents."""
from collections import defaultdict
from types import SimpleNamespace
from app import models as m


def source_link(typ, source, ref):
    if not ref: return ''
    if source == 'admin':
        return {'command':f'/admin/orders/{ref}','memo':f'/admin/memos/{ref}',
                'outgoing':f'/admin/letters/{ref}'}.get(typ,'')
    if source=='procurement': return f'/procurement/{ref}'
    if source=='finance': return f'/finance/disburse/{ref}'
    if source=='incoming_register': return f'/admin/incoming/{ref}'
    if source=='outgoing_register': return '/admin/outgoing'
    if source=='asset_audit': return f'/assets/audit?year={ref}'
    if source=='lunch': return '/lunch'
    return ''


def records(db, include_stale=False):
    from app.services.doc_number import parse_seq,parse_outgoing_seq,doc_year
    rows = {}
    current_keys = set()
    supported = {'admin','procurement','finance','incoming_register','outgoing_register'}
    def sequence(typ,no): return parse_outgoing_seq(no) if typ=='outgoing' else parse_seq(no)
    def add(typ,fy,no,source,ref,subject,date,id=None):
        seq = sequence(typ,no)
        if not seq: return
        year=doc_year(typ,fy,no,date)
        key=(typ,year,seq,source,ref)
        rows[key]=SimpleNamespace(id=id,doc_type=typ,fiscal_year=year,seq=seq,
            full_no=no,source=source,ref_id=ref,subject=subject or '',date=date,
            href=source_link(typ,source,ref),conflict=False)
    for r in db.query(m.IssuedDocNo):
        add(r.doc_type,r.fiscal_year,r.full_no or f'{r.seq}/{r.fiscal_year}',r.source,r.ref_id,r.subject,r.date,r.id)
    def add_source(*args):
        # Prefer current source fields over a stale title/date in the register.
        typ,fy,no,source,ref,subject,date=args
        key=(typ,doc_year(typ,fy,no,date),sequence(typ,no),source,ref)
        current_keys.add(key)
        previous=rows.get(key)
        add(*args,id=previous.id if previous else None)
    for model,typ,field in [(m.SchoolOrder,'command','order_no'),(m.OfficeMemo,'memo','memo_no'),
                            (m.OfficialLetter,'outgoing','doc_no')]:
        for r in db.query(model): add_source(typ,r.fiscal_year,getattr(r,field), 'admin',r.id,r.subject,r.date)
    for r in db.query(m.Procurement):
        for field,typ,datefield in [('memo_no','memo','request_date'),('result_memo_no','memo','request_date'),
                ('spec_memo_no','memo','request_date'),('inspect_memo_no','memo','inspect_date'),
                ('command_no','command','command_date'),('spec_cmd_no','command','spec_cmd_date'),
                ('purchase_cmd_no','command','purchase_cmd_date'),
                ('order_no','purchase_order' if r.proc_type=='ซื้อ' else 'hire_order','order_date')]:
            add_source(typ,r.fiscal_year,getattr(r,field),'procurement',r.id,r.subject,getattr(r,datefield))
        if getattr(r,'budget_memo_on',False):
            add_source('memo',r.fiscal_year,r.budget_memo_no,'procurement',r.id,r.subject,r.request_date)
    for r in db.query(m.DisburseMemo):
        add_source('memo',r.fiscal_year,r.memo_no,'finance',r.id,r.subject,r.date)
    for r in db.query(m.IncomingLetter).filter(m.IncomingLetter.calendar_year.isnot(None)):
        add_source('incoming',r.calendar_year,f'{r.recv_no}/{r.calendar_year}','incoming_register',r.id,r.subject,r.recv_date)
    for r in db.query(m.OutgoingLetter):
        # send_seq is the sequence saved by this source, not the ministry's prefix.
        from app.services.doc_number import parse_outgoing_seq
        seq=parse_outgoing_seq(r.send_no) or r.send_seq
        if seq:
            year=doc_year('outgoing',r.fiscal_year,r.send_no,r.date)
            add_source('outgoing',year,r.send_no or f'{seq}/{year}','outgoing_register',r.id,r.subject,r.date)
    if not include_stale:
        rows = {key:row for key,row in rows.items() if row.source not in supported or row.ref_id is None or key in current_keys}
    groups=defaultdict(list)
    for row in rows.values():groups[(row.doc_type,row.fiscal_year,row.seq)].append(row)
    from app.services.doc_number_links import same_document
    for group in groups.values():
        if len(group)>1:
            canonical=next((r for r in group if r.id is not None),group[0])
            distinct=[r for r in group if r is not canonical and not same_document(
                db,r.doc_type,r.fiscal_year,r.seq,r.source,r.ref_id,canonical.source,canonical.ref_id)]
            if not distinct:
                for r in group:
                    if r is not canonical:
                        rows.pop((r.doc_type,r.fiscal_year,r.seq,r.source,r.ref_id),None)
            else:
                for r in group:r.conflict=True
    return sorted(rows.values(),key=lambda r:(r.doc_type,r.fiscal_year,r.seq,r.source or '',r.ref_id or 0))


def summary(db, years):
    from app.services.doc_number import COUNTER_TYPES
    rows=records(db)
    reserved_rows=records(db,include_stale=True)
    counters={(c.doc_type,c.fiscal_year):c.last_number or 0 for c in db.query(m.DocNumberCounter)}
    result=[]
    for typ,label in COUNTER_TYPES.items():
        year=years[typ]
        selected=[r for r in rows if r.doc_type==typ and r.fiscal_year==year]
        last=max(selected,key=lambda r:r.seq) if selected else None
        reserved=max(counters.get((typ,year),0), max((r.seq for r in reserved_rows if r.doc_type==typ and r.fiscal_year==year),default=0))
        if typ=='incoming':
            from app.services.incoming_register import next_number
            reserved=max(reserved,next_number(db,year)-1)
        if not reserved: continue
        result.append(dict(label=label,last=last.full_no if last else '—',next=f'{reserved+1}/{year}',
                           reserved=f'{reserved}/{year}',gap=reserved>(last.seq if last else 0),
                           subject=last.subject if last else '',date=last.date if last else None,
                           conflict=any(r.conflict for r in selected)))
    return result
