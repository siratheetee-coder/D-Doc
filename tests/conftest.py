# -*- coding: utf-8 -*-
"""ตั้งค่ากลางของชุดทดสอบ

ระบบจำกัดจำนวนครั้งล็อกอินผิดต่อ IP ไว้ 5 นาที และเก็บไว้ในฐานข้อมูลจริง
เทสต์หลายไฟล์ล็อกอินจาก IP เดียวกัน (testclient) พอมีไฟล์ไหนทดสอบรหัสผ่านผิด
ไฟล์ถัด ๆ ไปในช่วง 5 นาทีจะโดน 429 Too Many Requests แล้วตกไปทั้งแถว
เป็นสาเหตุที่ผลเทสต์ไม่นิ่ง เดี๋ยวผ่านเดี๋ยวไม่ผ่าน · ล้างตัวนับก่อนทุกเทสต์
"""
import pytest


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
def _no_login_throttle():
    _clear_login_throttle()
    yield
    _clear_login_throttle()
