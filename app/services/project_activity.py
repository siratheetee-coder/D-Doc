# -*- coding: utf-8 -*-
"""กิจกรรมในโครงการ: จัดกลุ่มเรื่องจัดซื้อและบันทึกขอเบิกค่าอื่นของกิจกรรมเดียวกัน

ยอดใช้ของกิจกรรมคิดจากยอดตามเอกสาร (วงเงินเรื่องจัดซื้อ + ยอดขอเบิกที่ไม่ผ่านเรื่องจัดซื้อ)
ยอดของโครงการยังคิดจาก app.services.budget เหมือนเดิม กิจกรรมเป็นแค่การแบ่งกลุ่มดู
"""
from app.models import Project, ProjectActivity


def activities(db, project_id) -> list:
    return (db.query(ProjectActivity).filter_by(project_id=project_id)
            .order_by(ProjectActivity.seq, ProjectActivity.id).all())


def valid_activity(db, activity_id, project_id):
    """คืน id กิจกรรมเฉพาะเมื่อเป็นกิจกรรมของโครงการนั้นจริง (เปลี่ยนโครงการแล้วกิจกรรมเดิมหลุดเอง)"""
    try:
        aid = int(activity_id or 0)
    except (TypeError, ValueError):
        return None
    if not aid or not project_id:
        return None
    a = db.get(ProjectActivity, aid)
    return a.id if a and a.project_id == project_id else None


def activity_maps(db) -> dict:
    """ให้ช่องเลือกกิจกรรมในฟอร์ม: by_id = {project_id: [[id, name]]}, by_name = {ชื่อโครงการ: [[id, name]]}"""
    by_id, by_name = {}, {}
    names = {p.id: p.name for p in db.query(Project).order_by(Project.plan_year, Project.id)}
    for a in db.query(ProjectActivity).order_by(ProjectActivity.seq, ProjectActivity.id):
        by_id.setdefault(str(a.project_id), []).append([a.id, a.name])
    for pid, name in names.items():           # ชื่อซ้ำหลายปี: ปีใหม่กว่าทับ (ตรงกับที่ฟอร์มจัดซื้อเลือกโครงการ)
        if str(pid) in by_id:
            by_name[name] = by_id[str(pid)]
    return {"by_id": by_id, "by_name": by_name}


def _d(dt):
    from app.thai_utils import thai_date_short
    return thai_date_short(dt) if dt else "-"


def activity_groups(db, project, procs, memos) -> list:
    """[{a, docs, used, left}] ตามลำดับกิจกรรม + กลุ่มสุดท้าย a=None (ยังไม่ระบุกิจกรรม) ถ้ามีเอกสาร"""
    acts = activities(db, project.id)
    ids = {a.id for a in acts}
    docs = {a.id: [] for a in acts}
    loose = []
    for p in procs:
        row = {"kind": "จัดซื้อ/จัดจ้าง", "no": p.order_no or p.memo_no or "-", "subject": f"{p.proc_type or ''}{p.subject or ''}",
               "amount": float(p.total_amount or 0), "url": f"/procurement/{p.id}", "status": p.status or "", "type": "proc", "id": p.id, "paid_pre": bool(getattr(p, "paid_before_system", False)),
               "date": _d(p.order_date or p.request_date)}
        (docs[p.activity_id] if p.activity_id in ids else loose).append(row)
    for m in memos:
        row = {"kind": "ขอเบิกค่าใช้จ่ายอื่น" if m.proc_kind == "ค่าใช้จ่ายอื่น" else "ขอเบิกจ่าย",
               "no": m.memo_no or "-", "subject": m.subject or "", "amount": float(m.amount or 0),
               "url": f"/finance/disburse/{m.id}", "status": m.status or "", "type": "memo", "id": m.id,
               "date": _d(m.date or m.created_at)}
        (docs[m.activity_id] if m.activity_id in ids else loose).append(row)
    out = []
    for a in acts:
        used = round(sum(d["amount"] for d in docs[a.id]), 2)
        bud = float(a.budget or 0)
        pct = round(used / bud * 100) if bud else 0
        level = "over" if bud and used > bud else "near" if pct >= 80 else "ok"
        out.append({"a": a, "docs": docs[a.id], "used": used, "left": round(bud - used, 2), "pct": pct, "level": level})
    if loose:
        out.append({"a": None, "docs": loose, "used": round(sum(d["amount"] for d in loose), 2), "left": 0})
    return out
