"""Explicit plan funding, isolated from ledger cash and legacy project budgets."""
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import or_
from app.models import (PlanBudget, PlanFunding, ProjectFunding, Project,
                        AccountItem, SubsidySnapshot, SubsidyReceiptLink, FinanceTxn, DisburseMemo, Procurement)
from app.services import subsidy as sub
from app.services.budget import project_budget
from app.services.asset_utils import item_remaining_asof


def amount(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > 1_000_000_000:
            raise ValueError()
        return float(n.quantize(Decimal('.01')))
    except (ValueError, InvalidOperation):
        raise ValueError('กรอกจำนวนเงินตั้งแต่ 0 ถึง 1,000,000,000 บาท')


def defaults(year, mode):
    if not 2500 <= year <= 2800:
        raise ValueError('ปีของแผนไม่ถูกต้อง')
    ce = year - 543
    return (datetime(ce, 5, 1), datetime(ce+1, 4, 30)) if mode == 'academic' else (datetime(ce-1, 10, 1), datetime(ce, 9, 30))


def plan(db, year):
    return db.query(PlanBudget).filter_by(year=year).first()


def save_period(db, year, mode, start, end):
    sub.lock(db)
    if mode not in ('budget', 'academic'):
        raise ValueError('เลือกปีงบประมาณหรือปีการศึกษา')
    ds, de = defaults(year, mode)
    try:
        from app.thai_utils import parse_be_date
        start = parse_be_date(start) if '/' in start else datetime.fromisoformat(start)
        end = parse_be_date(end) if '/' in end else datetime.fromisoformat(end)
        if not start or not end or start.tzinfo or end.tzinfo or start.time()!=datetime.min.time() or end.time()!=datetime.min.time():
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('กรอกวันเริ่มและสิ้นสุดแผน')
    if start > end or (end-start).days > 366 or (mode == 'budget' and (start != ds or end != de)) or (mode == 'academic' and (start.year != year-543 or end.year != year-542)):
        raise ValueError('ช่วงวันที่ไม่ตรงกับปีของแผน (ปีงบใช้ 1 ต.ค.–30 ก.ย.; ปีการศึกษาคร่อมปีถัดไปและไม่เกิน 1 ปี)')
    p = plan(db, year)
    if p and db.query(PlanFunding).filter_by(plan_id=p.id).count() and (p.mode, p.start_date, p.end_date) != (mode, start, end):
        raise ValueError('นำงบเข้าแผนแล้ว กรุณายกเลิกการจัดสรรและนำงบออกก่อนเปลี่ยนช่วงแผน')
    if not p:
        p = PlanBudget(year=year); db.add(p)
    p.mode, p.start_date, p.end_date = mode, start, end
    db.flush()
    return p


def sources(db, p):
    return db.query(PlanFunding).populate_existing().filter_by(plan_id=p.id).order_by(PlanFunding.id).all() if p else []


def allocated(db, source_id, excluding=None):
    q = db.query(ProjectFunding).populate_existing().filter_by(funding_id=source_id)
    if excluding is not None:
        q = q.filter(ProjectFunding.project_id != excluding)
    return round(sum(x.amount for x in q), 2)


def project_allocated(db, pid):
    return round(sum(x.amount for x in db.query(ProjectFunding).filter_by(project_id=pid)), 2)


def eligible(p, snap):
    return snap.academic_year == p.year if p.mode == 'academic' else snap.fiscal_year == p.year


def subsidy_candidates(db, p, snapshot_id):
    snap = db.get(SubsidySnapshot, snapshot_id)
    if not snap or not eligible(p, snap):
        raise ValueError('ฉบับเงินอุดหนุนไม่ตรงกับปีของแผน')
    current = sub.state(db, snap.academic_year, snap.term)
    if current['changed'] or not current['latest'] or current['latest'].id != snap.id:
        raise ValueError('ยอดเงินอุดหนุนเปลี่ยนแล้ว ไปบันทึกและยืนยันฉบับล่าสุดก่อนนำเข้าแผน')
    data = json.loads(snap.payload)
    mapped = sub.mappings(db, snap.fiscal_year)
    result = []
    desired = {r['key']: r for r in data['result']['rows']}
    prefix = f'subsidy:{snap.academic_year}:{snap.term}:'
    # Removed supplementary entries must be reviewed as reductions to zero.
    for old in db.query(PlanFunding).filter(PlanFunding.source_key.startswith(prefix)):
        key = old.source_key[len(prefix):]
        desired.setdefault(key, dict(key=key, name=sub.NAMES.get(key,old.name), budget_amount=0, full=0))
    for key, row in desired.items():
        val = row.get('budget_amount', row.get('full'))
        if val is None:
            raise ValueError('ยอดเงินอุดหนุนยังไม่ครบ กรุณาคำนวณและยืนยันใหม่')
        item = mapped.get(key)
        if val and not item:
            raise ValueError('จับคู่หมวดในหน้าคำนวณเงินอุดหนุนก่อนนำเข้าแผน: '+row['name'])
        # Receipts before the plan starts already form part of its opening cash.
        early = db.query(SubsidyReceiptLink).join(FinanceTxn,FinanceTxn.id==SubsidyReceiptLink.txn_id).filter(
            SubsidyReceiptLink.academic_year==snap.academic_year,SubsidyReceiptLink.term==snap.term,
            SubsidyReceiptLink.item_key==key,FinanceTxn.date<p.start_date,FinanceTxn.kind=='in').all()
        received_before=round(sum(x.amount for x in early),2)
        val=max(0,amount(val)-received_before)
        result.append(dict(source_key=prefix+key, kind='subsidy', name=f"{row['name']} · ปีการศึกษา {snap.academic_year} เทอม {snap.term}", amount=amount(val),
                           snapshot_id=snap.id, account_item_id=item.id if item else None,
                           payload=dict(academic_year=snap.academic_year, term=snap.term, fiscal_year=snap.fiscal_year,
                                        key=key, token=data['token'], received_before=received_before)))
    return result


def opening_candidates(db, p):
    # Budget year: use the new year's opening, not all prior transactions again.
    fy = p.start_date.year + 543 + (1 if p.start_date.month >= 10 else 0)
    cutoff = p.start_date - timedelta(microseconds=1)
    result = []
    for item in db.query(AccountItem).filter_by(fiscal_year=fy).order_by(AccountItem.id):
        value = float(item.opening_balance or 0) if p.start_date.month == 10 and p.start_date.day == 1 else item_remaining_asof(item, cutoff)
        if value < 0:
            continue
        # Self balance only; parent totals must never include children twice.
        result.append(dict(source_key=f'opening:{p.start_date.date()}:{item.id}', kind='opening',
                           name=f'{item.account.name} / {item.name}', amount=amount(value), snapshot_id=None,
                           account_item_id=item.id, payload=dict(cutoff=str(cutoff.date()), fiscal_year=fy)))
    return result


def preview(db, p, kind, snapshot_id=0):
    conflicting = db.query(PlanBudget).join(PlanFunding,PlanFunding.plan_id==PlanBudget.id).filter(
        PlanBudget.id!=p.id,PlanBudget.start_date<=p.end_date,PlanBudget.end_date>=p.start_date).first()
    if conflicting:
        raise ValueError(f'มีแผนปี {conflicting.year} ที่นำงบมาใช้ในช่วงวันที่ซ้อนกันแล้ว กรุณาตรวจช่วงแผนเพื่อไม่ให้นับเงินซ้ำ')
    desired = subsidy_candidates(db, p, snapshot_id) if kind == 'subsidy' else opening_candidates(db, p) if kind == 'opening' else None
    if desired is None:
        raise ValueError('ประเภทงบไม่ถูกต้อง')
    rows = []
    for r in desired:
        old = db.query(PlanFunding).filter_by(source_key=r['source_key']).first()
        if old and old.plan_id != p.id:
            raise ValueError('เงินก้อนนี้อยู่ในแผนอื่นแล้ว ไม่สามารถนำมานับซ้ำ: '+r['name'])
        if not old and r['amount']==0:
            continue
        used = allocated(db, old.id) if old else 0
        rows.append(dict(r, old=old.amount if old else 0, allocated=used,
                         delta=round(r['amount']-(old.amount if old else 0),2)))
    return dict(plan_id=p.id, mode=p.mode, start=str(p.start_date),end=str(p.end_date),kind=kind, snapshot_id=snapshot_id, rows=rows)


def apply(db, p, kind, snapshot_id, expected, selected):
    sub.lock(db)
    db.refresh(p)
    data = preview(db, p, kind, snapshot_id)
    if sub.fingerprint(data) != expected:
        raise ValueError('ยอดเปลี่ยนแล้ว กรุณาเปิดหน้าตรวจยอดใหม่')
    if not selected or set(selected)-{r['source_key'] for r in data['rows']}:
        raise ValueError('เลือกรายการเงินที่จะนำเข้าแผนอย่างน้อยหนึ่งรายการ')
    data['rows']=[r for r in data['rows'] if r['source_key'] in selected]
    for r in data['rows']:
        if r['amount'] < r['allocated']:
            raise ValueError('ยอดใหม่ต่ำกว่ายอดที่จัดสรรให้โครงการแล้ว กรุณาปรับการจัดสรรก่อน: '+r['name'])
    for r in data['rows']:
        row = db.query(PlanFunding).filter_by(source_key=r['source_key']).first()
        if not row:
            row = PlanFunding(plan_id=p.id, source_key=r['source_key']); db.add(row)
        for k in ('kind','name','amount','snapshot_id','account_item_id'):
            setattr(row,k,r[k])
        row.payload = sub.dumps(r['payload'])
    db.flush()


def changed(db, p, row):
    try:
        if row.kind == 'subsidy':
            saved = json.loads(row.payload)
            now = sub.state(db, saved['academic_year'], saved['term'])
            if now['changed'] or not now['latest'] or now['latest'].id != row.snapshot_id:
                return True
            current=next((r for r in subsidy_candidates(db,p,row.snapshot_id) if r['source_key']==row.source_key),None)
            return current is None or current['amount']!=row.amount or current['account_item_id']!=row.account_item_id
        if row.kind == 'opening':
            current = next((r for r in opening_candidates(db,p) if r['source_key']==row.source_key),None)
            return current is None or current['amount'] != row.amount
    except (ValueError, KeyError):
        return True
    return False


def summary(db, p):
    rows = [dict(source=s, allocated=allocated(db,s.id), changed=changed(db,p,s)) for s in sources(db,p)]
    total = round(sum(r['source'].amount for r in rows),2)
    used = round(sum(r['allocated'] for r in rows),2)
    return dict(rows=rows, total=total, allocated=used, remaining=round(total-used,2))


def allocation_token(db, p, project):
    return sub.fingerprint([project.id, project.plan_year, project_budget(project),
        [[s.id,s.amount,allocated(db,s.id)] for s in sources(db,p)],
        [[a.funding_id,a.amount] for a in db.query(ProjectFunding).filter_by(project_id=project.id).order_by(ProjectFunding.id)]])


def allocate(db, p, project, values, expected):
    sub.lock(db)
    db.refresh(p);db.refresh(project);db.expire(project,['revisions'])
    if project.plan_year != p.year or allocation_token(db,p,project) != expected:
        raise ValueError('งบหรือการจัดสรรเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่')
    rows = sources(db,p)
    if set(values) - {str(s.id) for s in rows}:
        raise ValueError('รายการเงินไม่อยู่ในแผนนี้')
    desired = {s.id:amount(values.get(str(s.id),0)) for s in rows}
    if round(sum(desired.values()),2) > round(project_budget(project),2):
        raise ValueError('ยอดจัดสรรรวมเกินงบโครงการ กรุณาปรับงบโครงการก่อน')
    for s in rows:
        old=db.query(ProjectFunding).filter_by(project_id=project.id,funding_id=s.id).first()
        if desired[s.id]>(old.amount if old else 0) and changed(db,p,s):
            raise ValueError('ยอดต้นทางเปลี่ยนแล้ว กรุณาตรวจและอัปเดตงบแผนก่อนจัดสรรเพิ่ม: '+s.name)
        if round(desired[s.id]+allocated(db,s.id,project.id),2) > s.amount:
            raise ValueError('จัดสรรเกินวงเงินที่ยังเหลือ: '+s.name)
    for old in db.query(ProjectFunding).filter_by(project_id=project.id).all(): db.delete(old)
    db.flush()
    for sid, value in desired.items():
        if value: db.add(ProjectFunding(project_id=project.id,funding_id=sid,amount=value))


def actual_paid(db, project):
    # One ledger transaction counted once, whether linked directly or through a memo.
    procurement_ids=db.query(Procurement.id).filter(Procurement.project_id==project.id)
    memo_ids = db.query(DisburseMemo.id).filter(or_(DisburseMemo.project_id==project.id,DisburseMemo.procurement_id.in_(procurement_ids)))
    rows = db.query(FinanceTxn).filter(FinanceTxn.kind=='out',or_(FinanceTxn.project_id==project.id,FinanceTxn.disburse_id.in_(memo_ids))).all()
    return round(sum(t.amount or 0 for t in rows),2)


def guard_project(db, project, *, year=None, budget=None, deleting=False):
    """All legacy project-edit paths must respect explicit funding allocations."""
    from fastapi import HTTPException
    sub.lock(db)
    assigned=project_allocated(db,project.id)
    if assigned and (deleting or (year is not None and year!=project.plan_year)):
        raise HTTPException(409,'ยกเลิกการจัดสรรงบของโครงการก่อนลบหรือย้ายปี')
    if budget is not None and budget<assigned:
        raise HTTPException(409,'งบใหม่ต่ำกว่ายอดที่จัดสรรไว้ กรุณาปรับการจัดสรรก่อนลดงบโครงการ')


def guard_items(db, ids):
    from fastapi import HTTPException
    sub.lock(db)
    if db.query(PlanFunding).filter(PlanFunding.account_item_id.in_(ids)).first():
        raise HTTPException(409,'หมวดนี้เชื่อมกับงบแผนอยู่ กรุณานำเงินออกจากแผนก่อนลบหมวดหรือบัญชี')
