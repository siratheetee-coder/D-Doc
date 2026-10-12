# -*- coding: utf-8 -*-
"""
project_money.py - โครงการนี้ใช้เงินจากหมวดไหน (เชื่อมโครงการกับทะเบียนคุมเงิน)

เดิมฟอร์มเบิกจ่ายถามแยก 4 ช่อง (แหล่งเงิน / บัญชี / หมวด / โครงการ) ที่ไม่รู้จักกัน
ผู้ใช้เลือกโครงการแล้วต้องไปเลือกบัญชีกับหมวดเองอีก ทั้งที่ระบบรู้อยู่แล้ว

ระบบรู้ได้จากสองทาง เรียงตามความน่าเชื่อถือ
  1. จัดสรรไว้ในแผน   โครงการได้รับเงินจากหมวดไหน (ProjectFunding -> PlanFunding.account_item_id)
  2. เคยใช้ครั้งก่อน   บันทึกขอเบิกจ่าย/รายการจ่ายของโครงการนี้ที่เคยระบุหมวดไว้
ทางที่ 2 ทำให้โรงเรียนไม่ต้องตั้งค่าอะไรล่วงหน้า เลือกหมวดครั้งแรกครั้งเดียว ครั้งต่อไประบบจำให้

หมวด (AccountItem) แยกรายปีงบ หมวดที่จำไว้จากปีงบก่อนจึงต้องหา "หมวดชื่อเดียวกันในปีงบนี้"
ไม่งั้นจะหักเงินลงหมวดของปีที่ปิดไปแล้ว (แผนปีการศึกษาคร่อมสองปีงบ เจอกรณีนี้ทุกปี)
"""
from sqlalchemy import or_

from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Procurement

try:        # ระบบจัดสรรงบให้โครงการ (หน้างบประมาณที่ใช้จัดทำแผน) ยังไม่มีในทุกเครื่อง
    from app.models import PlanFunding, ProjectFunding
except ImportError:                                  # ไม่มีก็ใช้แค่ "เคยใช้ครั้งก่อน" ไปก่อน
    PlanFunding = ProjectFunding = None

ALLOCATED = "จัดสรรไว้ในแผน"
USED_BEFORE = "เคยใช้ครั้งก่อน"


def _same_item_in_year(db, item, fy):
    """หมวดเดียวกันในปีงบ fy (ชื่อเดียวกัน บัญชีเดียวกัน หมวดแม่ชื่อเดียวกัน) ไม่พบคืน None"""
    if item is None:
        return None
    if item.fiscal_year == fy:
        return item
    parent_name = item.parent.name if item.parent_id and item.parent else None
    for cand in db.query(AccountItem).filter_by(account_id=item.account_id, fiscal_year=fy,
                                                name=item.name).all():
        cp = cand.parent.name if cand.parent_id and cand.parent else None
        if cp == parent_name:
            return cand
    return None


def _entry(account, item, why):
    label = account.name + (f" / {item.name}" if item else "")
    return {"account_id": account.id, "account_name": account.name,
            "item_id": item.id if item else None, "item_name": item.name if item else "",
            "label": label, "why": why}


def project_sources(db, project_id, fy) -> list:
    """หมวดที่โครงการนี้ใช้ ในปีงบ fy · เรียงจากน่าเชื่อถือที่สุด ไม่ซ้ำกัน

    คืน [{account_id, account_name, item_id, item_name, label, why}]
    item_id เป็น None ได้ (บัญชีที่ไม่ได้แบ่งหมวด)
    """
    if not project_id:
        return []
    out, seen = [], set()

    def add(account, item, why):
        if account is None:
            return
        key = (account.id, item.id if item else None)
        if key in seen:
            return
        seen.add(key)
        out.append(_entry(account, item, why))

    # 1) จัดสรรไว้ในแผน
    rows = [] if PlanFunding is None else (db.query(PlanFunding)
            .join(ProjectFunding, ProjectFunding.funding_id == PlanFunding.id)
            .filter(ProjectFunding.project_id == project_id, ProjectFunding.amount > 0,
                    PlanFunding.account_item_id.isnot(None))
            .order_by(ProjectFunding.amount.desc()).all())
    for f in rows:
        it = _same_item_in_year(db, db.get(AccountItem, f.account_item_id), fy)
        if it is not None:
            add(it.account, it, ALLOCATED)

    # 2) เคยใช้ครั้งก่อน (ล่าสุดก่อน) · นับทั้งบันทึกที่ผูกโครงการตรง และที่ผูกผ่านเรื่องจัดซื้อ
    proc_ids = [p.id for p in db.query(Procurement.id).filter(Procurement.project_id == project_id)]
    memo_q = db.query(DisburseMemo).filter(DisburseMemo.account_id.isnot(None))
    cond = DisburseMemo.project_id == project_id
    if proc_ids:
        cond = or_(cond, DisburseMemo.procurement_id.in_(proc_ids))
    memo_q = memo_q.filter(cond)
    history = [(m.id, m.account_id, m.item_id) for m in memo_q.order_by(DisburseMemo.id.desc()).all()]
    history += [(t.id, t.account_id, t.item_id) for t in
                db.query(FinanceTxn).filter(FinanceTxn.project_id == project_id,
                                            FinanceTxn.kind == "out")
                .order_by(FinanceTxn.id.desc()).all()]
    for _, acc_id, item_id in history:
        acc = db.get(FinanceAccount, acc_id)
        if item_id:
            it = _same_item_in_year(db, db.get(AccountItem, item_id), fy)
            if it is None:
                continue          # หมวดของปีก่อนที่ปีนี้ไม่มีแล้ว ปล่อยให้ผู้ใช้เลือกเอง
            add(acc, it, USED_BEFORE)
        else:
            add(acc, None, USED_BEFORE)
    return out


