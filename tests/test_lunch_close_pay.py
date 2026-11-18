"""ปิดรอบแม่ครัว: วันที่จ่ายจริงแยกจากวันสิ้นสุดรอบ + ใช้รายการจ่ายเดิมในการเงิน ไม่ลงซ้ำ"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401
from tests.test_lunch_loan import _db, _setup


def test_paid_date_separate(env):
    from app.models import LunchLedger, FinanceTxn, LunchHireRound
    rid, _ = _setup()
    r = env.get(f"/lunch/round/{rid}/plan")
    assert "ยืนยันการจ่ายและปิดรอบ" in r.text
    env.post(f"/lunch/round/{rid}/status", data={"status": "จ่ายแล้ว", "paid_date": "20/06/2570"})
    with _db() as s:
        led = s.query(LunchLedger).filter_by(round_id=rid).one()
        assert led.date == datetime(2027, 6, 20)
        assert s.get(FinanceTxn, led.finance_txn_id).date == datetime(2027, 6, 20)
        rnd = s.get(LunchHireRound, rid); rnd.end_date = datetime(2027, 6, 15); s.commit()
        from app.routers.lunch import _sync_round_ledger
        _sync_round_ledger(s, rnd); s.commit()
        assert s.query(LunchLedger).filter_by(round_id=rid).one().date == datetime(2027, 6, 20)
    env.post(f"/lunch/round/{rid}/paid-date", data={"paid_date": "22/06/2570"})
    with _db() as s:
        assert s.query(LunchLedger).filter_by(round_id=rid).one().date == datetime(2027, 6, 22)
    env.post(f"/lunch/round/{rid}/status", data={"status": "จ้างแล้ว"})
    with _db() as s:
        assert not s.query(LunchLedger).filter_by(round_id=rid).all()


def test_link_existing_no_double(env):
    from app.models import LunchLedger, FinanceTxn, LunchProgram
    from app.routers.lunch import _ensure_lunch_account
    rid, pid = _setup()
    with _db() as s:
        p = s.get(LunchProgram, pid)
        acc = p.finance_account_id or _ensure_lunch_account(s).id
        t = FinanceTxn(account_id=acc, fiscal_year=2570, date=datetime(2027, 6, 18), kind="out",
                       amount=4700, note="จ่ายค่าแม่ครัวจากบันทึกขอเบิก")
        s.add(t); s.commit(); tid = t.id
    r = env.get(f"/lunch/round/{rid}/plan")
    assert "พบรายการจ่ายยอดเท่ากัน" in r.text
    env.post(f"/lunch/round/{rid}/status", data={"status": "จ่ายแล้ว", "link_txn": str(tid)})
    with _db() as s:
        assert s.query(LunchLedger).filter_by(round_id=rid).one().finance_txn_id == tid
        assert s.query(FinanceTxn).filter_by(account_id=acc, kind="out").count() == 1
    env.post(f"/lunch/round/{rid}/status", data={"status": "จ้างแล้ว"})
    with _db() as s:
        assert s.get(FinanceTxn, tid) is not None


def test_disburse_warns_closed_round(env):
    from app.models import DisburseMemo
    rid, _ = _setup()
    env.post(f"/lunch/round/{rid}/status", data={"status": "จ่ายแล้ว", "paid_date": "20/06/2570"})
    with _db() as s:
        m = DisburseMemo(fiscal_year=2570, subject="ค่าจ้างแม่ครัว", amount=4700, date=datetime(2027, 6, 21))
        s.add(m); s.commit(); mid = m.id
    r = env.get(f"/finance/disburse/{mid}")
    assert "ระวังจ่ายซ้ำ" in r.text and f"/lunch/round/{rid}/plan" in r.text


def test_missing_box_and_flow(env):
    rid, _ = _setup()
    t = env.get(f"/lunch/round/{rid}/plan").text
    assert "ข้อมูลที่ยังไม่ครบ" in t and "ยังไม่ได้แต่งตั้งกรรมการตรวจรับพัสดุ" in t
    assert "ทำเรื่องและจ่ายเงินครั้งเดียว" not in t
