# -*- coding: utf-8 -*-
"""หน้าเริ่มต้นใช้งานใน 10 นาที (/start) + การ์ดบนหน้าหลัก
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_quick_start.py
"""
import re

from tests.test_subsidy import env  # noqa: F401  (fixture)


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_every_listed_step_exists_in_module_checklists(env):
    """เปลี่ยนชื่อขั้นในรายการของงานไหนแล้วลืมแก้ที่นี่ = ขั้นนั้นหายจากหน้าเริ่มต้นเงียบ ๆ"""
    from app.models import School
    from app.services.quick_start import BASIC, CORE, module_setups
    db = _db()
    try:
        setups = module_setups(db, db.query(School).first(), set(CORE) | {"procurement", "hr"})
        names = {m: [s["title"] for s in st["steps"]] for m, st in setups.items()}
        for m, title, _ in BASIC:
            assert any(t.startswith(title) for t in names[m]), (m, title)
        for m, items in CORE.items():
            for title, _ in items:
                assert any(t.startswith(title) for t in names[m]), (m, title)
    finally:
        db.close()


def test_build_filters_modules_and_counts_minutes(env):
    from app.models import School
    from app.services.quick_start import build
    db = _db()
    try:
        school = db.query(School).first()
        fin = build(db, school, ["finance"])
        assert [s["key"] for s in fin["sections"]] == ["basic", "finance"]
        assert fin["total"] == 5 and fin["minutes_total"] == 7 and fin["minutes_left"] <= 7
        assert [r["key"] for r in fin["rest"]] == ["finance"]
        everything = build(db, school, [])
        assert [s["key"] for s in everything["sections"]][1:] == ["procurement", "admin", "finance", "lunch", "hr", "academic"]
        assert everything["minutes_total"] == 13
        titles = [s["title"] for sec in everything["sections"] for s in sec["steps"]]
        assert len(titles) == len(set(titles)), "ขั้นเดียวกันไม่ขึ้นซ้ำ"
        assert [s["n"] for sec in everything["sections"] for s in sec["steps"]] == list(range(1, len(titles) + 1))
    finally:
        db.close()


def test_page_hub_card_and_progress(env):
    html = env.get("/start").text
    assert "เริ่มต้นใช้งานใน 10 นาที" in html and "พื้นฐาน ใช้ร่วมกันทุกงาน" in html and "ทำต่อในแต่ละงาน" in html
    first = re.search(r'id="next".*?<a class="btn sm ?" href="([^"]+)"', html, re.S)
    assert first, "มีขั้นถัดไปพร้อมปุ่ม"
    hub = env.get("/").text
    assert 'href="/start"' in hub and "เริ่มต้นใช้งานใน 10 นาที" in hub
    # ทำขั้นบุคลากรแล้ว ระบบติ๊กให้เอง
    from app.models import Person
    db = _db()
    try:
        for i in range(3):
            db.add(Person(name=f"ครูทดสอบ {i}", position="ครู"))
        db.commit()
    finally:
        db.close()
    html = env.get("/start").text
    step = re.search(r'<li class="qs-step ([^"]*)"[^>]*>\s*<span class="qs-mark">[^<]*</span>\s*<div class="qs-body">\s*'
                     r'<div class="qs-name">เพิ่มรายชื่อบุคลากร', html)
    assert step and "is-done" in step.group(1)


def test_teacher_account_goes_to_academic(env):
    from app.routers.pages import quick_start_page

    class R:
        session = {"person_id": 5}
    r = quick_start_page(R(), db=None)
    assert r.status_code == 303 and r.headers["location"] == "/academic"
