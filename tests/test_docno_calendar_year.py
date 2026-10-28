"""เลขหนังสือราชการ (บันทึกข้อความ คำสั่ง หนังสือรับ-ส่ง) เรียงตามปีปฏิทิน ใบสั่งซื้อ/จ้างเรียงตามปีงบ"""
from datetime import datetime

from tests.test_subsidy import db  # noqa: F401
from app.models import DocNumberCounter, IssuedDocNo


def test_doc_year_rules():
    from app.services.doc_number import doc_year
    # ท้ายเลขบอกปีเอง
    assert doc_year("memo", 2570, "12/2569") == 2569
    assert doc_year("outgoing", 2570, "ศธ 5/2569") == 2569
    assert doc_year("outgoing", 2570, "ศธ 04002/45", datetime(2026, 11, 2)) == 2569   # /45 ไม่ใช่ปี ใช้วันที่แทน
    # ไม่มีท้ายปี ใช้วันที่บนเอกสาร: พ.ย. 2569 = ปีปฏิทิน 2569 แม้เป็นปีงบ 2570
    assert doc_year("command", 2570, "", datetime(2026, 11, 2)) == 2569
    assert doc_year("command", 2570, "", datetime(2027, 1, 5)) == 2570
    # ใบสั่งซื้อ/จ้าง คงปีงบ
    assert doc_year("purchase_order", 2570, "3/2570", datetime(2026, 11, 2)) == 2570
    # ไม่มีข้อมูลเลย ปีงบย้อนหลังคงไว้
    assert doc_year("memo", 2560) == 2560


def test_memo_counts_by_calendar_year_and_po_by_fiscal(db, monkeypatch):
    import app.services.doc_number as dn
    from app.services import doc_number

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 15)
    monkeypatch.setattr(dn, "datetime", FakeDT)
    import app.thai_utils as tu
    monkeypatch.setattr(tu, "datetime", FakeDT)

    # ก่อนหน้า: ปีปฏิทิน 2569 ใช้บันทึกข้อความไปถึงเลข 380 แล้ว
    db.add(DocNumberCounter(doc_type="memo", fiscal_year=2569, last_number=380)); db.commit()
    assert doc_number.suggest_doc_no(db, "memo", 2570) == "381/2569"          # พ.ย. ยังเป็นปี 2569
    doc_number.commit_doc_no(db, "memo", 2570, "381/2569", source="admin", ref_id=1, date=FakeDT(2026, 11, 15))
    assert db.query(IssuedDocNo).filter_by(doc_type="memo", seq=381).one().fiscal_year == 2569
    # ใบสั่งซื้อปีงบ 2570 เริ่ม 1
    assert doc_number.suggest_doc_no(db, "purchase_order", 2570) == "1/2570"
    assert doc_number.check_doc_no(db, "memo", 2570, "381/2569")["level"] == "duplicate"
    assert doc_number.check_doc_no(db, "memo", 2570, "1/2570") is None

    # ขึ้นปีใหม่ ม.ค. 2570: บันทึกข้อความเริ่มเลข 1 ส่วนใบสั่งซื้อยังต่อเลขปีงบ 2570
    doc_number.commit_doc_no(db, "purchase_order", 2570, "1/2570", source="procurement", ref_id=1)

    class Jan(FakeDT):
        @classmethod
        def now(cls, tz=None):
            return cls(2027, 1, 5)
    monkeypatch.setattr(dn, "datetime", Jan)
    monkeypatch.setattr(tu, "datetime", Jan)
    assert doc_number.suggest_doc_no(db, "memo", 2570) == "1/2570"
    assert doc_number.suggest_doc_no(db, "purchase_order", 2570) == "2/2570"