def item_allocations(db, item_rows, txn_project) -> dict:
    """หมวดในทะเบียนคุมเงินจัดสรรให้โครงการไหนบ้าง (ระยะ 2 ฝั่งการเงิน)

    item_rows   แถวหมวดของหน้าทะเบียนคุมเงิน {it, level, remain, ...} หมวดแม่มาก่อนลูกเสมอ
    txn_project {txn_id: Project} ของรายการจ่ายในปีงบนี้ (ได้จาก _txn_projects)

    คืน {item_id: {...}} เฉพาะหมวดที่มีการจัดสรร หมวดแม่รวมยอดของลูก
      paid      จ่ายแล้วทั้งหมดของหมวด (ทั้งที่ผูกโครงการและไม่ผูก)
      waiting   รอใช้ในโครงการ = ส่วนที่จัดสรรให้โครงการไว้แต่โครงการยังไม่ได้จ่ายจากหมวดนี้
      free      ยังไม่จัดสรรให้โครงการ = เงินคงเหลือจริง - รอใช้ในโครงการ (ติดลบ = จัดสรรเกิน)
      projects  [{project, allocated, used}] เรียงยอดจัดสรรมากไปน้อย

    นับ "โครงการใช้ไปจากหมวดนี้" ไม่เกินยอดที่จัดสรรให้ เพราะส่วนที่จ่ายเกินจัดสรรเป็นเงินของหมวด
    ที่โครงการเอาไปใช้เพิ่ม ไม่ได้ทำให้ยอดรอใช้ของโครงการอื่นลดลง
    """
    if PlanFunding is None or not item_rows:
        return {}
    ids = [r["it"].id for r in item_rows]
    rows = (db.query(PlanFunding.account_item_id, ProjectFunding.project_id, ProjectFunding.amount)
            .join(ProjectFunding, ProjectFunding.funding_id == PlanFunding.id)
            .filter(PlanFunding.account_item_id.in_(ids), ProjectFunding.amount > 0).all())
    if not rows:
        return {}
    alloc = {}                                     # {item_id: {project_id: amount}}
    for item_id, pid, amt in rows:
        alloc.setdefault(item_id, {})
        alloc[item_id][pid] = round(alloc[item_id].get(pid, 0) + (amt or 0), 2)

    from app.models import Project
    pids = {pid for per in alloc.values() for pid in per}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(pids))}

    own = {}
    for r in item_rows:
        it = r["it"]
        per = alloc.get(it.id, {})
        spent_by = {}                              # {project_id: จ่ายจากหมวดนี้}
        for t in it.account.txns:
            if t.item_id != it.id or t.kind != "out" or t.fiscal_year != it.fiscal_year:
                continue
            pj = txn_project.get(t.id)
            if pj is not None and pj.id in per:
                spent_by[pj.id] = spent_by.get(pj.id, 0) + (t.amount or 0)
        plist = [{"project": projects[pid], "allocated": amt,
                  "used": round(min(spent_by.get(pid, 0), amt), 2)}
                 for pid, amt in per.items() if pid in projects]
        own[it.id] = plist

    out, parent_of = {}, {}
    current = None
    for r in item_rows:
        if r["level"] == 0:
            current = r["it"].id
        else:
            parent_of[r["it"].id] = current
    for r in item_rows:
        it = r["it"]
        plist = list(own.get(it.id, []))
        if r["level"] == 0:
            for kid, par in parent_of.items():
                if par == it.id:
                    plist += own.get(kid, [])
        if not plist:
            continue
        merged = {}
        for p in plist:
            m = merged.setdefault(p["project"].id, {"project": p["project"], "allocated": 0, "used": 0})
            m["allocated"] = round(m["allocated"] + p["allocated"], 2)
            m["used"] = round(m["used"] + p["used"], 2)
        plist = sorted(merged.values(), key=lambda x: -x["allocated"])
        waiting = round(sum(p["allocated"] - p["used"] for p in plist), 2)
        remain = round(r["remain"], 2)
        out[it.id] = {"paid": round(r["tout"], 2), "remain": remain, "waiting": waiting,
                      "free": round(remain - waiting, 2), "projects": plist,
                      "allocated": round(sum(p["allocated"] for p in plist), 2)}
    return out
