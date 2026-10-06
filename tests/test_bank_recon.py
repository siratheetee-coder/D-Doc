# -*- coding: utf-8 -*-
"""งบกระทบยอดเงินฝากธนาคาร: ยอดตามบัญชีต้องถูกต้องจริง

เคยพลาดแบบเดียวกันมาแล้วในรายงานไตรมาส คือใช้ยอดตั้งต้นของบัญชี
แทนยอดยกมาของปีงบนั้น ทำให้โรงเรียนที่ยกยอดข้ามปีได้ตัวเลขผิด
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_bank_recon.py
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (AccountOpening, BankRecon, CheckPayment, FinanceAccount,
                        FinanceTxn, School)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(School(name="โรงเรียนทดสอบ"))
        s.commit()
        yield s
    engine.dispose()


def _account(db, name="เงินอุดหนุนทั่วไป", opening=1000.0):
    a = FinanceAccount(name=name, fund_type="เงินงบประมาณ", deposit_type="bank",
                       opening_balance=opening)
    db.add(a)
    db.commit()
    return a


def _txn(db, acc, fy, kind, amount, day):
    db.add(FinanceTxn(account_id=acc.id, fiscal_year=fy, kind=kind, amount=amount,
                      date=datetime(2026, day[0], day[1])))
    db.commit()


# ---------------------------------------------------------------- ยอดยกมา
def test_book_balance_uses_the_carried_forward_opening_not_the_original(db):
    from app.routers.finance import _book_balance
    acc = _account(db, opening=1000.0)
    db.add(AccountOpening(account_id=acc.id, fiscal_year=2570, amount=25000.0))
    db.commit()
    _txn(db, acc, 2570, "in", 5000.0, (10, 5))
    _txn(db, acc, 2570, "out", 2000.0, (10, 20))
    # ยอดยกมาปี 2570 คือ 25,000 ไม่ใช่ยอดตั้งต้นของบัญชี 1,000
    assert _book_balance(db, 2570, acc.id) == 28000.0


def test_book_balance_falls_back_to_the_original_opening_when_no_carry_forward(db):
    from app.routers.finance import _book_balance
    acc = _account(db, opening=1000.0)
    _txn(db, acc, 2569, "in", 500.0, (6, 1))
    assert _book_balance(db, 2569, acc.id) == 1500.0


def test_book_balance_counts_only_the_year_asked_for(db):
    from app.routers.finance import _book_balance
    acc = _account(db, opening=0.0)
    _txn(db, acc, 2569, "in", 900.0, (6, 1))
    _txn(db, acc, 2570, "in", 100.0, (10, 1))
    assert _book_balance(db, 2570, acc.id) == 100.0


# ---------------------------------------------------------------- ตัดยอด ณ วันที่
def test_book_balance_can_stop_at_the_reconciliation_date(db):
    """กระทบยอด ณ 30 ก.ย. ต้องไม่รวมรายการเดือนตุลาคมที่ลงบัญชีไปแล้ว"""
    from app.routers.finance import _book_balance
    acc = _account(db, opening=0.0)
    db.add(AccountOpening(account_id=acc.id, fiscal_year=2570, amount=10000.0))
    db.commit()
    _txn(db, acc, 2570, "in", 5000.0, (9, 30))
    _txn(db, acc, 2570, "out", 3000.0, (10, 2))
    assert _book_balance(db, 2570, acc.id) == 12000.0
    assert _book_balance(db, 2570, acc.id, upto=datetime(2026, 9, 30)) == 15000.0


def test_a_transaction_without_a_date_is_not_silently_dropped(db):
    """ข้อมูลเก่าที่ไม่มีวันที่ ต้องยังนับอยู่ ไม่ใช่หายไปเงียบ ๆ ตอนตัดยอด"""
    from sqlalchemy import text
    from app.routers.finance import _book_balance
    acc = _account(db, opening=0.0)
    _txn(db, acc, 2570, "in", 700.0, (10, 1))
    db.execute(text("UPDATE finance_txn SET date = NULL"))
    db.commit()
    assert _book_balance(db, 2570, acc.id, upto=datetime(2026, 9, 30)) == 700.0


# ---------------------------------------------------------------- หน้าจอ
def test_history_shows_only_the_account_being_reconciled(db):
    from fastapi.testclient import TestClient
    a = _account(db, "บัญชีเงินอุดหนุน")
    b = _account(db, "บัญชีเงินรายได้สถานศึกษา")
    db.add(BankRecon(fiscal_year=2570, account_id=a.id, as_of=datetime(2026, 9, 30),
                     stmt_balance=1.0, book_balance=1.0))
    db.add(BankRecon(fiscal_year=2570, account_id=b.id, as_of=datetime(2026, 9, 30),
                     stmt_balance=2.0, book_balance=2.0))
    db.commit()
    from app.routers import finance as fin
    rows = fin._recon_rows(db, 2570, a.id)
    assert [r.account_id for r in rows] == [a.id]


def test_unassigned_payments_are_not_counted_in_every_account(db):
    """เช็คที่ยังไม่ระบุบัญชี ต้องไม่ถูกนับเป็นรายการคงค้างของทุกบัญชีพร้อมกัน"""
    from app.routers import finance as fin
    a = _account(db, "บัญชี ก")
    b = _account(db, "บัญชี ข")
    db.add(CheckPayment(fiscal_year=2570, account_id=a.id, amount=100.0, cleared=False,
                        payee="ร้าน ก", date=datetime(2026, 9, 1)))
    db.add(CheckPayment(fiscal_year=2570, account_id=None, amount=50.0, cleared=False,
                        payee="ยังไม่ระบุบัญชี", date=datetime(2026, 9, 2)))
    db.commit()
    mine_a, loose_a = fin._outstanding_checks(db, 2570, a.id)
    mine_b, loose_b = fin._outstanding_checks(db, 2570, b.id)
    assert [c.payee for c in mine_a] == ["ร้าน ก"]
    assert mine_b == []
    # รายการที่ยังไม่ระบุบัญชี แจ้งแยกให้ไปตามเก็บ ไม่เอาไปบวกลบยอด
    assert [c.payee for c in loose_a] == ["ยังไม่ระบุบัญชี"]
    assert [c.payee for c in loose_b] == ["ยังไม่ระบุบัญชี"]


def test_page_calculates_the_difference_while_typing(db):
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / "app" / "templates" / "finance_bank_recon.html").read_text(encoding="utf-8")
    assert "data-recon-calc" in html, "ต้องมีช่องแสดงยอดกระทบแล้วและผลต่างแบบคำนวณสด"
    assert "ผลต่าง" in html
