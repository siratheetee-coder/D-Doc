# -*- coding: utf-8 -*-
"""
lunch_finance.py - เชื่อมเงินอาหารกลางวันกับทะเบียนคุมเงิน (ตามที่เจ้าของกำหนด)

  - การเงินลงรับเงินอาหารกลางวันก่อนเสมอ ในบัญชีแยกของอาหารกลางวัน (ไม่ต้องเลือกหมวด)
  - โครงการอาหารกลางวันเลือกบัญชีนั้น (LunchProgram.finance_account_id)
  - หน้าอาหารกลางวันดึงรายการรับจากบัญชีนั้นมาแสดงเอง ไม่ต้องลงซ้ำ
    ใช้กับโครงการปีการศึกษาไหน: ตามวันที่รับ (16 พ.ค. ถึง 15 พ.ค. ปีถัดไป) เปลี่ยนรายรายการได้ (FinanceTxn.lunch_year)
  - รายการจ่ายจากรอบ/งวดยังคัดลอกไปการเงินเหมือนเดิม แต่ลงบัญชีที่เลือก (ไม่สร้างบัญชี "อาหารกลางวัน" อีก)
  - รายการที่หน้าอาหารกลางวันคัดลอกไป (LunchLedger.finance_txn_id) แก้/ลบที่หน้าอาหารกลางวันเท่านั้น
"""
from datetime import date, datetime

from app.models import FinanceAccount, FinanceTxn, LunchLedger

AUTO_ACCOUNT_NAME = "อาหารกลางวัน"          # บัญชีที่ระบบเคยสร้างให้เอง (ก่อนมีการเลือกบัญชี)
_MS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
DUP_DAYS = 7


def lunch_year_of(d) -> int:
    """ปีการศึกษา (พ.ศ.) ของวันที่รับเงิน: 16 พ.ค. ถึง 15 พ.ค. ปีถัดไป"""
    if isinstance(d, datetime):
        d = d.date()
    d = d or date.today()
    return d.year + 543 if (d.month, d.day) >= (5, 16) else d.year + 542


def year_range_text(year: int) -> str:
    return f"16 พ.ค. {year} ถึง 15 พ.ค. {year + 1}"


def txn_year(t) -> int:
    return t.lunch_year or lunch_year_of(t.date)


def mirror_map(db) -> dict:
    """{finance_txn_id: program_id} ของรายการที่หน้าอาหารกลางวันคัดลอกไป (แก้ที่หน้าอาหารกลางวันเท่านั้น)"""
    return {tid: pid for tid, pid in db.query(LunchLedger.finance_txn_id, LunchLedger.program_id)
            .filter(LunchLedger.finance_txn_id.isnot(None))}


def account_incomes(db, prog, mirrors=None) -> list:
    """รายการรับจากบัญชีที่เลือก ที่ใช้กับโครงการปีนี้ (ไม่รวมรายการที่หน้าอาหารกลางวันคัดลอกไปเอง)"""
    if not prog or not prog.finance_account_id:
        return []
    mirrors = mirror_map(db) if mirrors is None else mirrors
    rows = (db.query(FinanceTxn).filter(FinanceTxn.account_id == prog.finance_account_id,
                                         FinanceTxn.kind == "in")
            .order_by(FinanceTxn.date, FinanceTxn.id).all())
    return [t for t in rows if t.id not in mirrors and txn_year(t) == prog.year]


def totals(db, prog) -> dict:
    rin = sum(l.amount or 0 for l in prog.ledger if l.kind == "in")
    rout = sum(l.amount or 0 for l in prog.ledger if l.kind == "out")
    rin += sum(t.amount or 0 for t in account_incomes(db, prog))
    return {"in": rin, "out": rout, "balance": rin - rout}


def duplicates(entries) -> list:
    """คู่รายการรับที่อาจลงซ้ำ: ยอดเท่ากัน วันที่ห่างกันไม่เกิน 7 วัน
    entries = [(label, date, amount)] คืน [(a, b)]"""
    out = []
    items = [e for e in entries if e[1] and (e[2] or 0) > 0]
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            da = a[1].date() if isinstance(a[1], datetime) else a[1]
            db_ = b[1].date() if isinstance(b[1], datetime) else b[1]
            if round(a[2], 2) == round(b[2], 2) and abs((da - db_).days) <= DUP_DAYS:
                out.append((a, b))
    return out


def default_account(db):
    """บัญชีที่ชื่อมีคำว่า อาหารกลางวัน · บัญชีที่โรงเรียนสร้างเองมาก่อนบัญชีที่ระบบเคยสร้างให้"""
    accs = [a for a in db.query(FinanceAccount).order_by(FinanceAccount.id) if "อาหารกลางวัน" in (a.name or "")]
    own = [a for a in accs if (a.name or "").strip() != AUTO_ACCOUNT_NAME]
    return (own or accs or [None])[0]


def move_preview(db, prog, account_id) -> dict:
    """รายการที่หน้าอาหารกลางวันโครงการนี้เคยคัดลอกไปอยู่บัญชีอื่น ต้องย้ายไปบัญชีใหม่"""
    ids = [l.finance_txn_id for l in prog.ledger if l.finance_txn_id]
    rows = (db.query(FinanceTxn).filter(FinanceTxn.id.in_(ids), FinanceTxn.account_id != account_id).all()
            if ids and account_id else [])
    return dict(rows=rows, n=len(rows),
                sum_in=round(sum(t.amount or 0 for t in rows if t.kind == "in"), 2),
                sum_out=round(sum(t.amount or 0 for t in rows if t.kind == "out"), 2),
                from_names=sorted({t.account.name for t in rows if t.account}))


def move(db, prog, account_id) -> int:
    pv = move_preview(db, prog, account_id)
    for t in pv["rows"]:
        t.account_id = account_id
    prog.finance_account_id = account_id
    db.flush()
    return pv["n"]


def thai_short(d) -> str:
    if not d:
        return "-"
    return f"{d.day} {_MS[d.month]} {d.year + 543}"
