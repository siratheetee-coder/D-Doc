"""เลข บค. (ใบรับรองแทนใบเสร็จ) รายวันของรอบซื้อวัตถุดิบ อาหารกลางวัน

ใช้ลำดับเดียวกับทะเบียนคุมเงิน (services/docno.py) และจองเลขโดยบันทึกลงทะเบียนใบเสร็จ/ใบสำคัญ (Receipt)
ผูกกับรอบ+วัน ด้วย Receipt.note = "lunch-bk:<round id>:<YYYY-MM-DD>"
รันทีละวัน: กดในวันที่ซื้อจริง ลำดับเลขจึงสลับกับงานการเงินอื่นตามเวลาจริง
"""
import re
from datetime import datetime

from app.services import docno
from app.thai_utils import current_fiscal_year

PREFIX = "บค."


def _tag(rnd, d):
    return f"lunch-bk:{rnd.id}:{d.isoformat()}"


def _days(rnd):
    from app.services.lunch_ingredient_doc import _ings_by_day
    return [(d, ings) for d, ings in _ings_by_day(rnd) if d]


def numbers(db, rnd) -> dict:
    """{date: Receipt} ของรอบนี้"""
    from app.models import Receipt
    out = {}
    for r in db.query(Receipt).filter(Receipt.note.like(f"lunch-bk:{rnd.id}:%")):
        try:
            out[datetime.fromisoformat(r.note.split(":", 2)[2]).date()] = r
        except ValueError:
            pass
    return out


def day_rows(db, rnd):
    nums = numbers(db, rnd)
    return [{"date": d, "iso": d.isoformat(), "no": (nums[d].receipt_no if d in nums else ""),
             "total": sum((g.quantity or 0) * (g.unit_price or 0) for g in ings)}
            for d, ings in _days(rnd)]


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def duplicate(db, no, skip_id=None) -> bool:
    from app.models import FinanceTxn, Receipt
    n = _norm(no)
    if not n:
        return False
    for (ref,) in db.query(FinanceTxn.ref).filter(FinanceTxn.ref.like("%/%")):
        if _norm(ref) == n:
            return True
    for rid, ref in db.query(Receipt.id, Receipt.receipt_no):
        if rid != skip_id and _norm(ref) == n:
            return True
    return False


def _upsert(db, rnd, d, no, total):
    from app.models import Receipt
    from app.services.lunch_ingredient_doc import _borrower
    from app.routers.pages import get_school
    cur = numbers(db, rnd).get(d)
    dt = datetime(d.year, d.month, d.day)
    if not cur:
        cur = Receipt(note=_tag(rnd, d))
        db.add(cur)
    cur.fiscal_year = current_fiscal_year(dt)
    cur.receipt_no, cur.date, cur.kind = no, dt, "จ่าย"
    cur.party = _borrower(get_school(db), rnd.program)[0] or ""
    cur.amount = total
    return cur


def run_day(db, rnd, d):
    """จองเลขถัดไปให้วัน d (ถ้ามีเลขแล้วไม่เปลี่ยน) คืนเลข"""
    have = numbers(db, rnd).get(d)
    if have and have.receipt_no:
        return have.receipt_no
    total = next((r["total"] for r in day_rows(db, rnd) if r["date"] == d), 0.0)
    fy = current_fiscal_year(datetime(d.year, d.month, d.day))
    no = docno.next_ref(db, PREFIX, fy)
    _upsert(db, rnd, d, no, total)
    db.commit()
    return no


def run_missing(db, rnd):
    n = 0
    for r in day_rows(db, rnd):
        if not r["no"]:
            run_day(db, rnd, r["date"]); n += 1
    return n


def set_manual(db, rnd, d, no):
    """พิมพ์เลขเอง คืนข้อความเตือน ("" = บันทึกแล้ว)"""
    no = (no or "").strip()
    cur = numbers(db, rnd).get(d)
    if not no:
        if cur:
            db.delete(cur); db.commit()
        return ""
    if duplicate(db, no, cur.id if cur else None):
        return f"เลข {no} ถูกใช้ไปแล้วในทะเบียน"
    total = next((r["total"] for r in day_rows(db, rnd) if r["date"] == d), 0.0)
    _upsert(db, rnd, d, no, total)
    db.commit()
    return ""


def no_for(rnd, d) -> str:
    """เลขของวัน d สำหรับเติมในเอกสาร ("" ถ้ายังไม่มี)"""
    from sqlalchemy.orm import object_session
    db = object_session(rnd)
    if not db or not d:
        return ""
    r = numbers(db, rnd).get(d if not isinstance(d, datetime) else d.date())
    return r.receipt_no if r else ""
