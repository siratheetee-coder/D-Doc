# -*- coding: utf-8 -*-
"""
disburse_split.py - บันทึกขอเบิก 1 ฉบับ แยกจ่ายจากหลายบัญชี/หมวด
เช่น เรื่องเดียว 30,000 หักเงินอุดหนุน 20,000 และเงินรายได้สถานศึกษา 10,000

กติกา
  - ไม่แยก = ไม่มีแถว DisburseSplit ทำงานแบบเดิมทุกอย่าง (memo.account_id / item_id)
  - แยก = 2 แถวขึ้นไป ยอดรวมต้องเท่ายอดขอเบิก memo.account_id/item_id เก็บแถวแรกไว้ให้โค้ดเดิมอ่านได้
  - ลงจ่าย = FinanceTxn 1 รายการต่อแถว (disburse_id เดียวกัน) ทะเบียนแต่ละบัญชีเห็นเฉพาะส่วนของตัวเอง
    ยอดโครงการรวมจากรายการเงิน จึงนับ 30,000 ไม่ซ้ำ
  - ภาษี ณ ที่จ่ายและค่าปรับ: หนังสือรับรองใบเดียวตามยอดรวม แบ่งลงแต่ละบัญชีตามสัดส่วน
    เศษสตางค์ยกให้แถวสุดท้าย ผลรวมจึงเท่ายอดเดิมพอดี (เจ้าของเลือก 2026-10-31)
  - วันจ่ายวันเดียวทั้งฉบับ ใช้วันที่ของบันทึก
"""
from datetime import datetime

from app.models import AccountItem, CheckPayment, DisburseSplit, FinanceAccount, FinanceTxn, Receipt


def parse(accounts, items, amounts) -> list:
    """แถวจากฟอร์ม ข้ามแถวที่ว่างทั้งแถว"""
    rows = []
    for acc, item, amt in zip(accounts or [], items or [], amounts or []):
        acc, item, amt = (acc or "").strip(), (item or "").strip(), (amt or "").replace(",", "").strip()
        if not acc and not amt:
            continue
        try:
            value = round(float(amt or 0), 2)
        except ValueError:
            value = 0.0
        rows.append({"account_id": int(acc) if acc.isdigit() else None,
                     "item_id": int(item) if item.isdigit() else None, "amount": value})
    return rows


def _check(db, memo, row):
    if not row["account_id"] or not db.get(FinanceAccount, row["account_id"]):
        raise ValueError("เลือกบัญชีให้ครบทุกแถว")
    if row["amount"] <= 0:
        raise ValueError("จำนวนเงินแต่ละแถวต้องมากกว่า 0")
    if row["item_id"]:
        item = db.get(AccountItem, row["item_id"])
        if not item or (item.account_id, item.fiscal_year) != (row["account_id"], memo.fiscal_year):
            raise ValueError("หมวดไม่ตรงกับบัญชีหรือปีงบประมาณ")


