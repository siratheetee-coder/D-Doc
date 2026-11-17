from datetime import datetime
from tests.test_subsidy import env  # noqa: F401
from tests.test_budget_request import _db


def test_bk_per_day(env):
    from app.models import LunchProgram, LunchClass, LunchHireRound, LunchIngredient, Receipt
    from app.services import lunch_bk, docno
    c = env; _, db = _db()
    p = LunchProgram(year=2569, operate_mode="person", rate_per_head=24); db.add(p); db.flush()
    db.add(LunchClass(program_id=p.id, level="ป.1", num_students=10, seq=1))
    r = LunchHireRound(program_id=p.id, seq=1, start_date=datetime(2026, 11, 3), end_date=datetime(2026, 11, 5), days=3); db.add(r)
    for d in (3, 4, 5):
        db.add(LunchIngredient(program_id=p.id, date=datetime(2026, 11, d), name="ไข่", quantity=10, unit="ฟอง", unit_price=4))
    db.commit()
    start = docno.next_number(db, "บค.", 2570)
    c.post(f"/lunch/round/{r.id}/bk", data={"action": "run", "day": "2026-11-03"})
    db.add(Receipt(fiscal_year=2570, receipt_no=f"บค.{start + 1}/70", note="other")); db.commit()
    c.post(f"/lunch/round/{r.id}/bk", data={"action": "all"})
    db.expire_all()
    nums = {d.day: x.receipt_no for d, x in lunch_bk.numbers(db, r).items()}
    assert nums == {3: f"บค.{start}/70", 4: f"บค.{start + 2}/70", 5: f"บค.{start + 3}/70"}
    # พิมพ์เลขซ้ำ ต้องเตือน
    resp = c.post(f"/lunch/round/{r.id}/bk", data={"action": "save", "day": "2026-11-05", "no": f"บค.{start + 1}/70"})
    assert "ถูกใช้ไปแล้ว" in resp.text
    page = c.get(f"/lunch/round/{r.id}/plan").text
    assert f"บค.{start}/70" in page
    from app.services.lunch_ingredient_doc import _bk_no
    assert _bk_no(r, datetime(2026, 11, 4)) == f"บค.{start + 2}/70"


def test_loan_register(env):
    from app.models import LunchProgram, LunchClass, LunchHireRound, MoneyLoan
    c = env; _, db = _db()
    p = LunchProgram(year=2569, operate_mode="person", rate_per_head=24); db.add(p); db.flush()
    db.add(LunchClass(program_id=p.id, level="ป.1", num_students=10, seq=1))
    r = LunchHireRound(program_id=p.id, seq=1, start_date=datetime(2026, 11, 3), end_date=datetime(2026, 11, 5), days=3); db.add(r)
    db.add(MoneyLoan(fiscal_year=2570, contract_no="7/2570", borrower="ครูเอ", amount=500, purpose="ไปราชการ"))
    db.commit()
    page = c.get(f"/lunch/round/{r.id}/plan").text
    assert "ดูเลขล่าสุด" in page and 'value="8/2570"' in page
    j = c.get("/docnos/peek?year=2570").json()
    assert any(i["label"] == "สัญญายืมเงิน" and i["next"] == "8/2570" for i in j["items"])
