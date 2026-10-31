# -*- coding: utf-8 -*-
"""แยกจ่ายบันทึกขอเบิก 1 ฉบับจากหลายบัญชี"""
from datetime import datetime

import pytest
from docx import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Project, Receipt
from app.services import disburse_payments as payments
from app.services import disburse_split as splits


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture()
def accs(db):
    a = FinanceAccount(name="เงินอุดหนุน")
    b = FinanceAccount(name="เงินรายได้สถานศึกษา")
    db.add_all([a, b]); db.flush()
    ia = AccountItem(account_id=a.id, fiscal_year=2570, name="ค่ารายหัว")
    ib = AccountItem(account_id=b.id, fiscal_year=2570, name="รายได้ทั่วไป")
    db.add_all([ia, ib]); db.flush()
    return a, b, ia, ib


def memo(db, amount=30000.0, **kw):
    m = DisburseMemo(fiscal_year=2570, memo_no="บ.1/2570", subject="ซื้อวัสดุ", payee="ร้านเอ",
                     amount=amount, date=datetime(2026, 11, 2), status="อนุมัติ", **kw)
    db.add(m); db.flush()
    return m


def two(accs, x=20000.0, y=10000.0):
    a, b, ia, ib = accs
    return [dict(account_id=a.id, item_id=ia.id, amount=x), dict(account_id=b.id, item_id=ib.id, amount=y)]


def test_parse_skips_blank_rows_and_commas():
    rows = splits.parse(["1", "", "2"], ["5", "", ""], ["20,000", "", "10000.50"])
    assert rows == [dict(account_id=1, item_id=5, amount=20000.0), dict(account_id=2, item_id=None, amount=10000.5)]


def test_post_one_memo_makes_one_txn_per_account(db, accs):
    a, b, ia, _ = accs
    m = memo(db)
    splits.apply(db, m, two(accs))
    assert (m.account_id, m.item_id) == (a.id, ia.id)
    splits.post(db, m); db.flush()
    txns = db.query(FinanceTxn).filter_by(disburse_id=m.id).order_by(FinanceTxn.id).all()
    assert [(t.account_id, t.amount) for t in txns] == [(a.id, 20000.0), (b.id, 10000.0)]
    assert {t.date for t in txns} == {m.date}
    assert payments.summary(db, m)["paid"] == 30000.0


def test_single_account_stays_as_before(db, accs):
    a, _, ia, _ = accs
    m = memo(db, account_id=a.id, item_id=ia.id)
    splits.apply(db, m, [])
    splits.post(db, m); db.flush()
    t = db.query(FinanceTxn).filter_by(disburse_id=m.id).one()
    assert (t.account_id, t.item_id, t.amount, t.note) == (a.id, ia.id, 30000.0, "จ่าย ร้านเอ")
    assert not splits.is_split(m)


@pytest.mark.parametrize("rows_fn,word", [
    (lambda c: two(c, 20000, 5000), "ไม่เท่ายอดขอเบิก"),
    (lambda c: two(c, 30000, 0), "มากกว่า 0"),
    (lambda c: [dict(account_id=None, item_id=None, amount=10000), two(c)[1] | {"amount": 20000}], "ครบทุกแถว"),
    (lambda c: [two(c)[0] | {"amount": 15000}, two(c)[0] | {"amount": 15000}], "ซ้ำกัน"),
    (lambda c: [two(c)[0] | {"item_id": c[3].id}, two(c)[1]], "หมวดไม่ตรง"),
])
def test_bad_splits_are_refused(db, accs, rows_fn, word):
    m = memo(db)
    with pytest.raises(ValueError, match=word):
        splits.apply(db, m, rows_fn(accs))
    assert not m.splits


def test_withholding_shares_add_up_exactly(db, accs):
    m = memo(db, amount=1000.0, wht=10.01, fine=0.05)
    splits.apply(db, m, two(accs, 333.33, 666.67))
    rows = splits.rows_of(db, m)
    assert rows[0]["wht"] == 3.34 and round(sum(r["wht"] for r in rows), 2) == 10.01
    assert round(sum(r["fine"] for r in rows), 2) == 0.05
    assert round(sum(r["net"] for r in rows), 2) == round(1000 - 10.01 - 0.05, 2)


