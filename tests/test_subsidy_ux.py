# -*- coding: utf-8 -*-
"""หน้าคำนวณเงินอุดหนุน: คำเตือนต้องอ่านรู้เรื่อง และชี้ช่องที่ต้องกรอกให้เห็น

ของเดิมเปิดหน้าครั้งแรกขึ้นคำเตือน 47 บรรทัด ไล่ทีละชั้นทีละรายการ
("ขาดอัตรา อ.1 / ค่าจัดการเรียนการสอน", "ขาดอัตรา อ.2 / ..." ไปจนครบ 9 ชั้น x 5 รายการ)
ซึ่งอ่านไม่ออกว่าต้องทำอะไรก่อน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_subsidy_ux.py
"""
import pathlib
import re

import pytest

from app.services.subsidy import ITEMS, calculate

LV9 = ["อ.1", "อ.2", "อ.3", "ป.1", "ป.2", "ป.3", "ป.4", "ป.5", "ป.6"]
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _scan(year, rnd, counts, saved=True):
    key = f"{rnd}{year}"
    return {"year": year, "round": rnd, "counts": counts, "saved": saved, "key": key,
            "label": f"{'10 มิถุนายน' if rnd == 'jun' else '10 พฤศจิกายน'} {year}",
            "id": 1 if saved else None, "confirmed": saved}


def _cfg(rates, **kw):
    return dict({"levels": LV9, "rates": rates, "first": {}, "second": {}, "extras": {},
                 "budget_basis": "estimate"}, **kw)


def _full_scans():
    return [_scan(2568, "nov", {lv: 10 for lv in LV9}), _scan(2569, "jun", {lv: 10 for lv in LV9})]


def test_missing_rates_collapse_into_one_line_per_item():
    """ไม่มีอัตราเลย = 45 ช่อง แต่ต้องเตือนแค่ 5 บรรทัด (รายการละบรรทัด)"""
    r = calculate(_cfg({}), _full_scans(), 1)
    assert len(r["missing"]) == len(ITEMS), r["missing"]
    for msg in r["missing"]:
        assert "ยังไม่ได้กรอกอัตรา" in msg
        assert "(9 ชั้น)" in msg, msg


def test_a_few_missing_levels_are_listed_by_name():
    """ขาดไม่กี่ชั้น ควรบอกชื่อชั้นไปเลย จะได้ไม่ต้องไล่หา"""
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    del rates["ป.3"]["teach"]
    del rates["ป.5"]["teach"]
    r = calculate(_cfg(rates), _full_scans(), 1)
    assert len(r["missing"]) == 1
    assert "ป.3" in r["missing"][0] and "ป.5" in r["missing"][0], r["missing"]


def test_missing_fields_point_at_real_input_names():
    """รายชื่อช่องต้องตรงกับ name ของ input จริง ไม่งั้นไฮไลต์ไม่ติด"""
    r = calculate(_cfg({}), _full_scans(), 1)
    fields = r["missing_fields"]
    assert len(fields) == len(LV9) * len(ITEMS)
    assert "r_อ.1_teach" in fields and "r_ป.6_activity" in fields
    assert len(set(fields)) == len(fields), "ต้องไม่ซ้ำ"

    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    assert 'name="r_{{ lv }}_{{ k }}"' in html.replace("r_{{ lv }}_{{ k }}", "r_{{ lv }}_{{ k }}")


def test_missing_census_cells_are_pointed_at_too():
    scans = _full_scans()
    del scans[1]["counts"]["ป.3"]
    r = calculate(_cfg({lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}), scans, 1)
    assert "n_jun2569_ป.3" in r["missing_fields"], r["missing_fields"]


def test_nothing_missing_means_no_warning_and_no_highlight():
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    r = calculate(_cfg(rates), _full_scans(), 1)
    assert r["missing"] == [] and r["missing_fields"] == []
    assert r["ready"]


# ---------------------------------------------------------------- ฝั่งหน้าจอ
def test_page_marks_levels_so_unticked_ones_can_hide():
    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    assert 'data-count-level="{{ lv }}"' in html, "ช่อง DMC ต้องติดป้ายชั้นไว้ให้ JS ซ่อนได้"
    assert 'data-rate-level="{{ lv }}"' in html


