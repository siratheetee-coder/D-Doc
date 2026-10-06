# -*- coding: utf-8 -*-
"""ตัวช่วยตอนงบกระทบยอดไม่ตรง ต้องชี้เป้าให้ถูก ไม่ใช่บอกลอย ๆ ว่าไม่ตรง

กฎอยู่ใน app/static/recon_hints.js เพราะต้องคิดสดระหว่างพิมพ์บนหน้าจอ
เทสต์นี้รันไฟล์นั้นด้วย node จริง จะได้ไม่ใช่เทสต์ที่อ่านแค่ว่ามีข้อความอยู่ในไฟล์
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_recon_hints.py
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "recon_hints.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันกฎฝั่งหน้าจอ")


def hints(**payload):
    runner = (
        "const f = require(process.argv[1]);"
        "const input = JSON.parse(process.argv[2]);"
        "process.stdout.write(JSON.stringify(f(input)));"
    )
    r = subprocess.run([NODE, "-e", runner, str(SCRIPT), json.dumps(payload)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _check(amount, payee="ร้านทดสอบ", cleared=False, no="", on=""):
    return {"amount": amount, "payee": payee, "cleared": cleared, "no": no, "on": on}


def test_balanced_books_get_no_nagging():
    assert hints(diff=0) == []
    assert hints(diff=0.001) == []


def test_difference_equal_to_one_payment_names_that_payment():
    out = hints(diff=3200, checks=[_check(1800, "ร้าน ก"), _check(3200, "ร้าน ข", no="0012345")])
    assert out[0]["kind"] == "check"
    assert "ร้าน ข" in out[0]["text"] and "0012345" in out[0]["text"]
    assert "3,200.00" in out[0]["text"]


def test_a_cleared_payment_is_described_differently_from_an_open_one():
    opened = hints(diff=500, checks=[_check(500, cleared=False)])[0]["text"]
    closed = hints(diff=500, checks=[_check(500, cleared=True)])[0]["text"]
    assert "ยังไม่ติ๊ก" in opened and "วันที่เงินออก" in closed


def test_dates_are_shown_as_thai_years_not_raw_iso():
    out = hints(diff=200, checks=[_check(200, "ร้าน ก", on="2026-09-05")])
    assert "5/09/2569" in out[0]["text"], out[0]["text"]
    assert "2026" not in out[0]["text"]


def test_double_of_a_payment_points_at_a_wrong_sign():
    out = hints(diff=-7000, checks=[_check(3500, "ร้านคูณสอง")])
    assert out[0]["kind"] == "check2"
    assert "สองเท่า" in out[0]["text"] and "ร้านคูณสอง" in out[0]["text"]


def test_difference_equal_to_a_deposit_names_that_deposit():
    out = hints(diff=63000, txns=[{"amount": 63000, "kind": "in", "note": "เงินอุดหนุนงวดแรก"}])
    assert out[0]["kind"] == "txn" and "เงินอุดหนุนงวดแรก" in out[0]["text"]
    assert "รับ" in out[0]["text"]


def test_unassigned_payments_are_the_first_thing_suggested():
    out = hints(diff=50, looseSum=50, checks=[_check(50, "บังเอิญเท่ากัน")])
    assert out[0]["kind"] == "loose"
    assert "ยังไม่ได้ระบุบัญชี" in out[0]["text"]


def test_transposed_digits_are_spotted_by_the_rule_of_nine():
    out = hints(diff=360)                     # 1,620 ลงเป็น 1,260
    assert out[0]["kind"] == "transpose"
    assert "สลับหลัก" in out[0]["text"]


def test_the_rule_of_nine_never_hides_a_real_match():
    out = hints(diff=360, checks=[_check(360, "ร้านตรงเป๊ะ")])
    assert [h["kind"] for h in out] == ["check"], out


def test_a_difference_with_no_lead_still_says_which_side_is_higher():
    high = hints(diff=1234.50)
    low = hints(diff=-1234.50)
    assert high[0]["kind"] == "none" and "ฝั่งธนาคารสูงกว่า" in high[0]["text"]
    assert low[0]["kind"] == "none" and "ฝั่งโรงเรียนสูงกว่า" in low[0]["text"]


def test_many_matches_are_capped_so_the_box_stays_readable():
    out = hints(diff=100, checks=[_check(100, f"ร้านที่ {i}") for i in range(20)])
    assert len(out) == 6


def test_satang_differences_are_not_rounded_away():
    out = hints(diff=0.25, checks=[_check(0.25, "เศษสตางค์")])
    assert out[0]["kind"] == "check" and "0.25" in out[0]["text"]


def test_the_page_loads_the_rules_and_has_a_place_to_show_them():
    html = (ROOT / "app" / "templates" / "finance_bank_recon.html").read_text(encoding="utf-8")
    assert "recon_hints.js" in html
    assert "data-recon-hints" in html
