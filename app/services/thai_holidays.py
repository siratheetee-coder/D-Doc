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
from datetime import date, datetime, timedelta

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


def is_workday(dt, holiday_iso=None) -> bool:
    """วันทำการหรือไม่ (จันทร์-ศุกร์ และไม่ใช่วันหยุดราชการ)
    holiday_iso = set ของ ISO date (ค.ศ.) วันหยุด · None = ตรวจจากไลบรารีเอง"""
    if isinstance(dt, datetime):
        dt = dt.date()
    if dt.weekday() >= 5:
        return False
    if holiday_iso is not None:
        return dt.isoformat() not in holiday_iso
    return check_date(dt) is None


def next_workday(dt, holiday_iso=None):
    """วันทำการแรกตั้งแต่ dt เป็นต้นไป (รวม dt ถ้าเป็นวันทำการ)"""
    if isinstance(dt, datetime):
        dt = dt.date()
    while not is_workday(dt, holiday_iso):
        dt += timedelta(days=1)
    return dt


def add_working_days(start, n, holiday_iso=None):
    """คืนวันสุดท้าย (นับรวม) ที่ทำให้มีวันทำการครบ n วัน เริ่มจากวันทำการแรก >= start"""
    if not start or n <= 0:
        return None
    d = next_workday(start, holiday_iso)
    cnt, last = 1, d
    while cnt < n:
        d += timedelta(days=1)
        if is_workday(d, holiday_iso):
            cnt += 1
            last = d
    return last


def generate_installment_ranges(start, n_inst, days_each, holiday_iso=None):
    """แบ่งงวดอัตโนมัติ: คืน [(start_i, end_i), ...] ช่วงวันทำการต่อเนื่อง ไม่นับวันหยุด
    งวดถัดไปเริ่มวันทำการถัดจากวันสิ้นสุดงวดก่อน"""
    ranges = []
    if not start or n_inst <= 0 or days_each <= 0:
        return ranges
    cur = next_workday(start, holiday_iso)
    for _ in range(n_inst):
        end = add_working_days(cur, days_each, holiday_iso)
        if not end:
            break
        ranges.append((cur, end))
        cur = next_workday(end + timedelta(days=1), holiday_iso)
    return ranges


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
