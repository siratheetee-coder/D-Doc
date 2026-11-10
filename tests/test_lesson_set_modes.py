# -*- coding: utf-8 -*-
"""ชุดแผน 2 แบบ: แนบทีละแผน / แนบทั้งหน่วย (สร้างร่าง เพิ่มได้เรื่อย ๆ แล้วค่อยส่ง)

เจ้าของขอ: เลือกได้ 2 แบบ ค่าเริ่มต้นแนบทีละแผน เลขแผนนับต่อกันทั้งชุด
แบบทั้งหน่วยกรอกจำนวนแผนแล้วระบบไล่ "แผนที่ 1 ถึง 6" ให้
บันทึกหลังสอนทุกใบบอกว่าเป็นของแผนไหน หน่วยไหน และเขียนบนเส้นไข่ปลา
รัน: .venv/Scripts/python.exe -m pytest tests/test_lesson_set_modes.py
"""
from types import SimpleNamespace as O

from tests.test_lesson_after_note import _login_client, _DOCX, _CT_DOCX

MARK = "ทดสอบชุดแผน2แบบ_"


def _cleanup(db):
    from app.models import LessonPlan, Person
    for p in db.query(LessonPlan).filter(LessonPlan.title.like(MARK + "%")).all():
        db.delete(p)
    for q in db.query(Person).filter(Person.name.like(MARK + "%")).all():
        db.delete(q)
    db.commit()


def _files(*names):
    return [("file", (n + ".docx", _DOCX, _CT_DOCX)) for n in names]


def test_plan_mode_numbers_plans_across_units_and_sends_once_complete():
    from app.tenancy import session_for
    from app.models import LessonPlan, Person
    from app.services import lesson_set
    db = session_for(1)
    t = Person(name=MARK + "ครู", position="ครู"); db.add(t); db.commit()
    c = _login_client(person_id=t.id)
    try:
        r = c.post("/academic/lesson-plans/new", data={"title": MARK + "ไทย ป.4", "term": "1"},
                   follow_redirects=False)
        assert "/units" in r.headers["location"]
        p = db.query(LessonPlan).filter(LessonPlan.title.like(MARK + "%")).one()
        assert p.mode == "plan" and p.status == "draft", "ค่าเริ่มต้นต้องเป็นแนบทีละแผน และยังไม่ส่ง"
        pid = p.id
        # ส่งตอนยังไม่มีแผนไม่ได้
        r = c.post(f"/academic/lesson-plans/{pid}/send", follow_redirects=False)
        assert "err=" in r.headers["location"]
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_name": "การอ่าน"},
               files=_files("อ่านคำ", "อ่านเรื่อง"))
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_name": "การเขียน"},
               files=_files("เขียนเล่าเรื่อง"))
        # เพิ่มแผนเข้าหน่วยที่ 1 ทีหลัง ต้องแทรกเป็นแผนที่ 3 แล้วหน่วยที่ 2 เลื่อนเป็นแผนที่ 4
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_no": "1"}, files=_files("สรุปใจความ"))
        db.expire_all(); p = db.get(LessonPlan, pid)
        got = [(r.unit_no, r.seq, r.name) for r in sorted(p.units_rows, key=lambda r: r.seq)]
        assert got == [(1, 1, "อ่านคำ"), (1, 2, "อ่านเรื่อง"), (1, 3, "สรุปใจความ"), (2, 4, "เขียนเล่าเรื่อง")], got
        assert lesson_set.row_title(p, p.units_rows[3]) == "แผนที่ 4 เรื่อง เขียนเล่าเรื่อง หน่วยที่ 2 การเขียน"
        # หน้าชุดแผนเห็นทั้ง 2 หน่วย
        html = c.get(f"/academic/lesson-plans/{pid}/units").text
        assert "หน่วยที่ 2" in html and "แผนที่ 4" in html and "เพิ่มแผนในหน่วยนี้" in html
        # ส่งแล้วแก้ไม่ได้
        r = c.post(f"/academic/lesson-plans/{pid}/send", follow_redirects=False)
        assert "err=" not in r.headers["location"], r.headers["location"]
        db.expire_all()
        assert db.get(LessonPlan, pid).status == "pending"
        r = c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_no": "1"},
                   files=_files("แอบเพิ่ม"), follow_redirects=False)
        assert "err=" in r.headers["location"], "ส่งตรวจแล้วต้องเพิ่มแผนไม่ได้"
    finally:
        _cleanup(db)


