"""วันที่จ่ายจริงตอนปิดรอบ (แม่ครัว/ซื้อวัตถุดิบ) + กันลงจ่ายซ้ำกับรายการที่ทำในงานการเงินไว้แล้ว

- เก็บวันจ่ายที่ LunchHireRound.paid_date แก้วันสิ้นสุดรอบภายหลังวันจ่ายไม่เปลี่ยน
- ถ้าในทะเบียนคุมเงินมีรายการจ่ายยอดเท่ากันอยู่แล้ว (ทำจากบันทึกขอเบิกหรือกรอกเอง)
  ครูเลือก "ใช้รายการเดิม" ได้ ระบบผูกรายการนั้นแทนการสร้างใหม่ จดไว้ใน doc_nos["paid_link"]
  ยกเลิกปิดรอบแล้วรายการเดิมยังอยู่ (ปลดผูกอย่างเดียว ไม่ลบ)
"""
import json
from datetime import datetime, timedelta

from app.thai_utils import parse_be_date


def _nos(rnd):
    try:
        return json.loads(rnd.doc_nos or "{}") or {}
    except Exception:
        return {}


def _set_link(rnd, tid):
    d = _nos(rnd)
    if tid:
        d["paid_link"] = tid
    else:
        d.pop("paid_link", None)
    rnd.doc_nos = json.dumps(d, ensure_ascii=False)


def _acc_id(db, rnd):
    from app.routers.lunch import _ensure_lunch_account
    p = rnd.program
    return p.finance_account_id or _ensure_lunch_account(db).id


def account_name(db, rnd):
    from app.models import FinanceAccount
    a = db.get(FinanceAccount, _acc_id(db, rnd)) if db else None
    return a.name if a else ""


def paid_date(db, rnd):
    """วันจ่ายที่ลงบัญชีจริงของรอบที่ปิดแล้ว"""
    from app.models import LunchLedger
    if rnd.status != "จ่ายแล้ว" or not db:
        return None
    led = db.query(LunchLedger).filter_by(round_id=rnd.id).first()
    return (led.date if led else None) or rnd.paid_date


def candidates(db, rnd, amount):
    """รายการจ่ายในบัญชีอาหารกลางวันที่ยอดเท่ากัน และยังไม่ได้ผูกกับงานอาหารกลางวัน"""
    from app.models import FinanceTxn, LunchLedger
    if not db or not amount or amount <= 0:
        return []
    used = {t for (t,) in db.query(LunchLedger.finance_txn_id).filter(LunchLedger.finance_txn_id.isnot(None))}
    since = (rnd.start_date or datetime.now()) - timedelta(days=45)
    q = (db.query(FinanceTxn).filter(FinanceTxn.account_id == _acc_id(db, rnd), FinanceTxn.kind == "out",
                                     FinanceTxn.date >= since).order_by(FinanceTxn.date.desc()))
    return [t for t in q if t.id not in used and round(t.amount or 0, 2) == round(amount, 2)][:5]


def before_status(db, rnd, status, paid_text, link_txn):
    """เรียกก่อนเปลี่ยนสถานะรอบ"""
    from app.models import FinanceTxn, LunchLedger
    if rnd.program.operate_mode not in ("person", "ingredient"):
        return
    if status != "จ่ายแล้ว":
        rnd.paid_date = None
        return
    if rnd.status == "จ่ายแล้ว":
        return
    d = parse_be_date(paid_text or "")
    rnd.paid_date = d or rnd.paid_date
    try:
        tid = int(link_txn or 0)
    except ValueError:
        tid = 0
    if not tid:
        return
    from app.services.lunch_loan import close_info
    t = db.get(FinanceTxn, tid)
    if not t or t not in candidates(db, rnd, close_info(rnd)[0]):
        return
    rnd.paid_date = t.date
    led = db.query(LunchLedger).filter_by(round_id=rnd.id).first()
    if not led:
        led = LunchLedger(program_id=rnd.program_id, round_id=rnd.id, kind="out", amount=t.amount, date=t.date,
                          ref=t.ref or "")
        db.add(led)
    led.finance_txn_id = t.id
    _set_link(rnd, t.id)
    db.flush()


def release(db, rnd, led):
    """ยกเลิกปิดรอบ: รายการที่ผูกจากงานการเงินไม่ลบ แค่ปลดผูก"""
    tid = _nos(rnd).get("paid_link")
    if tid and led.finance_txn_id == tid:
        led.finance_txn_id = None
    if tid:
        _set_link(rnd, None)
