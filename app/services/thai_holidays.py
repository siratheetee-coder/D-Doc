# -*- coding: utf-8 -*-
"""
thai_holidays.py
----------------
ปฏิทินวันหยุดราชการไทย (ใช้ไลบรารี holidays ที่ทำงานออฟไลน์)
- รองรับวันหยุดที่เลื่อนตามจันทรคติ (มาฆบูชา/วิสาขบูชา/อาสาฬหบูชา/เข้าพรรษา)
- รวมวันหยุดชดเชย (เสาร์/อาทิตย์ -> เลื่อนวันทำการถัดไป)

ใช้สำหรับเตือนผู้ใช้เมื่อกรอกวันที่ลงนามเอกสารตรงกับวันหยุด
(วันราชการหยุด -> โดยทั่วไปไม่ลงนาม/ส่งมอบในวันนั้น)
"""
from datetime import date, datetime

try:
    import holidays as _holidays_lib
    _HAS_LIB = True
except ImportError:          # เผื่อยังไม่ได้ติดตั้ง -> เตือนเฉพาะเสาร์/อาทิตย์
    _HAS_LIB = False

_THAI_DOW = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี",
             "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]


def holiday_map(years) -> dict:
    """คืน dict {ISO date (ค.ศ.): ชื่อวันหยุด} สำหรับปี ค.ศ. ที่ระบุ
    เช่น {'2026-04-13': 'วันสงกรานต์', ...}"""
    if not _HAS_LIB:
        return {}
    th = _holidays_lib.Thailand(years=list(years), language="th")
    return {d.isoformat(): name for d, name in th.items()}


def check_date(dt) -> dict | None:
    """ตรวจวันเดียว: คืน None ถ้าเป็นวันทำการปกติ
    หรือ dict {'type': 'weekend'|'holiday', 'label': ...} ถ้าเป็นวันหยุด
    """
    if not dt:
        return None
    if isinstance(dt, datetime):
        dt = dt.date()
    # เสาร์ (5) / อาทิตย์ (6)
    if dt.weekday() >= 5:
        return {"type": "weekend", "label": _THAI_DOW[dt.weekday()]}
    if _HAS_LIB:
        th = _holidays_lib.Thailand(years=[dt.year], language="th")
        if dt in th:
            return {"type": "holiday", "label": th[dt]}
    return None


def year_range_for(*dts) -> list:
    """หาเซตปี ค.ศ. ที่ต้องเตรียมปฏิทิน จากวันที่ที่เกี่ยวข้อง (เผื่อ +/-1 ปี)"""
    years = set()
    for dt in dts:
        if dt:
            y = dt.year if isinstance(dt, (date, datetime)) else None
            if y:
                years.update([y - 1, y, y + 1])
    if not years:
        now = datetime.now().year
        years = {now - 1, now, now + 1, now + 2}
    return sorted(years)
