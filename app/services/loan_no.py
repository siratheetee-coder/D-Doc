"""เลขที่สัญญายืมเงิน: ดูเลขที่ใช้แล้วในปีงบ + เสนอเลขถัดไป (นับจาก MoneyLoan.contract_no)"""
import re


def _seq(no):
    m = re.match(r"\s*(\d+)", no or "")
    return int(m.group(1)) if m else 0


def used(db, fiscal_year):
    from app.models import MoneyLoan
    rows = db.query(MoneyLoan).filter(MoneyLoan.fiscal_year == fiscal_year).all()
    rows = [r for r in rows if (r.contract_no or "").strip()]
    return sorted(rows, key=lambda r: (_seq(r.contract_no), r.id))


def next_no(db, fiscal_year):
    top = max((_seq(r.contract_no) for r in used(db, fiscal_year)), default=0)
    return f"{top + 1}/{fiscal_year}"
