# -*- coding: utf-8 -*-
"""ภาษีหัก ณ ที่จ่าย: รับเข้าบัญชีตอนลงจ่าย นำส่งรายเดือน ไม่ซ้ำ"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import DisburseMemo, FinanceAccount, FinanceTxn, School
from app.services import disburse_split as splits
from app.services import wht_ledger as wl


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(School(name="โรงเรียนทดสอบ")); s.add(FinanceAccount(name="เงินอุดหนุน")); s.flush()
    yield s
    s.close()


def _memo(db, wht=508.04, day=10):
    acc = db.query(FinanceAccount).filter_by(name="เงินอุดหนุน").one()
    m = DisburseMemo(fiscal_year=2570, memo_no=f"บ.{day}/2569", subject="จ้างซ่อมแอร์", payee="ร้านเย็น",
                     amount=18120.0, vat=1185.42, wht=wht, date=datetime(2026, 11, day), status="อนุมัติ",
                     account_id=acc.id)
    db.add(m); db.flush()
    splits.post(db, m, paid_date=datetime(2026, 11, day)); db.flush()
    return m


def _held(db):
    return db.query(FinanceTxn).filter(FinanceTxn.wht_memo_id.isnot(None)).all()


def test_nothing_until_school_starts_tracking(db):
    _memo(db)
    assert wl.sync(db) == 0 and not _held(db)


def test_receive_then_remit_and_undo(db):
    db.query(School).one().wht_track_from = "2026-11-05"
    _memo(db, day=1)                      # ก่อนวันเริ่มคุม ไม่นับ
    m = _memo(db, day=10)
    wl.sync(db); wl.sync(db)              # เรียกซ้ำไม่ซ้ำ
    held = _held(db)
    assert [(t.wht_memo_id, t.amount, t.kind) for t in held] == [(m.id, 508.04, "in")]
    acc = db.get(FinanceAccount, held[0].account_id)
    assert acc.name == wl.ACCOUNT_NAME
    # จ่ายจากบัญชีเงินอุดหนุนเต็มยอด
    assert db.query(FinanceTxn).filter_by(disburse_id=m.id).one().amount == 18120.0

    m.wht = 543.63; wl.sync(db)           # แก้ยอดภาษี รายการรับตาม
    assert _held(db)[0].amount == 543.63

    out = wl.remit(db, "2026-11", datetime(2026, 12, 5), "ใบเสร็จ 001")
    assert out.amount == 543.63 and out.kind == "out" and out.account_id == acc.id
    assert not wl.pending(db)
    m.wht = 1.0; wl.sync(db)              # นำส่งแล้วไม่แตะ
    assert _held(db)[0].amount == 543.63

    wl.undo(db, out.id)
    assert list(wl.pending(db)) == ["2026-11"]


def test_memo_wht_removed_drops_pending(db):
    db.query(School).one().wht_track_from = "2026-11-01"
    m = _memo(db)
    wl.sync(db)
    m.wht = 0; wl.sync(db)
    assert not _held(db)


def test_uses_existing_tax_account(db):
    db.add(FinanceAccount(name="ภาษีหัก ณ ที่จ่าย (เดิม)")); db.flush()
    db.query(School).one().wht_track_from = "2026-11-01"
    _memo(db); wl.sync(db)
    assert db.get(FinanceAccount, _held(db)[0].account_id).name == "ภาษีหัก ณ ที่จ่าย (เดิม)"
