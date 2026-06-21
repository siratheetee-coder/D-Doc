# -*- coding: utf-8 -*-
"""
budget.py — คำนวณงบโครงการ / ใช้จริง / คงเหลือ (โมดูลแผนปฏิบัติการ)

- งบปัจจุบัน = ยอดของการปรับงบครั้งล่าสุด (ProjectBudgetRevision) ถ้าไม่มี = Project.budget
- ใช้จริง = Σ เรื่องจัดซื้อที่ผูกโครงการ + Σ ขอเบิกจ่ายที่ผูกโครงการ (เฉพาะที่ไม่ได้อ้างเรื่องจัดซื้อ กันนับซ้ำ)
"""
from app.thai_utils import current_fiscal_year, current_academic_year


def current_plan_year(school) -> int:
    """ปีของแผนปัจจุบัน ตามโหมดที่ตั้งไว้ของโรงเรียน"""
    mode = getattr(school, "project_year_mode", "budget") or "budget"
    return current_academic_year() if mode == "academic" else current_fiscal_year()


def plan_year_label(school) -> str:
    mode = getattr(school, "project_year_mode", "budget") or "budget"
    return "ปีการศึกษา" if mode == "academic" else "ปีงบประมาณ"


def project_budget(project) -> float:
    """งบปัจจุบันของโครงการ = ยอดของการปรับงบครั้งล่าสุด มิฉะนั้นใช้ budget ตั้งต้น"""
    revs = getattr(project, "revisions", None) or []
    if revs:
        last = max(revs, key=lambda r: (r.seq or 0))
        return float(last.amount or 0)
    return float(project.budget or 0)


def project_spent(project) -> float:
    """ยอดใช้จริงของโครงการ = เรื่องจัดซื้อที่ผูก + ขอเบิกจ่ายเดี่ยวที่ผูก (กันนับซ้ำเรื่องที่เบิกจากจัดซื้อ)"""
    from app.models import Procurement, DisburseMemo
    from sqlalchemy.orm import object_session
    db = object_session(project)
    if db is None:
        return 0.0
    procs = (db.query(Procurement)
             .filter(Procurement.project_id == project.id).all())
    spent = sum(p.total_amount or 0 for p in procs)
    disb = (db.query(DisburseMemo)
            .filter(DisburseMemo.project_id == project.id,
                    DisburseMemo.procurement_id.is_(None)).all())
    spent += sum(d.amount or 0 for d in disb)
    return round(spent, 2)


def project_remaining(project) -> float:
    return round(project_budget(project) - project_spent(project), 2)
