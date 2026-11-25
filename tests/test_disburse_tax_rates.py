# -*- coding: utf-8 -*-
"""ช่องเลือก VAT / % ภาษีหัก ณ ที่จ่าย ในบันทึกขอเบิก เดาโหมดจากตัวเลขเดิมได้ถูก"""
import re


def _sel(a, v, w):
    from app.templating import templates
    h = templates.env.get_template("_finance_tax_rates.html").render(amt_v=a, vat_v=v, wht_v=w)
    return re.findall(r'<option value="(\w+)" selected', h)


def test_guess_modes_from_saved_numbers():
    assert _sel(18120, 1185.42, 508.04) == ["include", "3"]
    assert _sel(18120, 0, 181.2) == ["none", "1"]
    assert _sel(500, 0, 0) == ["none", "0"]
    assert _sel(1000, 50, 7) == ["manual", "manual"]