def apply(db, memo, rows) -> None:
    """ตั้งการแยกแหล่งเงินของบันทึก (แถวน้อยกว่า 2 = ไม่แยก ใช้บัญชีเดียวตามเดิม)"""
    if len(rows) < 2:
        memo.splits = []
        if rows:
            memo.account_id, memo.item_id = rows[0]["account_id"], rows[0]["item_id"]
        return
    for r in rows:
        _check(db, memo, r)
    keys = [(r["account_id"], r["item_id"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("มีบัญชีและหมวดซ้ำกัน รวมเป็นแถวเดียว")
    total = round(sum(r["amount"] for r in rows), 2)
    if total != round(float(memo.amount or 0), 2):
        raise ValueError(f"ยอดแยกรวม {total:,.2f} บาท ไม่เท่ายอดขอเบิก {float(memo.amount or 0):,.2f} บาท")
    memo.splits = [DisburseSplit(seq=i, account_id=r["account_id"], item_id=r["item_id"], amount=r["amount"])
                   for i, r in enumerate(rows, 1)]
    memo.account_id, memo.item_id = rows[0]["account_id"], rows[0]["item_id"]


def _share(total, amounts) -> list:
    """แบ่งยอดตามสัดส่วน เศษยกให้แถวสุดท้าย"""
    total = round(float(total or 0), 2)
    whole = sum(amounts)
    if not whole:
        return [0.0] * len(amounts)
    out = [round(total * a / whole, 2) for a in amounts[:-1]]
    out.append(round(total - sum(out), 2))
    return out


def is_split(memo) -> bool:
    return len(memo.splits or []) >= 2


def rows_of(db, memo) -> list:
    """แหล่งเงินของบันทึก [{account_id, item_id, amount, name, wht, fine, net}] ไม่แยก = แถวเดียว"""
    src = list(memo.splits or [])
    base = ([(s.account_id, s.item_id, float(s.amount or 0)) for s in src] if len(src) >= 2
            else [(memo.account_id, memo.item_id, float(memo.amount or 0))])
    amounts = [b[2] for b in base]
    whts, fines = _share(memo.wht, amounts), _share(memo.fine, amounts)
    out = []
    for (acc_id, item_id, amt), wht, fine in zip(base, whts, fines):
        acc = db.get(FinanceAccount, acc_id) if acc_id else None
        item = db.get(AccountItem, item_id) if item_id else None
        name = (acc.name if acc else "") + (f" ({item.name})" if item else "")
        out.append({"account_id": acc_id, "item_id": item_id, "amount": amt, "name": name,
                    "account_name": acc.name if acc else "", "wht": wht, "fine": fine,
                    "net": round(amt - wht - fine, 2)})
    return out


def source_text(db, memo) -> str:
    """ชื่อเงินสั้น ๆ สำหรับเอกสาร/ทะเบียน เช่น เงินอุดหนุน 20,000.00 และเงินรายได้ 10,000.00"""
    if (memo.budget_source or "").strip():
        return memo.budget_source.strip()
    if is_split(memo):
        return " และ ".join(f"{r['account_name']} {r['amount']:,.2f} บาท" for r in rows_of(db, memo))
    return ""


def txn_note(memo, n=None, total=None) -> str:
    from app.services.finance_txn_text import payment_note
    return payment_note(memo, n, total)


def post(db, memo) -> None:
    """ลงจ่ายเข้าทะเบียนคุมเงิน 1 รายการต่อแหล่งเงิน"""
    rows = rows_of(db, memo)
    many = len(rows) > 1
    for i, r in enumerate(rows, 1):
        db.add(FinanceTxn(account_id=r["account_id"], fiscal_year=memo.fiscal_year, kind="out", item_id=r["item_id"],
                          amount=r["amount"], date=memo.date or datetime.now(), category="เบิกจ่าย",
                          ref=memo.memo_no or "", note=txn_note(memo, i if many else None, len(rows)),
                          disburse_id=memo.id))


def _tied(db, txn) -> bool:
    return bool(db.query(Receipt).filter_by(txn_id=txn.id).first()
                or db.query(CheckPayment).filter_by(txn_id=txn.id).first())


def sync(db, memo, txns) -> None:
    """แก้บันทึกที่ลงจ่ายแล้วและแยกหลายบัญชี ให้รายการเงินตรงกับแหล่งเงินล่าสุด
    รายการที่เชื่อมใบเสร็จหรือเช็คอยู่ ถ้าบัญชี/ยอด/วันที่เปลี่ยนจะไม่ยอม เหมือนกรณีบัญชีเดียว"""
    from app.services.receipt_money import release_for_deleted_txn
    txns = sorted(txns, key=lambda t: t.id)
    if any(t.linked_existing for t in txns):
        raise ValueError("รายการนี้ใช้ยอดจ่ายเดิม หากต้องการแยกหลายบัญชี ให้ยกเลิกการเชื่อมก่อน")
    rows = rows_of(db, memo)
    for t, r in zip(txns, rows):
        same = (t.account_id == r["account_id"] and round(t.amount or 0, 2) == round(r["amount"], 2)
                and not (memo.date and (not t.date or memo.date.date() != t.date.date())))
        if not same and _tied(db, t):
            raise ValueError("รายการจ่ายนี้เชื่อมใบเสร็จหรือทะเบียนเช็คอยู่ ยกเลิกการเชื่อมก่อนจึงแก้บัญชี ยอด หรือวันที่ได้")
    for t in txns[len(rows):]:
        if _tied(db, t):
            raise ValueError("รายการจ่ายนี้เชื่อมใบเสร็จหรือทะเบียนเช็คอยู่ ยกเลิกการเชื่อมก่อน")
    many = len(rows) > 1
    for i, (t, r) in enumerate(zip(txns, rows), 1):
        t.account_id, t.item_id, t.amount = r["account_id"], r["item_id"], r["amount"]
        t.date = memo.date or t.date
        t.ref = memo.memo_no or t.ref
        t.note = txn_note(memo, i if many else None, len(rows))
    for t in txns[len(rows):]:
        release_for_deleted_txn(db, t)
        db.delete(t)
    for i, r in enumerate(rows[len(txns):], len(txns) + 1):
        db.add(FinanceTxn(account_id=r["account_id"], fiscal_year=memo.fiscal_year, kind="out", item_id=r["item_id"],
                          amount=r["amount"], date=memo.date or datetime.now(), category="เบิกจ่าย",
                          ref=memo.memo_no or "", note=txn_note(memo, i if many else None, len(rows)),
                          disburse_id=memo.id))
