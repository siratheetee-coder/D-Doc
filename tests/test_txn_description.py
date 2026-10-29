"""ฟอร์มรับ-จ่ายในทะเบียนคุมเงินมีช่อง "รายการ" และ "หมายเหตุ" แยกกัน ตรงกับคอลัมน์ในทะเบียนที่พิมพ์ออก"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_txn_form_has_description_and_remark(env, tmp_path, monkeypatch):
    from app.models import FinanceAccount, FinanceTxn, AccountItem
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    with _db() as s:
        a = FinanceAccount(name="เงินอุดหนุนทดสอบ", deposit_type="bank"); s.add(a); s.flush()
        it = AccountItem(account_id=a.id, fiscal_year=fy, name="ค่าวัสดุ"); s.add(it); s.commit()
        aid, iid = a.id, it.id
    page = env.get(f"/finance/accounts/{aid}?year={fy}").text
    assert 'name="note" id="txnNote"' in page and 'name="remark"' in page

    today = datetime.now()
    d = f"{today.day:02d}/{today.month:02d}/{today.year + 543}"
    env.post(f"/finance/accounts/{aid}/txn", data={"fiscal_year": str(fy), "kind": "out", "amount": "1200", "date": d,
                                                    "note": "จ่ายค่าวัสดุสำนักงาน ร้านศึกษาภัณฑ์", "remark": "ตามใบส่งของ 15/2569",
                                                    "item_id": str(iid)})
    # ไม่กรอกรายการ: ระบบประกอบให้จากประเภท หมวด และผู้รับเงิน
    env.post(f"/finance/accounts/{aid}/txn", data={"fiscal_year": str(fy), "kind": "out", "amount": "300", "date": d,
                                                    "note": "", "item_id": str(iid), "party": "ร้านบี"})
    with _db() as s:
        rows = s.query(FinanceTxn).filter_by(account_id=aid).order_by(FinanceTxn.id).all()
        assert (rows[0].note, rows[0].remark) == ("จ่ายค่าวัสดุสำนักงาน ร้านศึกษาภัณฑ์", "ตามใบส่งของ 15/2569")
        assert rows[1].note == "จ่ายเงิน ค่าวัสดุ ร้านบี"
        # ทะเบียนคุมเงิน: รายการ -> ช่องรายการ, หมายเหตุ -> ช่องหมายเหตุ (คอลัมน์สุดท้าย)
        from app.services import fin_registers
        monkeypatch.setattr(fin_registers, "get_data_dir", lambda: tmp_path, raising=False)
        from app.models import School
        doc = fin_registers.render_money_register(s.query(School).first(), s.get(FinanceAccount, aid), rows, 0, fy, doc=__import__("docx").Document())
        cells = [[c.text for c in r.cells] for r in doc.tables[0].rows]
        hit = next(r for r in cells if "จ่ายค่าวัสดุสำนักงาน ร้านศึกษาภัณฑ์" in r)
        assert hit[-1] == "ตามใบส่งของ 15/2569"
