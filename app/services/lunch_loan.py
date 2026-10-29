# -*- coding: utf-8 -*-
"""
lunch_loan.py - ยืมเงินซื้อวัตถุดิบ (โหมดจ้างแม่ครัว / ซื้อวัตถุดิบเอง) เชื่อมทะเบียนคุมเงินยืมของการเงิน

คู่มือการดำเนินงานโครงการอาหารกลางวัน พ.ศ. 2569 (สพฐ.) ภาคผนวก ค หน้า 65-68:
  ขั้นตอนการยืม = บันทึกขออนุมัติยืม + สัญญาการยืมเงิน + แบบประมาณการ
  ขั้นตอนการส่งใช้ = ใบจัดซื้อ/ใบรับรองการจ่ายเงิน (ใบสำคัญ) + เงินสดเหลือจ่าย (ถ้ามี)
  "กรณีจ้างบุคคลภายนอกมาประกอบอาหารให้หักประมาณการค่าจ้างแม่ครัวไว้ไม่ต้องยืม" (หน้า 66)

กรอกที่หน้ารอบ ระบบสร้าง MoneyLoan ในทะเบียนคุมเงินยืมให้เอง (ไม่ต้องไปหน้าการเงิน)
  ได้รับเงินแล้ว -> บัญชีอาหารกลางวันลงจ่ายเงินยืม (รายการคู่ในการเงินผูก loan_id)
  ส่งใช้ -> ใบสำคัญ = ค่าวัตถุดิบ + ค่าเชื้อเพลิง (ไม่เกินยอดยืม) + เงินสดเหลือคืน (ลงรับคืน ผูก loan_return_id)
  ปิดรอบ ("จ่ายแล้ว") -> ลงเฉพาะส่วนที่เงินยืมไม่ได้จ่าย (ค่าจ้างแม่ครัว + ส่วนที่ใช้เกินยอดยืม) ไม่นับค่าวัตถุดิบซ้ำ
"""
import json
from datetime import timedelta

WITHIN_DAYS = 30          # ส่งใช้ภายใน 30 วันนับแต่ได้รับเงิน (เท่ากับสัญญายืมในชุดเอกสารอาหารกลางวันเดิม)
POSITION = "เจ้าหน้าที่โครงการอาหารกลางวัน"


def _r2(x) -> float:
    return round(float(x or 0), 2)


def loan_of(rnd):
    """สัญญายืมของรอบ (None ถ้าไม่มี หรือถูกลบจากหน้าการเงินไปแล้ว)"""
    return rnd.loan if getattr(rnd, "loan_id", None) else None


def default_amount(rnd) -> float:
    """ยอดยืมตั้งต้น = นักเรียน x วัน x อัตรา หักค่าจ้างแม่ครัว (ค่าจ้างไม่ต้องยืม)"""
    prog = rnd.program
    full = (float(getattr(prog, "total_students", 0) or 0) * float(getattr(prog, "rate_per_head", 0) or 0)
            * float(getattr(rnd, "days", 0) or 0))
    wage = float(getattr(rnd, "cook_wage", 0) or 0) if getattr(prog, "operate_mode", "") == "person" else 0.0
    return _r2(max(0.0, full - wage))


def spent(rnd) -> float:
    """ใช้จากเงินยืมจริง = ค่าวัตถุดิบที่กรอก + ค่าเชื้อเพลิงของรอบ"""
    from app.routers.lunch import round_ingredient_total
    return _r2(round_ingredient_total(rnd) + float(rnd.fuel_cost or 0))


def state(rnd) -> dict:
    loan = loan_of(rnd)
    used = spent(rnd)
    if not loan:
        return {"loan": None, "amount": default_amount(rnd), "spent": used, "received": False,
                "repaid": False, "vouchers": 0.0, "cash": 0.0, "over": 0.0, "covered": 0.0, "stale": False,
                "overdue": False}
    amount = _r2(loan.amount)
    vouchers = _r2(sum(r.amount or 0 for r in loan.returns if r.kind == "ใบสำคัญ"))
    cash = _r2(sum(r.amount or 0 for r in loan.returns if r.kind == "เงินสด"))
    repaid = bool(loan.returns)
    received = bool(loan.receive_date)
    if not received:
        covered = 0.0
    elif repaid:
        covered = _r2(amount - cash)
    else:
        covered = min(amount, used)
    from datetime import datetime
    return {"loan": loan, "amount": amount, "spent": used, "received": received, "repaid": repaid,
            "vouchers": vouchers, "cash": cash, "over": _r2(max(0.0, used - amount)),
            "covered": _r2(covered),
            "overdue": bool(loan.due_date and not repaid and loan.due_date < datetime.now()),
            # ค่าวัตถุดิบเปลี่ยนหลังบันทึกส่งใช้ -> ต้องกดส่งใช้ใหม่
            "stale": repaid and abs(vouchers - min(used, amount)) > 0.005}


