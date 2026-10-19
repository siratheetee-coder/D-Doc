# -*- coding: utf-8 -*-
"""เลขที่เอกสาร บจ. / บค. รันให้อัตโนมัติ (เช่น บจ.5/70 หรือ บจ.5/2570)

นับต่อจากเลขสูงสุดที่มีอยู่แล้วในปีงบเดียวกัน ทั้งในทะเบียนคุมเงิน (FinanceTxn.ref)
และทะเบียนใบเสร็จ/ใบสำคัญ (Receipt.receipt_no) · เลขที่พิมพ์เองไว้ก่อนก็นับด้วย จึงไม่ชนกัน
รูปท้ายปี /70 กับ /2570 ใช้ลำดับเดียวกัน
"""
import re

PREFIXES = ("บจ.", "บค.")


def _pattern(prefix: str, fiscal_year: int):
    yy = f"{fiscal_year % 100:02d}"
    return re.compile(r"^\s*" + re.escape(prefix.rstrip(".")) + r"\.?\s*(\d+)\s*/\s*(?:" + yy + "|" + str(fiscal_year) + r")\s*$")


def next_number(db, prefix: str, fiscal_year: int) -> int:
    from app.models import FinanceTxn, Receipt
    rx = _pattern(prefix, fiscal_year)
    top = 0
    # ไม่กรองตามปีงบของรายการ: ท้ายเลข (/70) บอกปีอยู่แล้ว และกันเลขชนกับรายการที่ลงปีงบผิด
    refs = [r for (r,) in db.query(FinanceTxn.ref).filter(FinanceTxn.ref.like("%/%"))]
    refs += [r for (r,) in db.query(Receipt.receipt_no).filter(Receipt.receipt_no.like("%/%"))]
    for ref in refs:
        m = rx.match(ref or "")
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def format_no(prefix: str, n: int, fiscal_year: int, yfmt: str = "2") -> str:
    year = str(fiscal_year) if yfmt == "4" else f"{fiscal_year % 100:02d}"
    return f"{prefix}{n}/{year}"


def next_ref(db, prefix: str, fiscal_year: int, yfmt: str = "2") -> str:
    """เลขถัดไป หรือ "" ถ้าไม่ใช่ บจ./บค."""
    if prefix not in PREFIXES:
        return ""
    return format_no(prefix, next_number(db, prefix, fiscal_year), fiscal_year, yfmt)