def test_edit_after_posting_changes_amounts_and_removes_a_row(db, accs):
    a, b, ia, ib = accs
    m = memo(db)
    splits.apply(db, m, two(accs))
    splits.post(db, m); db.flush()
    txns = db.query(FinanceTxn).filter_by(disburse_id=m.id).all()
    splits.apply(db, m, two(accs, 25000, 5000)); db.flush()
    splits.sync(db, m, txns); db.flush()
    assert sorted(t.amount for t in db.query(FinanceTxn).filter_by(disburse_id=m.id)) == [5000.0, 25000.0]

    # กลับเป็นบัญชีเดียว เหลือรายการเงินเดียว ยอดเต็ม
    txns = db.query(FinanceTxn).filter_by(disburse_id=m.id).all()
    m.account_id, m.item_id = a.id, ia.id
    splits.apply(db, m, []); db.flush()
    splits.sync(db, m, txns); db.flush()
    t = db.query(FinanceTxn).filter_by(disburse_id=m.id).one()
    assert (t.account_id, t.amount) == (a.id, 30000.0)


def test_edit_refused_when_part_is_tied_to_a_receipt(db, accs):
    m = memo(db)
    splits.apply(db, m, two(accs))
    splits.post(db, m); db.flush()
    txns = db.query(FinanceTxn).filter_by(disburse_id=m.id).order_by(FinanceTxn.id).all()
    db.add(Receipt(txn_id=txns[1].id, fiscal_year=2570)); db.flush()
    splits.apply(db, m, two(accs, 25000, 5000)); db.flush()
    with pytest.raises(ValueError, match="เชื่อมใบเสร็จ"):
        splits.sync(db, m, txns)


def test_split_memo_cannot_link_an_existing_payment(db, accs):
    a = accs[0]
    m = memo(db)
    splits.apply(db, m, two(accs))
    old = FinanceTxn(account_id=a.id, fiscal_year=2570, kind="out", amount=30000.0, date=datetime(2026, 11, 1))
    db.add(old); db.flush()
    assert payments.compatible(db, m, old) is False


def test_delete_memo_removes_its_rows(db, accs):
    m = memo(db)
    splits.apply(db, m, two(accs)); db.flush()
    db.delete(m); db.flush()
    from app.models import DisburseSplit
    assert db.query(DisburseSplit).count() == 0


def test_source_text_uses_account_names_unless_typed(db, accs):
    m = memo(db)
    splits.apply(db, m, two(accs))
    assert splits.source_text(db, m) == "เงินอุดหนุน 20,000.00 บาท และ เงินรายได้สถานศึกษา 10,000.00 บาท"
    m.budget_source = "เงินอุดหนุนทั่วไป"
    assert splits.source_text(db, m) == "เงินอุดหนุนทั่วไป"


def test_project_spent_counts_total_once(db, accs):
    from app.services.budget import project_money_summary
    pj = Project(name="ค่ายวิชาการ", budget=50000.0)
    db.add(pj); db.flush()
    m = memo(db, project_id=pj.id)
    splits.apply(db, m, two(accs))
    splits.post(db, m); db.flush()
    info = project_money_summary(pj)
    assert info["paid"] == 30000.0
    assert info["waiting"] == 0


@pytest.mark.parametrize("kind", ["จัดซื้อ", "ค่าใช้จ่ายอื่น"])
def test_memo_document_lists_each_account(db, accs, kind, tmp_path, monkeypatch):
    from app.models import School
    from app.services import finance_doc
    monkeypatch.setattr(finance_doc, "get_data_dir", lambda: tmp_path)
    school = School(name="โรงเรียนทดสอบ")
    db.add(school); db.flush()
    m = memo(db, wht=300.0, proc_kind=kind)
    splits.apply(db, m, two(accs)); db.flush()
    path = finance_doc.render_disburse(m, school)
    text = chr(10).join(p.text for p in Document(path).paragraphs)
    assert "เงินอุดหนุน (ค่ารายหัว) จำนวน 20,000.00 บาท หักภาษี ณ ที่จ่าย 200.00 บาท" in text
    assert "เงินรายได้สถานศึกษา (รายได้ทั่วไป) จำนวน 10,000.00 บาท หักภาษี ณ ที่จ่าย 100.00 บาท" in text
