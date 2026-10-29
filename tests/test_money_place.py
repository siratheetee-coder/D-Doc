"""บัญชีเดียวเก็บเงินได้หลายที่: ถอนจากธนาคารมาเป็นเงินสด จ่ายจากเงินสด ฝากคืน ยอดแยกที่ถูกต้องทุกหน้า"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_move_money_between_places(env):
    from app.models import FinanceAccount, FinanceTxn, AccountItem, School
    from app.services.money_place import account_by_place, item_by_place
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    with _db() as s:
        a = FinanceAccount(name="เงินอุดหนุนทดสอบ", deposit_type="bank", opening_balance=20000); s.add(a); s.flush()
        it = AccountItem(account_id=a.id, fiscal_year=fy, name="ค่าวัสดุ"); s.add(it); s.commit()
        aid, iid = a.id, it.id
    now = datetime.now()
    d = f"{now.day:02d}/{now.month:02d}/{now.year + 543}"

    # ถอนจากธนาคาร 5,000 มาเป็นเงินสด
    r = env.post(f"/finance/accounts/{aid}/move", data={"fiscal_year": str(fy), "src": "bank", "dst": "cash",
                                                        "amount": "5000", "date": d, "item_id": str(iid)},
                 follow_redirects=False)
    assert "moved_place=1" in r.headers["location"]
    # จ่าย 3,200 จากเงินสด
    env.post(f"/finance/accounts/{aid}/txn", data={"fiscal_year": str(fy), "kind": "out", "amount": "3200", "date": d,
                                                    "note": "จ่ายค่าวัสดุ", "place": "cash", "item_id": str(iid)})
    # จ่ายเงินสดเกินที่มี -> บันทึกได้แต่เตือน
    r = env.post(f"/finance/accounts/{aid}/txn", data={"fiscal_year": str(fy), "kind": "out", "amount": "2000", "date": d,
                                                        "note": "จ่ายเกิน", "place": "cash"}, follow_redirects=False)
    assert "short=cash" in r.headers["location"] and "short_amt=200.00" in r.headers["location"]
    with _db() as s:
        a = s.get(FinanceAccount, aid)
        bal = account_by_place(a, fy)
        assert (bal["bank"], bal["cash"]) == (15000, -200)
        assert sum(bal.values()) == 14800
        moves = s.query(FinanceTxn).filter_by(account_id=aid, no_count=True).all()
        assert len(moves) == 2 and {m.place for m in moves} == {"bank", "cash"}
        assert item_by_place(s.get(AccountItem, iid)) == {"cash": 1800.0, "bank": -5000.0, "agency": 0.0}

        # ทะเบียนคุมเงิน: คอลัมน์คงเหลือ เงินสด/ธนาคาร ลงยอดแยก
        from docx import Document
        from app.services import fin_registers
        txns = [t for t in a.txns if t.fiscal_year == fy]
        doc = fin_registers.render_money_register(s.query(School).first(), a, txns, 20000, fy, doc=Document())
        rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
        last_txn = next(r for r in rows if "จ่ายเกิน" in r)
        assert last_txn[7] == "-200.00" and last_txn[8] == "15,000.00"

    page = env.get(f"/finance/accounts/{aid}?year={fy}").text
    assert 'class="pl-strip"' in page and 'name="place"' in page and 'id="move"' in page

    # รายงานเงินคงเหลือประจำวัน แยกคอลัมน์ตามที่เก็บจริง
    from app.routers.finance import _build_cash_rows
    with _db() as s:
        rows, tot = _build_cash_rows([s.get(FinanceAccount, aid)], fy, None)
        mine = next(r for r in rows if r["name"] == "ค่าวัสดุ")
        assert (mine["cash"], mine["bank"]) == (1800.0, -5000.0)
        assert round(tot["cash"], 2) == -200 and round(tot["bank"], 2) == 15000
