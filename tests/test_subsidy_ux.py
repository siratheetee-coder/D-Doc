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
