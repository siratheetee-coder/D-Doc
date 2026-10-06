# -*- coding: utf-8 -*-
"""เงื่อนไขขอบของงานคำนวณเงินอุดหนุน ที่เคยเดาว่าน่าจะพัง

ตรวจความสอดคล้องของตัวเลข (ยอดตั้งงบ = ผลรวมแถว, งวดปรับยอด = เต็มเทอม ลบ งวดแรก)
และพฤติกรรมตอนสลับโหมด สลับภาคเรียน และกรอกข้อมูลไม่ครบ
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_subsidy_edges.py
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.database import Base
from app.models import School, SubsidyCensusRevision
from app.services import subsidy as sub

LV9 = ["อ.1", "อ.2", "อ.3", "ป.1", "ป.2", "ป.3", "ป.4", "ป.5", "ป.6"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(School(name="โรงเรียนทดสอบ"))
        session.commit()
        yield session
    engine.dispose()


def _form(db, ay, term, levels=("ป.1", "ป.2"), rate="1234.57", counts=("10", "12"), **over):
    s = sub.state(db, ay, term)
    d = {"academic_year": str(ay), "term": str(term), "token": s["token"]}
    for k in sub.keys_for(term):
        for lv in levels:
            d[f"r_{lv}_{k}"] = rate
    pairs = []
    for i, scan in enumerate(s["census"]):
        for lv in levels:
            pairs.append((f"n_{scan['key']}_{lv}", counts[i]))
    out = [("levels", lv) for lv in levels] + list(d.items()) + pairs
    out += [(k, v) for k, v in over.items()]
    return FormData(out)


def _save(db, ay=2569, term=1, **kw):
    state = sub.save(db, ay, term, _form(db, ay, term, **kw))
    db.commit()
    return state


# ------------------------------------------------- ความสอดคล้องของตัวเลขบนหน้า
def test_budget_total_always_equals_the_rows_shown(db):
    res = _save(db)["result"]
    rows = sum(Decimal(str(r["budget_amount"])) for r in res["rows"])
    assert res["budget_total"] == sub.money(rows)


def test_top_up_is_exactly_full_minus_first_even_with_satang(db):
    res = _save(db, rate="1234.57")["result"]
    for r in res["rows"]:
        want = sub.money(Decimal(str(r["full"])) - Decimal(str(r["basis"])))
        assert r["remaining"] == want, r


def test_first_installment_is_seventy_percent_of_the_advance_base(db):
    res = _save(db, levels=("ป.2",), rate="1000", counts=("10", "12"))["result"]
    # ป.2 เลื่อนฐานมาจาก ป.1 ของรอบแรก ซึ่งไม่ได้กรอกไว้ จึงยังประมาณการไม่ได้
    assert res["basis"][0]["source_level"] == "ป.1"
    assert res["rows"][0]["first_estimate"] is None
    res = _save(db, levels=("ป.1", "ป.2"), rate="1000", counts=("10", "12"))["result"]
    teach = next(r for r in res["rows"] if r["key"] == "teach")
    # ฐานงวดแรก = ป.1(ฐานของ ป.1) + ป.1(ฐานของ ป.2) = 10 + 10 คน
    assert teach["first_estimate"] == sub.money(Decimal("1000") * 20 * Decimal(".7"))


# ------------------------------------------------- สลับโหมดตั้งงบ
def test_switching_back_to_estimate_does_not_let_allocated_numbers_decide_the_budget(db):
    alloc = {f"{w}_{k}": "50000" for w in ("first", "second") for k in sub.keys_for(1)}
    alloc.update(first_ref="ว 1/2569", second_ref="ว 2/2569", budget_basis="allocated")
    res = _save(db, **alloc)["result"]
    assert res["budget_basis"] == "allocated"
    allocated_total = res["budget_total"]
    back = _save(db, **dict(alloc, budget_basis="estimate"))["result"]
    assert back["budget_total"] != allocated_total
    assert back["budget_total"] == sub.money(sum(Decimal(str(r["full"])) for r in back["rows"]))
    # ยอดจัดสรรที่กรอกไว้ยังอยู่ ไม่ถูกลบทิ้งเพราะสลับโหมด
    assert all(r["first"] == 50000 for r in back["rows"] if not r["extra"])


def test_allocated_mode_needs_both_installments_before_it_can_confirm(db):
    half = {f"first_{k}": "50000" for k in sub.keys_for(1)}
    half.update(first_ref="ว 1/2569", budget_basis="allocated")
    res = _save(db, **half)["result"]
    assert res["budget_total"] is None and not res["ready"]
    assert any("งวดปรับยอด" in m for m in res["missing"]), res["missing"]


def test_allocated_mode_ignores_missing_rates_but_estimate_mode_does_not(db):
    both = {f"{w}_{k}": "50000" for w in ("first", "second") for k in sub.keys_for(1)}
    both.update(first_ref="ว 1", second_ref="ว 2", budget_basis="allocated")
    res = _save(db, levels=("ป.1", "ป.2"), rate="", **both)["result"]
    assert res["budget_total"] is not None and res["missing"] == []
    res = _save(db, levels=("ป.1", "ป.2"), rate="", **dict(both, budget_basis="estimate"))["result"]
    assert res["budget_total"] is None and res["missing"]


# ------------------------------------------------- รอบ DMC ที่ใช้ร่วมสองภาคเรียน
def test_saving_one_term_does_not_wipe_the_round_the_other_term_shares(db):
    _save(db, ay=2569, term=1, counts=("10", "12"))
    before = sub.state(db, 2569, 2)["census"][0]["counts"]
    assert before.get("ป.1") == 12, before
    # บันทึกเทอม 2 โดยกรอกรอบมิถุนายนด้วยเลขเดิม ต้องไม่กลายเป็นค่าว่าง
    _save(db, ay=2569, term=2, counts=("12", "14"))
    after = sub.state(db, 2569, 1)["census"][1]["counts"]
    assert after.get("ป.1") == 12, after


def test_editing_the_shared_round_in_one_term_shows_up_in_the_other(db):
    _save(db, ay=2569, term=1, counts=("10", "12"))
    _save(db, ay=2569, term=2, counts=("99", "14"))
    assert sub.state(db, 2569, 1)["census"][1]["counts"]["ป.1"] == 99


def test_unchanged_counts_do_not_pile_up_census_revisions(db):
    _save(db)
    n = db.query(SubsidyCensusRevision).count()
    _save(db)
    _save(db)
    assert db.query(SubsidyCensusRevision).count() == n, "บันทึกซ้ำโดยไม่แก้ ไม่ควรเก็บฉบับใหม่"


# ------------------------------------------------- ชั้นเรียนที่เลือก/ไม่เลือก
def test_unticking_a_level_drops_it_from_the_money_but_keeps_its_numbers(db):
    big = _save(db, levels=("ป.1", "ป.2"))["result"]
    small = _save(db, levels=("ป.1",))["result"]
    assert small["budget_total"] < big["budget_total"]
    assert [b["level"] for b in small["basis"]] == ["ป.1"]
    # หน้าเว็บส่งช่อง DMC มาทุกชั้นเสมอ ชั้นที่ไม่ติ๊กแค่ซ่อนไว้ ยอดจึงยังอยู่
    assert sub.state(db, 2569, 1)["census"][1]["counts"].get("ป.2") == 12


def test_a_form_without_some_count_fields_must_not_erase_them(db):
    """หน้าเก่าค้างในเบราว์เซอร์แล้วกดบันทึก ต้องไม่ลบยอดที่ไม่ได้ส่งมา

    รอบ DMC หนึ่งรอบใช้ร่วมกันสองภาคเรียน ถ้าลบทิ้งคือพังอีกเทอมไปด้วย
    โดยที่หน้าจอไม่ฟ้องอะไรเลย
    """
    _save(db, levels=("ป.1", "ป.2"))
    s = sub.state(db, 2569, 1)
    partial = [("levels", "ป.1"), ("levels", "ป.2"),
               ("academic_year", "2569"), ("term", "1"), ("token", s["token"])]
    for k in sub.keys_for(1):
        partial += [(f"r_ป.1_{k}", "1234.57"), (f"r_ป.2_{k}", "1234.57")]
    # ส่งมาเฉพาะช่องของ ป.1 ไม่มีช่อง ป.2 เลย
    for scan, n in zip(s["census"], ("10", "12")):
        partial.append((f"n_{scan['key']}_ป.1", n))
    sub.save(db, 2569, 1, FormData(partial))
    db.commit()
    after = sub.state(db, 2569, 1)["census"][1]["counts"]
    assert after.get("ป.2") == 12, after
    # ส่วนช่องที่ส่งมาแต่เว้นว่าง ยังหมายถึงลบของเดิมเหมือนเดิม
    _save(db, levels=("ป.1", "ป.2"), counts=("", ""))
    assert sub.state(db, 2569, 1)["census"][1]["counts"].get("ป.2") is None


def test_no_level_selected_is_refused(db):
    with pytest.raises(ValueError):
        sub.save(db, 2569, 1, _form(db, 2569, 1, levels=()))


# ------------------------------------------------- ตัวเลขที่กรอกผิดรูปแบบ
@pytest.mark.parametrize("raw", ["-1", "nan", "Infinity", "2000000000", "1,000", "abc"])
def test_bad_rate_is_refused(db, raw):
    with pytest.raises(ValueError):
        sub.save(db, 2569, 1, _form(db, 2569, 1, rate=raw))


def test_thai_digits_are_read_as_the_number_they_are(db):
    """เลขไทยอ่านเป็นค่าที่ถูกต้อง ไม่ใช่ปัดทิ้งหรืออ่านผิดหลัก"""
    res = _save(db, levels=("ป.1",), rate="๑๐๐๐", counts=("10", "10"))["result"]
    assert sub.state(db, 2569, 1)["config"]["rates"]["ป.1"]["teach"] == 1000
    assert res["budget_total"] == sub.money(1000 * 10 * len(sub.keys_for(1)))


@pytest.mark.parametrize("raw", ["10.5", "-3", "2000000"])
def test_bad_headcount_is_refused(db, raw):
    with pytest.raises(ValueError):
        sub.save(db, 2569, 1, _form(db, 2569, 1, counts=(raw, "12")))


def test_zero_is_kept_as_a_real_answer_not_as_missing(db):
    res = _save(db, levels=("ป.1",), rate="0", counts=("0", "0"))["result"]
    assert res["budget_total"] == 0 and res["missing"] == []


# ------------------------------------------------- การแข่งกันบันทึกจากสองหน้าจอ
def test_a_stale_form_cannot_overwrite_a_newer_save(db):
    stale = _form(db, 2569, 1, rate="1000")
    _save(db, rate="2000")
    with pytest.raises(ValueError):
        sub.save(db, 2569, 1, stale)


def test_confirm_refuses_a_token_from_before_the_last_edit(db):
    s = _save(db)
    old = s["token"]
    _save(db, rate="999")
    with pytest.raises(ValueError):
        sub.confirm(db, 2569, 1, old)


# ------------------------------------------------- คำเตือนและขั้นตอน
def test_warnings_never_point_at_a_field_that_is_not_on_the_form(db):
    res = _save(db, levels=("ป.1", "ป.2"), rate="", counts=("", ""))["result"]
    keys = sub.keys_for(1)
    scans = sub.state(db, 2569, 1)["census"]
    allowed = {f"r_{lv}_{k}" for lv in sub.LEVELS for k in keys}
    allowed |= {f"n_{s['key']}_{lv}" for s in scans for lv in sub.LEVELS}
    assert res["missing_fields"]
    for f in res["missing_fields"]:
        assert f in allowed, f


def test_steps_and_missing_warnings_tell_the_same_story(db):
    res = _save(db)["result"]
    data = sub.state(db, 2569, 1)
    steps = sub.workflow_steps(data, {}, None, [])
    assert (steps[2]["state"] == "done") == (res["budget_total"] is not None)
    assert steps[3]["state"] != "done", "ยังไม่ได้ยืนยัน จะขึ้นว่าเสร็จไม่ได้"
    sub.confirm(db, 2569, 1, data["token"])
    db.commit()
    after = sub.state(db, 2569, 1)
    assert sub.workflow_steps(after, {}, None, [])[3]["state"] == "done"