def close_info(rnd):
    """ยอดที่ลงบัญชีตอนปิดรอบ = ค่าใช้จ่ายทั้งรอบ หักส่วนที่จ่ายจากเงินยืมไปแล้ว คืน (ยอด, คำอธิบาย)"""
    from app.routers.lunch import round_spend
    loan = loan_of(rnd)
    amount = _r2(round_spend(rnd) - (state(rnd)["covered"] if loan else 0.0))
    wage = _r2(rnd.cook_wage) if rnd.program.operate_mode == "person" else 0.0
    rest = _r2(amount - wage)
    parts = []
    if wage > 0:
        parts.append(f"ค่าจ้างแม่ครัว {wage:,.2f}")
    if rest > 0:
        parts.append(("วัตถุดิบส่วนที่เงินยืมไม่พอ " if loan else "ค่าวัตถุดิบและค่าเชื้อเพลิง ") + f"{rest:,.2f}")
    return amount, " + ".join(parts)


def _docnos_set(rnd, ent: dict) -> None:
    """เก็บเลขที่/วันที่สัญญายืมไว้ใน doc_nos["loan"] ให้เอกสารชุดเดิมพิมพ์ได้เหมือนเดิม"""
    try:
        data = json.loads(rnd.doc_nos or "{}") or {}
    except Exception:
        data = {}
    old = data.get("loan") or {}
    new = {k: v for k, v in ent.items() if v}
    if old.get("present_date"):
        new["present_date"] = old["present_date"]
    if new:
        data["loan"] = new
    else:
        data.pop("loan", None)
    rnd.doc_nos = json.dumps(data, ensure_ascii=False)


def _ledgers(db, loan_id):
    from app.models import LunchLedger
    return db.query(LunchLedger).filter_by(loan_id=loan_id).all()


def _post(db, rnd, *, kind, amount, date, detail, ref, loan_id, return_id=None):
    from app.models import LunchLedger
    from app.routers.lunch import _mirror_finance
    led = LunchLedger(program_id=rnd.program_id, kind=kind, amount=_r2(amount), date=date, detail=detail,
                      ref=ref, loan_id=loan_id, loan_return_id=return_id)
    db.add(led)
    db.flush()
    _mirror_finance(db, led)
    from app.models import FinanceTxn
    txn = db.get(FinanceTxn, led.finance_txn_id)
    txn.loan_id = loan_id                       # ทะเบียนคุมเงินยืมเห็นว่าจ่าย/รับคืนเงินจริงแล้ว
    txn.loan_return_id = return_id
    txn.category = "รับคืนเงินยืม" if return_id else "จ่ายเงินยืม"
    return led


def _clear_returns(db, loan) -> None:
    from app.routers.lunch import _delete_ledger
    for led in _ledgers(db, loan.id):
        if led.loan_return_id:
            _delete_ledger(db, led)
    db.flush()
    for r in list(loan.returns):
        db.delete(r)
    db.flush()
    db.refresh(loan)


def _sync_payout(db, rnd, loan) -> None:
    """ได้รับเงินแล้ว = ลงจ่ายเงินยืมจากบัญชีอาหารกลางวัน 1 รายการ (ยังไม่ได้รับ = ไม่มีรายการ)"""
    from app.routers.lunch import _delete_ledger, _mirror_finance
    pay = [l for l in _ledgers(db, loan.id) if not l.loan_return_id]
    if loan.receive_date and (loan.amount or 0) > 0:
        detail = f"จ่ายเงินยืมซื้อวัตถุดิบ รอบที่ {rnd.seq} ({loan.borrower or '-'})"
        if pay:
            led = pay[0]
            led.amount, led.date, led.detail, led.ref = _r2(loan.amount), loan.receive_date, detail, loan.contract_no or ""
            _mirror_finance(db, led)
        else:
            _post(db, rnd, kind="out", amount=loan.amount, date=loan.receive_date, detail=detail,
                  ref=loan.contract_no or "", loan_id=loan.id)
        pay = pay[1:]
    for led in pay:
        _delete_ledger(db, led)


