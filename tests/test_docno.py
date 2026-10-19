# -*- coding: utf-8 -*-
"""เลขที่เอกสาร บจ./บค. รันอัตโนมัติในฟอร์มบันทึกรับ-จ่าย
รัน: .venv\Scripts\python.exe -m pytest tests/test_docno.py
"""
from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _refs(note_prefix):
    from app.models import FinanceTxn
    db = _db()
    try:
        return [t.ref for t in db.query(FinanceTxn).filter(FinanceTxn.note.like(note_prefix + "%")).order_by(FinanceTxn.id)]
    finally:
        db.close()


def test_format_and_pattern():
    from app.services.docno import format_no, _pattern
    assert format_no("บจ.", 5, 2570) == "บจ.5/70" and format_no("บค.", 12, 2570, "4") == "บค.12/2570"
    rx = _pattern("บจ.", 2570)
    for ok in ("บจ.3/70", "บจ. 3/2570", "บจ3 / 70", " บจ.03/70 "):
        assert rx.match(ok), ok
    for bad in ("บจ.3/69", "บค.3/70", "บจ.3/2569", "เลขที่ บจ.3/70", "บจ.3/700"):
        assert not rx.match(bad), bad


def test_auto_number_on_save(env):
    from app.models import FinanceAccount, Receipt
    env.post("/finance/accounts", data={"name": "เงินรายได้สถานศึกษา", "deposit_type": "bank", "eb_slot": "3.5"})
    db = _db()
    try:
        aid = db.query(FinanceAccount).filter_by(name="เงินรายได้สถานศึกษา").one().id
        db.add(Receipt(fiscal_year=FY, receipt_no="บจ.7/70", kind="จ่าย", amount=1))      # เลขที่พิมพ์เองไว้ในทะเบียนใบสำคัญ
        db.add(Receipt(fiscal_year=FY - 1, receipt_no="บจ.40/69", kind="จ่าย", amount=1))  # ปีอื่น ไม่นับ
        db.add(Receipt(fiscal_year=FY - 1, receipt_no="บค.5/2570", kind="จ่าย", amount=1))  # ลงปีงบผิดแต่เลขเป็นของปี 70 ต้องนับ
        db.commit()
    finally:
        db.close()
    html = env.get(f"/finance/accounts/{aid}?year={FY}").text
    assert 'name="ref_mode"' in html and '<option value="บจ.">' in html and "/70</option>" in html and "/2570</option>" in html
    assert env.get(f"/finance/docno/next?prefix=บจ.&year={FY}").json() == {"ref": "บจ.8/70"}
    assert env.get(f"/finance/docno/next?prefix=บค.&year={FY}&yfmt=4").json() == {"ref": "บค.6/2570"}
    assert env.get(f"/finance/docno/next?prefix=บร.&year={FY}").status_code == 400

    def add(note, mode, ref="", yfmt="2", kind="out"):
        env.post(f"/finance/accounts/{aid}/txn", data={"kind": kind, "amount": "100", "date": "05/11/2569",
                 "fiscal_year": FY, "note": note, "ref": ref, "ref_mode": mode, "ref_yfmt": yfmt})

    add("ทดสอบ-1", "บจ.", ref="บจ.999/70")      # ค่าที่ฟอร์มส่งมาไม่ใช้ ระบบออกเลขเอง
    add("ทดสอบ-2", "บจ.")
    add("ทดสอบ-3", "บจ.", yfmt="4")              # /2570 ใช้ลำดับเดียวกับ /70
    add("ทดสอบ-4", "บค.")
    add("ทดสอบ-5", "", ref="  ที่ ศธ 123  ")      # พิมพ์เองเหมือนเดิม
    add("ทดสอบ-6", "บร.", ref="เลขเดิม")          # ชนิดที่ไม่รองรับ = ใช้ค่าที่พิมพ์
    assert _refs("ทดสอบ-") == ["บจ.8/70", "บจ.9/70", "บจ.10/2570", "บค.6/70", "ที่ ศธ 123", "เลขเดิม"]
    assert env.get(f"/finance/docno/next?prefix=บจ.&year={FY}").json()["ref"] == "บจ.11/70"
    assert env.get(f"/finance/docno/next?prefix=บจ.&year={FY + 1}").json()["ref"] == "บจ.1/71", "ปีงบใหม่เริ่ม 1"
    cb = env.get(f"/finance/cashbook?year={FY}").text
    assert "บจ.8/70" in cb and "บค.6/70" in cb, "เลขขึ้นในสมุดเงินสดช่องเลขที่เอกสาร"
