"""งานอาหารกลางวัน: ผู้รับจ้างจด VAT -> ถอด VAT ก่อนคิดภาษีหัก ณ ที่จ่าย"""
from types import SimpleNamespace
from app.services.lunch_meals import vat_split


def test_no_vat_uses_full_amount():
    assert vat_split(SimpleNamespace(vat_include=False), 10700) == (0.0, 10700.0)


def test_vat_registered_strips_vat_first():
    vat, base = vat_split(SimpleNamespace(vat_include=True), 10700)
    assert base == 10000.0 and vat == 700.0
    assert round(base * 0.01, 2) == 100.0