def test_deleting_the_only_plan_of_a_unit_renumbers_units():
    from app.tenancy import session_for
    from app.models import LessonPlan, Person
    db = session_for(1)
    t = Person(name=MARK + "ครูลบ", position="ครู"); db.add(t); db.commit()
    c = _login_client(person_id=t.id)
    try:
        c.post("/academic/lesson-plans/new", data={"title": MARK + "ลบ", "term": "1"})
        p = db.query(LessonPlan).filter(LessonPlan.title == MARK + "ลบ").one(); pid = p.id
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_name": "ก"}, files=_files("a"))
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"unit_name": "ข"}, files=_files("b"))
        db.expire_all(); p = db.get(LessonPlan, pid)
        first = [r for r in p.units_rows if r.unit_no == 1][0]
        c.post(f"/academic/lesson-plans/{pid}/set/{first.id}/delete")
        db.expire_all(); p = db.get(LessonPlan, pid)
        assert [(r.unit_no, r.seq, r.unit_name) for r in p.units_rows] == [(1, 1, "ข")]
    finally:
        _cleanup(db)


def test_unit_mode_counts_plans_into_ranges():
    from app.tenancy import session_for
    from app.models import LessonPlan, Person
    from app.services import lesson_set
    db = session_for(1)
    t = Person(name=MARK + "ครูหน่วย", position="ครู"); db.add(t); db.commit()
    c = _login_client(person_id=t.id)
    try:
        c.post("/academic/lesson-plans/new", data={"title": MARK + "หน่วย", "term": "1", "mode": "unit"})
        p = db.query(LessonPlan).filter(LessonPlan.title == MARK + "หน่วย").one(); pid = p.id
        assert p.mode == "unit"
        c.post(f"/academic/lesson-plans/{pid}/set/add",
               data={"name": "การอ่าน", "hours": "12", "plan_count": "6"}, files=_files("u1"))
        c.post(f"/academic/lesson-plans/{pid}/set/add",
               data={"name": "การเขียน", "hours": "8", "plan_count": "4"}, files=_files("u2"))
        db.expire_all(); p = db.get(LessonPlan, pid)
        rs = sorted(p.units_rows, key=lambda r: r.seq)
        rng = lesson_set.unit_ranges(p)
        assert rng[rs[0].id] == (1, 6) and rng[rs[1].id] == (7, 10)
        assert lesson_set.row_title(p, rs[1]) == "หน่วยที่ 2 การเขียน (แผนที่ 7 ถึง 10)"
        html = c.get(f"/academic/lesson-plans/{pid}/units").text
        assert "แผนที่ 7 ถึง 10" in html
    finally:
        _cleanup(db)


def test_unit_ranges_stop_when_a_count_is_missing():
    """ไม่กรอกจำนวนแผนหน่วยหนึ่ง หน่วยถัดไปไล่เลขไม่ได้ ไม่ขึ้นเลขที่ผิด"""
    from app.services import lesson_set
    rows = [O(id=1, seq=1, plan_count=3), O(id=2, seq=2, plan_count=None), O(id=3, seq=3, plan_count=2)]
    plan = O(mode="unit", units_rows=rows)
    assert lesson_set.unit_ranges(plan) == {1: (1, 3)}


