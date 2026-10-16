# -*- coding: utf-8 -*-
"""คอนโซล "ใครกำลังใช้งาน": หน้าล่าสุดต้องเป็นหน้าที่ผู้ใช้เปิดจริง
เคยพัง: แชทเช็กข้อความทุก 15 วิ ทุกคนเลยขึ้นว่าอยู่หน้า /support/chat/messages
รัน: .venv\Scripts\python.exe -m pytest tests/test_last_seen.py
"""
from tests.test_subsidy import env  # noqa: F401  (fixture)

HTML = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


def _last(username="demo"):
    from app.accounts import acc_session, Account
    db = acc_session()
    try:
        a = db.query(Account).filter_by(username=username).one()
        return a.last_path, a.last_seen_at
    finally:
        db.close()


def test_background_polls_do_not_replace_the_page(env, monkeypatch):
    import app.accounts as ac
    monkeypatch.setattr(ac, "_seen_cache", {})
    monkeypatch.setattr(ac, "_seen_page", {})
    env.get("/procurement", headers=HTML)
    assert _last()[0] == "/procurement"
    ac._seen_cache.clear()                           # ครบนาที -> รอบนี้เขียนจริง แต่เป็นแชทเช็กข้อความ
    env.get("/support/chat/messages")
    path, seen = _last()
    assert path == "/procurement" and seen is not None, "ยังออนไลน์ แต่หน้าที่ทำงานยังเป็นงานพัสดุ"
    env.get("/finance", headers=HTML)                # เปิดหน้าใหม่ภายในนาทีเดียวกัน (ยังไม่เขียน)
    ac._seen_cache.clear()
    env.get("/support/chat/messages")                # รอบเขียนถัดไปใช้หน้าล่าสุดที่เปิดจริง
    assert _last()[0] == "/finance"
