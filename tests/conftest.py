# -*- coding: utf-8 -*-
"""ตั้งค่ากลางของชุดทดสอบ

ระบบจำกัดจำนวนครั้งล็อกอินผิดต่อ IP ไว้ 5 นาที และเก็บไว้ในฐานข้อมูลจริง
เทสต์หลายไฟล์ล็อกอินจาก IP เดียวกัน (testclient) พอมีไฟล์ไหนทดสอบรหัสผ่านผิด
ไฟล์ถัด ๆ ไปในช่วง 5 นาทีจะโดน 429 Too Many Requests แล้วตกไปทั้งแถว
เป็นสาเหตุที่ผลเทสต์ไม่นิ่ง เดี๋ยวผ่านเดี๋ยวไม่ผ่าน · ล้างตัวนับก่อนทุกเทสต์
"""
import os

import pytest

os.environ.setdefault("DDOC_JOBS", "0")   # ไม่เปิดตัวจับเวลางานอัตโนมัติระหว่างเทสต์


def _clear_login_throttle():
    try:
        import app.accounts as ac
        db = ac.acc_session()
        try:
            db.query(ac.LoginFail).delete()
            db.commit()
        finally:
            db.close()
    except Exception:
        pass        # ยังไม่มีฐานข้อมูลบัญชีก็ไม่ต้องทำอะไร


@pytest.fixture(autouse=True)
def _no_form_guard(monkeypatch):
    """ด่านกันบอท (โทเคนเวลา + ช่องล่อ) ต้องเปิดหน้าก่อนส่งฟอร์ม · เทสต์ส่วนใหญ่ยิงฟอร์มตรง
    จึงปิดไว้ · เทสต์ของด่านเอง (test_form_guard.py) เปิดกลับเอง"""
    import app.services.form_guard as fg
    monkeypatch.setattr(fg, "ENABLED", False)


@pytest.fixture(autouse=True)
def _no_error_alert(monkeypatch):
    """เทสต์ที่ตั้งใจให้ขึ้น 500 ไม่ต้องเขียน error-log/ส่งอีเมล · test_error_alert.py เปิดกลับเอง"""
    monkeypatch.setenv("DDOC_ERROR_ALERT", "0")


@pytest.fixture(autouse=True)
def _no_login_throttle():
    _clear_login_throttle()
    yield
    _clear_login_throttle()


@pytest.fixture(autouse=True)
def _capture_dirs(monkeypatch, tmp_path_factory):
    """บางเทสต์เขียนหน้า HTML ไว้แคปภาพที่โฟลเดอร์จาก env *_CAPTURE
    ถ้าไม่ได้ตั้งไว้ (รันเทสต์ปกติ) ให้ชี้ไปโฟลเดอร์ชั่วคราว ไม่ให้ตกเพราะ KeyError"""
    import os
    names = ("ACADEMIC_HOME_CAPTURE", "FINANCE_DASH_CAPTURE", "DM_UI_CAPTURE", "SHARED_REPORT_CAPTURE",
             "LEDGER_CAPTURE", "LUNCH_FLOW_CAPTURE", "LUNCH_PICKER_CAPTURE", "PAY_DATE_CAPTURE",
             "CLAIM_CAPTURE", "PROJECT_DATES_CAPTURE", "QUICK_DATE_CAPTURE", "SCHOOL_EVENTS_CAPTURE")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        d = tmp_path_factory.mktemp("capture")
        for n in missing:
            monkeypatch.setenv(n, str(d))