def test_reviewers_do_not_see_drafts():
    from app.tenancy import session_for
    from app.models import LessonPlan, Person
    db = session_for(1)
    t = Person(name=MARK + "ครูร่าง", position="ครู"); db.add(t); db.commit()
    try:
        db.add(LessonPlan(person_id=t.id, year=2569, title=MARK + "ร่างลับ", status="draft", mode="plan"))
        db.commit()
        y = db.query(LessonPlan).filter(LessonPlan.title == MARK + "ร่างลับ").one()
        c = _login_client(person_id=None)        # ผู้ตรวจ (ไม่ใช่ครู)
        html = c.get(f"/academic/lesson-plans?year={y.year}").text
        assert "แผนที่ครูส่งเข้ามา" in html
        assert MARK + "ร่างลับ" not in html
    finally:
        _cleanup(db)


def test_unit_mode_has_one_after_note_per_plan_and_locks_until_approved():
    """เจ้าของ: บันทึกหลังสอนต้องมีเท่าจำนวนแผน และก่อนอนุมัติต้องล็อก ไม่ใช่ฟอร์มที่กดแล้วไม่บันทึก"""
    from datetime import datetime
    from docx import Document
    from app.tenancy import session_for
    from app.models import LessonPlan, Person, LessonNote
    from app.services import lesson_set
    db = session_for(1)
    t = Person(name=MARK + "ครูรายแผน", position="ครู"); db.add(t); db.commit()
    c = _login_client(person_id=t.id)
    try:
        c.post("/academic/lesson-plans/new", data={"title": MARK + "รายแผน", "term": "1", "mode": "unit"})
        p = db.query(LessonPlan).filter(LessonPlan.title == MARK + "รายแผน").one(); pid = p.id
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"name": "การอ่าน", "plan_count": "3"}, files=_files("u1"))
        c.post(f"/academic/lesson-plans/{pid}/set/add", data={"name": "การเขียน", "plan_count": "2"}, files=_files("u2"))
        c.post(f"/academic/lesson-plans/{pid}/send")
        # ยังไม่อนุมัติ: ขึ้นล็อกครบ 5 ช่อง ไม่มีช่องพิมพ์
        html = c.get(f"/academic/lesson-plans/{pid}/units").text
        assert "บันทึกหลังสอนยังล็อกอยู่" in html and html.count("ล็อก รออนุมัติ") == 5
        assert 'name="k_text"' not in html
        db.expire_all(); p = db.get(LessonPlan, pid)
        labels = [s["label"] for s in lesson_set.slots(p)]
        assert labels == ["แผนที่ 1", "แผนที่ 2", "แผนที่ 3", "แผนที่ 4", "แผนที่ 5"], labels
        note = db.query(LessonNote).join(LessonNote.unit).filter_by(plan_id=pid).filter(LessonNote.seq == 2).first()
        assert note is not None
        r = c.post(f"/academic/lesson-plans/{pid}/notes/{note.id}/save", data={"k_text": "ก่อนอนุมัติ"},
                   follow_redirects=False)
        assert "err=" in r.headers["location"]
        # อนุมัติแล้ว: เขียนได้รายแผน
        p.status, p.director_at = "approved", datetime.now(); db.commit()
        html = c.get(f"/academic/lesson-plans/{pid}/units").text
        assert html.count('name="k_text"') == 5 and "ล็อก รออนุมัติ" not in html
        r = c.post(f"/academic/lesson-plans/{pid}/notes/{note.id}/save",
                   data={"name": "อ่านเรื่องสั้น", "k_text": "ผ่านเกณฑ์ 28 คน"}, follow_redirects=False)
        assert "err=" not in r.headers["location"]
        db.expire_all()
        assert db.get(LessonNote, note.id).k_text == "ผ่านเกณฑ์ 28 คน"
        r = c.get(f"/academic/lesson-plans/{pid}/after")
        import io
        d = Document(io.BytesIO(r.content))
        text = "\n".join(x.text for x in d.paragraphs)
        assert text.count("บันทึกหลังการจัดการเรียนรู้") == 5, "ต้องได้ 1 หน้าต่อ 1 แผน"
        assert "แผนที่ 2 เรื่อง อ่านเรื่องสั้น หน่วยที่ 1 การอ่าน" in text
        assert "แผนที่ 5 หน่วยที่ 2 การเขียน" in text
    finally:
        _cleanup(db)