def save(db, rnd, school, *, contract_no, date, receive_date, amount, borrower):
    """สร้าง/แก้สัญญายืมเงินของรอบ แล้วซิงก์บัญชี คืน (loan, error)"""
    from app.models import MoneyLoan
    from app.thai_utils import current_fiscal_year
    from app.services.lunch_ingredient_doc import _fund
    amount = _r2(amount)
    if amount <= 0:
        return None, "ใส่ยอดเงินยืมมากกว่า 0 บาท"
    loan = loan_of(rnd)
    if loan and loan.returns and abs(amount - _r2(loan.amount)) > 0.005:
        return loan, "บันทึกส่งใช้ไปแล้ว ยกเลิกการส่งใช้ก่อนแก้ยอดเงินยืม"
    if not loan:
        loan = MoneyLoan(fiscal_year=current_fiscal_year(date or receive_date), within_days=WITHIN_DAYS)
        db.add(loan)
    prog = rnd.program
    loan.contract_no = (contract_no or "").strip()
    loan.date, loan.receive_date = date, receive_date
    if date or receive_date:
        loan.fiscal_year = current_fiscal_year(date or receive_date)
    base = receive_date or date
    loan.due_date = base + timedelta(days=loan.within_days or WITHIN_DAYS) if base else None
    loan.borrower = (borrower or "").strip()
    loan.position = POSITION
    loan.submit_to = f"ผู้อำนวยการ{(getattr(school, 'name', '') or '').strip()}"
    loan.fund_from = f"เงินอุดหนุนอาหารกลางวันรับจาก{_fund(prog)}"
    loan.purpose = f"ซื้อวัตถุดิบประกอบอาหารกลางวันนักเรียน รอบที่ {rnd.seq} ปีการศึกษา {prog.year}"
    loan.items = json.dumps([{"name": loan.purpose, "amount": amount}], ensure_ascii=False)
    loan.amount = amount
    loan.account_id = prog.finance_account_id
    loan.note = f"สร้างจากงานอาหารกลางวัน รอบที่ {rnd.seq}"
    db.flush()
    rnd.loan_id = loan.id
    _docnos_set(rnd, {"no": loan.contract_no, "date": date.isoformat() if date else "",
                      "receive_date": receive_date.isoformat() if receive_date else ""})
    _sync_payout(db, rnd, loan)
    return loan, ""


def repay(db, rnd, date):
    """บันทึกส่งใช้: ใบสำคัญ = ที่ใช้จริง (ไม่เกินยอดยืม) เงินสดเหลือคืน = ยอดยืม - ใบสำคัญ"""
    from app.models import LoanReturn
    loan = loan_of(rnd)
    if not loan:
        return "ยังไม่มีสัญญายืมเงิน"
    if not loan.receive_date:
        return "ใส่วันที่ได้รับเงินยืมก่อน"
    if not date:
        return "ใส่วันที่ส่งใช้"
    _clear_returns(db, loan)
    used = spent(rnd)
    vouchers = min(used, _r2(loan.amount))
    cash = _r2(_r2(loan.amount) - vouchers)
    if vouchers > 0:
        db.add(LoanReturn(loan_id=loan.id, date=date, kind="ใบสำคัญ", amount=vouchers,
                          note="ค่าวัตถุดิบและค่าเชื้อเพลิง (อาหารกลางวัน)"))
    if cash > 0:
        ret = LoanReturn(loan_id=loan.id, date=date, kind="เงินสด", amount=cash, note="เงินสดเหลือจ่าย")
        db.add(ret)
        db.flush()
        _post(db, rnd, kind="in", amount=cash, date=date, ref=loan.contract_no or "",
              detail=f"รับคืนเงินยืมเหลือจ่าย รอบที่ {rnd.seq} ({loan.borrower or '-'})",
              loan_id=loan.id, return_id=ret.id)
    db.flush()
    db.refresh(loan)
    return ""


def undo_repay(db, rnd) -> None:
    loan = loan_of(rnd)
    if loan:
        _clear_returns(db, loan)


def remove(db, rnd) -> str:
    """ยกเลิกสัญญายืมของรอบ (ลบรายการเงินที่ระบบลงให้ด้วย)"""
    from app.routers.lunch import _delete_ledger
    loan = loan_of(rnd)
    if loan:
        _clear_returns(db, loan)
        for led in _ledgers(db, loan.id):
            _delete_ledger(db, led)
        db.flush()
        db.delete(loan)
    rnd.loan_id = None
    _docnos_set(rnd, {})
    return ""