def test_page_has_the_fill_column_button_for_every_item():
    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    assert 'data-fill-col="{{ k }}"' in html


def test_script_hides_counts_highlights_and_fills(tmp_path):
    js = (ROOT / "app" / "static" / "subsidy.js").read_text(encoding="utf-8")
    assert "data-count-level" in js, "ต้องซ่อนช่อง DMC ของชั้นที่ไม่ได้ติ๊ก"
    assert "aria-invalid" in js, "ต้องไฮไลต์ช่องที่ยังไม่ได้กรอก"
    assert "data-fill-col" in js
    # เคยพลาด: สตริงถูกตัดกลางบรรทัดจน JS พังทั้งไฟล์ -> ทุกฟีเจอร์ในหน้าหยุดทำงานเงียบ ๆ
    for i, line in enumerate(js.splitlines(), 1):
        head = line.split("//")[0]
        assert head.count("'") % 2 == 0, f"อัญประกาศไม่ครบคู่ที่บรรทัด {i}: {line.strip()[:60]}"


def test_css_marks_needed_fields():
    css = (ROOT / "app" / "static" / "subsidy.css").read_text(encoding="utf-8")
    assert 'aria-invalid="true"' in css


# ---------------------------------------------- แถบขั้นตอน (เหมือนหน้าทัศนศึกษา)
from app.services.subsidy import rounds, shared_term, workflow_steps


def _data(term=1, rates=None, levels=None, latest=None, changed=False, basis=None,
          empty_dmc=False):
    lv = levels if levels is not None else LV9
    scans = _full_scans() if term == 1 else [_scan(2569, "jun", {}), _scan(2569, "nov", {})]
    if empty_dmc:
        scans = [_scan(s["year"], s["round"], {}) for s in scans]
    cfg = _cfg(rates if rates is not None else {}, levels=lv)
    res = calculate(cfg, scans, term)
    if basis is not None:
        res["basis"] = basis
    return {"config": cfg, "result": res, "term": term, "census": scans,
            "latest": latest, "changed": changed}


class _Snap:
    id = 7


def test_steps_start_at_rates_and_stop_at_the_first_unfinished_one():
    steps = workflow_steps(_data(empty_dmc=True), {}, None, [])
    assert [s["state"] for s in steps] == ["doing", "todo", "todo", "todo", "todo", "todo"]
    assert "0 / 45 ช่อง" in steps[0]["sub"], steps[0]
    assert "0 / 18 ช่อง" in steps[1]["sub"], steps[1]
    # ทุกขั้นต้องชี้ไปที่ส่วนที่มีอยู่จริงในหน้า ไม่งั้นกดแล้วไม่ขยับ
    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    for s in steps:
        assert f'id="{s["href"][1:]}"' in html, s["href"]


def test_finished_rates_move_the_current_step_forward():
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    steps = workflow_steps(_data(rates=rates), {}, None, [])
    assert steps[0]["state"] == "done" and "45 / 45" in steps[0]["sub"]
    # DMC ครบด้วย (ฐานมาจาก _full_scans) จึงต้องข้ามไปขั้นที่ 3
    assert steps[1]["state"] == "done"
    assert steps[2]["state"] == "done", steps[2]       # รวมยอดได้แล้ว
    assert steps[3]["state"] == "doing", steps[3]      # ค้างที่การยืนยัน


def test_confirmed_then_changed_goes_back_to_not_done():
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    ok = workflow_steps(_data(rates=rates, latest=_Snap()), {}, None, [])
    assert ok[3]["state"] == "done" and "#7" in ok[3]["sub"]
    stale = workflow_steps(_data(rates=rates, latest=_Snap(), changed=True), {}, None, [])
    assert stale[3]["state"] == "doing"
    assert "ยืนยันใหม่" in stale[3]["sub"], stale[3]


def test_progress_counts_only_finished_steps():
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    steps = workflow_steps(_data(rates=rates), {}, None, [])
    assert sum(1 for s in steps if s["state"] == "done") == 3


def test_invalid_receipt_link_does_not_count_as_finished():
    rates = {lv: {k: 100 for k, _n, _b in ITEMS} for lv in LV9}
    bad = workflow_steps(_data(rates=rates), {}, None, [{"valid": False}])
    good = workflow_steps(_data(rates=rates), {}, None, [{"valid": True}])
    assert bad[5]["state"] != "done" and good[5]["state"] == "done"


