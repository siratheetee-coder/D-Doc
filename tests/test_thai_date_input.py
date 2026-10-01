# -*- coding: utf-8 -*-
"""ช่องวันที่ต้องรับสิ่งที่ครูพิมพ์จริงได้ ไม่ใช่เด้ง "กรอกวันที่ให้ครบ" ซ้ำ ๆ

รัน: .venv\Scripts\python.exe -m pytest tests/test_thai_date_input.py
"""
from datetime import datetime

import pytest

from app.thai_utils import parse_be_date, thai_month_number


@pytest.mark.parametrize("text", [
    "02/10/2569", "2/10/2569", "02-10-2569", "02102569", "2102569",
    "1 ตุลาคม 2569"[0:0] + "02 ตุลาคม 2569", "2 ต.ค. 2569", "02 ตค 2569",
    "2569-10-02", "2026-10-02",
])
def test_formats_people_actually_type(text):
    assert parse_be_date(text) == datetime(2026, 10, 2)


@pytest.mark.parametrize("text", ["", "   ", "ตุลาคม", "32/10/2569", "02/13/2569", "สองตุลา"])
def test_rejects_what_it_cannot_read(text):
    assert parse_be_date(text) is None


def test_two_digit_year_is_not_guessed():
    """ช่องวันเกิดก็ใช้ฟังก์ชันนี้ เดาปี 2 หลักผิดแล้วข้อมูลเพี้ยนเงียบ ๆ"""
    assert parse_be_date("02/10/69") is None


def test_month_names():
    assert thai_month_number("มกราคม") == 1
    assert thai_month_number("ธ.ค.") == 12
    assert thai_month_number("กย") == 9
    assert thai_month_number("ไม่ใช่เดือน") is None