# ---------------------------------------------- รอบ DMC ที่ใช้ร่วมกันสองภาคเรียน
def test_june_round_is_shared_between_both_terms_of_the_same_year():
    jun = _scan(2569, "jun", {})
    assert shared_term(jun, 2569, 1) == (2569, 2)
    assert shared_term(jun, 2569, 2) == (2569, 1)


def test_november_round_is_shared_with_next_years_first_term():
    nov = _scan(2568, "nov", {})
    assert shared_term(nov, 2569, 1) == (2568, 2)
    assert shared_term(nov, 2568, 2) == (2569, 1)


def test_every_round_really_is_used_by_exactly_two_terms():
    """กันไว้: ถ้าสูตรรอบ DMC เปลี่ยน คำเตือนว่าใช้ร่วมกันต้องไม่กลายเป็นคำโกหก"""
    for ay in (2568, 2569, 2570):
        for term in (1, 2):
            for year, rnd in rounds(ay, term):
                scan = _scan(year, rnd, {})
                other = shared_term(scan, ay, term)
                assert other is not None, (ay, term, year, rnd)
                assert (year, rnd) in rounds(*other)


def test_page_warns_before_editing_a_shared_round():
    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    assert "shared_rounds.get(scan.key)" in html
    assert "ใช้ร่วมกับ" in html
    css = (ROOT / "app" / "static" / "subsidy.css").read_text(encoding="utf-8")
    assert ".sub-shared" in css and ".sub-step.doing" in css


# ------------------------------- ถามย้ำเรื่องระดับชั้น ก่อนบันทึกยอดนักเรียน
def test_save_asks_to_check_levels_only_when_counts_were_touched():
    js = (ROOT / "app" / "static" / "subsidy.js").read_text(encoding="utf-8")
    assert "censusTouched" in js, "ต้องรู้ว่าแตะยอด DMC หรือยัง"
    assert "โปรดตรวจสอบระดับชั้นของนักเรียน ณ วันที่" in js
    # ยกเลิกแล้วต้องไม่บันทึก และยังถือว่ามีข้อมูลค้างอยู่
    submit = js[js.index("form.addEventListener('submit'"):]
    submit = submit[:submit.index("});") + 3]
    assert "preventDefault" in submit and "return;" in submit, submit
    assert submit.index("preventDefault") < submit.index("dirty=false"), "ยกเลิกแล้วห้ามล้างสถานะค้าง"
    # ปุ่มเติมช่องว่างก็เปลี่ยนยอด DMC จึงต้องถามย้ำด้วย
    fill = js[js.index("[data-fill]"):]
    assert "censusTouched=true" in fill[:fill.index("copy-rates")]


def test_confirm_text_carries_the_survey_dates_and_the_shift_example():
    html = (ROOT / "app" / "templates" / "finance_subsidy.html").read_text(encoding="utf-8")
    assert "'surveys':s.census|map(attribute='label')|list" in html
    assert "'shifts':advance_pairs" in html
    router = (ROOT / "app" / "routers" / "subsidy.py").read_text(encoding="utf-8")
    assert "advance_pairs" in router


def test_shift_example_matches_the_rule_actually_used():
    """ตัวอย่างในกล่องยืนยันต้องมาจากสูตรจริง ไม่ใช่ข้อความตายตัวที่อาจไม่ตรง"""
    from app.services.subsidy import advance_source
    pairs = [(advance_source(lv, 1), lv) for lv in LV9]
    shifted = [(a, b) for a, b in pairs if a != b]
    assert shifted, "เทอม 1 ต้องมีชั้นที่เลื่อนฐานมา"
    for src, dest in shifted:
        assert src != dest and src[0] == dest[0]
    # ชั้นแรกของแต่ละช่วงใช้ฐานชั้นตัวเอง ไม่เลื่อน
    for lv in ("อ.1", "อ.2", "ป.1"):
        assert advance_source(lv, 1) == lv
    # เทอม 2 ไม่เลื่อนชั้นเลย
    assert all(advance_source(lv, 2) == lv for lv in LV9)
