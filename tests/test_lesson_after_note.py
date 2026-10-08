# -*- coding: utf-8 -*-
"""บันทึกหลังการจัดการเรียนรู้ ท้ายแผนแต่ละหน่วย

ครูอัปโหลดเฉพาะตัวแผน ระบบออกหน้าบันทึกหลังสอนให้หน่วยละหนึ่งหน้า พร้อมลายเซ็น
เพราะเป็นหน้าที่ระบบสร้างเอง ผอ. จึงลงนามครบทุกหน่วยด้วยคลิกเดียว
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_lesson_after_note.py
"""
import pathlib
from datetime import datetime

from docx import Document
from docx.oxml.ns import qn

from app.services.lesson_after_doc import render_after_notes

ROOT = pathlib.Path(__file__).resolve().parents[1]


class O:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _school():
    return O(name="บ้านหินลาด", address="", director_name="นายอัครเทพ ศรีวงศ์",
             director_position="ผู้อำนวยการโรงเรียน", academic_head_name="")


def _unit(seq=1, **over):
    base = dict(seq=seq, name=f"หน่วยทดสอบ {seq}", hours=12.0, k_text="", p_text="", a_text="",
                problem="", suggestion="", taught_at=None)
    base.update(over)
    return O(**base)


def _plan(units, **over):
    base = dict(id=1, title="รายวิชาคณิตศาสตร์ ค14101 ชั้นประถมศึกษาปีที่ 4",
                status="approved", director_at=datetime(2026, 8, 19),
                teacher=O(name="นายสิรธีร์ ดีเมืองจ้าย", position="ครู"), units_rows=units)
    base.update(over)
    return O(**base)


def _text(path):
    doc = Document(path)
    out = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            out += [c.text for c in row.cells]
    return "\n".join(out)


def test_form_sections_match_the_school_form():
    t = _text(render_after_notes(_plan([_unit()]), _school()))
    for want in ("บันทึกหลังการจัดการเรียนรู้", "ผลการจัดการเรียนรู้",
                 "ด้านความรู้ (Knowledge: K)", "ด้านกระบวนการ (Process: P)",
                 "ด้านคุณลักษณะอันพึงประสงค์และเจตคติ (Attitude: A)",
                 "ปัญหาและอุปสรรค", "ข้อเสนอแนะ / แนวทางแก้ไข",
                 "ครูผู้สอน", "ผู้อำนวยการโรงเรียน"):
        assert want in t, want


def test_one_page_per_unit():
    """แผนชุดหนึ่งมีหลายหน่วย ต้องได้บันทึกครบทุกหน่วย ไม่ใช่ใบเดียวรวม"""
    units = [_unit(1, name="จำนวนนับ"), _unit(2, name="การวัด"), _unit(3, name="เรขาคณิต")]
    doc = Document(render_after_notes(_plan(units), _school()))
    t = "\n".join(p.text for p in doc.paragraphs)
    for name in ("จำนวนนับ", "การวัด", "เรขาคณิต"):
        assert name in t, name
    assert t.count("บันทึกหลังการจัดการเรียนรู้") == 3
    breaks = doc.element.body.findall(".//" + qn("w:br"))
    assert sum(1 for b in breaks if b.get(qn("w:type")) == "page") == 2, "ต้องขึ้นหน้าใหม่ทุกหน่วย"


def test_typed_results_are_printed_and_blank_ones_leave_ruled_lines():
    filled = _unit(1, k_text="นักเรียนร้อยละ 85 ผ่านเกณฑ์", problem="ขาดสื่อของจริง",
                   suggestion="ยืมสื่อจากโรงเรียนใกล้เคียง", taught_at=datetime(2026, 8, 17))
    path = render_after_notes(_plan([filled, _unit(2)]), _school())
    t = _text(path)
    assert "นักเรียนร้อยละ 85 ผ่านเกณฑ์" in t
    assert "ขาดสื่อของจริง" in t and "ยืมสื่อจากโรงเรียนใกล้เคียง" in t
    # หน่วยที่ยังไม่กรอก ต้องมีเส้นบรรทัดให้เขียนมือ
    doc = Document(path)
    rules = doc.element.body.findall(".//" + qn("w:pBdr"))
    assert len(rules) >= 5, f"หน่วยที่ยังว่างต้องมีเส้นบรรทัด ได้ {len(rules)}"


def test_director_signature_appears_only_after_approval():
    waiting = _plan([_unit()], status="director", director_at=None)
    assert "นายอัครเทพ ศรีวงศ์" not in _text(render_after_notes(waiting, _school()))
    assert "นายอัครเทพ ศรีวงศ์" in _text(render_after_notes(_plan([_unit()]), _school()))


def test_teacher_signature_waits_until_the_result_is_recorded():
    """หน้าที่ยังว่าง ต้องไม่มีใครเซ็นค้างไว้ ไม่งั้นเท่ากับเซ็นกระดาษเปล่า"""
    blank = _text(render_after_notes(_plan([_unit()]), _school()))
    assert "นายสิรธีร์ ดีเมืองจ้าย" not in blank
    done = _text(render_after_notes(_plan([_unit(1, k_text="ผ่านเกณฑ์ทุกคน")]), _school()))
    assert "นายสิรธีร์ ดีเมืองจ้าย" in done


def test_signatures_float_in_front_of_text(monkeypatch, tmp_path):
    from PIL import Image
    png = tmp_path / "sig.png"
    Image.new("RGBA", (300, 100), (0, 0, 0, 255)).save(png)
    import app.services.signature as S
    monkeypatch.setattr(S, "signature_path_for_current", lambda name: str(png))

    doc = Document(render_after_notes(_plan([_unit(1, k_text="ผ่าน")]), _school()))
    anchors = doc.element.body.findall(".//" + qn("wp:anchor"))
    assert len(anchors) == 2, f"ครู + ผอ. = 2 ลายเซ็น ได้ {len(anchors)}"
    assert not doc.element.body.findall(".//" + qn("wp:inline")), "ลายเซ็นต้องไม่เป็น inline"
    for a in anchors:
        assert a.find(qn("wp:wrapNone")) is not None
        assert a.get("behindDoc") == "0"


def test_plan_without_units_does_not_crash():
    t = _text(render_after_notes(_plan([]), _school()))
    assert "ยังไม่มีหน่วยการเรียนรู้" in t


# ---------------- การต่อสาย ----------------
def test_routes_and_upload_limit_are_wired():
    acad = (ROOT / "app/routers/academic.py").read_text(encoding="utf-8")
    for want in ('"/academic/lesson-plans/{plan_id}/units"',
                 '"/academic/lesson-plans/{plan_id}/units/{unit_id}/save"',
                 '"/academic/lesson-plans/{plan_id}/after"',
                 "_PLAN_MAX"):
        assert want in acad, want
    assert "file: list[UploadFile]" in acad, "ฟอร์มส่งแผนยังรับไฟล์เดียว"
    html = (ROOT / "app/templates/academic_lesson_plans.html").read_text(encoding="utf-8")
    assert "multiple" in html, "ช่องแนบไฟล์ยังเลือกหลายไฟล์ไม่ได้"


def test_memo_table_follows_the_unit_rows_when_they_exist():
    """ครูแก้ชื่อหน่วยที่หน้าหน่วยการเรียนรู้แล้ว ตารางในบันทึกเสนอต้องตามไปด้วย"""
    from app.services.lesson_plan_doc import plan_units
    plan = _plan([_unit(1, name="ชื่อที่แก้ใหม่", hours=9.0)])
    plan.units = "หน่วยที่ 1 ชื่อเก่า (99 ชั่วโมง)"
    us = plan_units(plan)
    assert us == [{"no": 1, "name": "ชื่อที่แก้ใหม่", "hours": 9.0}]


# ---------------- เดินผ่าน HTTP จริง ----------------
def _login_client(person_id=None):
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "tester", "role": "owner", "tenant_id": 1,
        "display_name": "ผู้ทดสอบ", "must_change": False, "person_id": person_id,
    }
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {
        "is_owner": True, "modules": "", "active": True, "welcomed": True,
        "person_id": person_id}
    c = TestClient(app)
    r = c.post("/login", data={"username": "tester", "password": "x"}, follow_redirects=False)
    assert r.status_code in (302, 303), f"login ไม่ผ่าน: {r.status_code}"
    return c


_PDF = b"%PDF-1.4\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def test_whole_flow_over_http_upload_two_units_record_results_download():
    from app.tenancy import session_for
    from app.models import LessonPlan, LessonUnit, Person
    mark = "ทดสอบหน่วยแผน_"
    db = session_for(1)
    teacher = Person(name=mark + "ครูทดสอบ", position="ครู")
    db.add(teacher); db.commit()
    c = _login_client(person_id=teacher.id)

    def _clean():
        for p in db.query(LessonPlan).filter(LessonPlan.title.like(mark + "%")).all():
            db.delete(p)
        for q in db.query(Person).filter(Person.name.like(mark + "%")).all():
            db.delete(q)
        db.commit()

    try:
        r = c.post("/academic/lesson-plans/submit",
                   data={"title": mark + "คณิตศาสตร์ ป.4", "term": "1", "note": "",
                         "units": "หน่วยที่ 1 จำนวนนับ (12 ชั่วโมง)\nหน่วยที่ 2 การวัด (8 ชั่วโมง)"},
                   files=[("file", ("u1.pdf", _PDF, "application/pdf")),
                          ("file", ("u2.pdf", _PDF, "application/pdf"))],
                   follow_redirects=False)
        assert r.status_code in (302, 303) and "err=" not in r.headers.get("location", ""), \
            r.headers.get("location")
        plan = db.query(LessonPlan).filter(LessonPlan.title.like(mark + "%")).first()
        assert plan is not None
        rows = db.query(LessonUnit).filter(LessonUnit.plan_id == plan.id).order_by(
            LessonUnit.seq).all()
        assert len(rows) == 2, "แนบสองไฟล์ต้องได้สองหน่วย"
        assert rows[0].name == "จำนวนนับ" and rows[0].hours == 12
        assert rows[1].name == "การวัด", rows[1].name
        assert rows[0].file_blob == _PDF, "ไฟล์แผนของหน่วยต้องถูกเก็บแยกรายหน่วย"

        # หน้าหน่วยการเรียนรู้เปิดได้
        r = c.get(f"/academic/lesson-plans/{plan.id}/units")
        assert r.status_code == 200 and "บันทึกหลังการจัดการเรียนรู้" in r.text

        # ครูกรอกผลหน่วยที่ 1
        r = c.post(f"/academic/lesson-plans/{plan.id}/units/{rows[0].id}/save",
                   data={"name": "จำนวนนับ", "hours": "12", "taught_at": "17/08/2569",
                         "k_text": "นักเรียนร้อยละ 85 ผ่านเกณฑ์", "p_text": "", "a_text": "",
                         "problem": "ขาดสื่อของจริง", "suggestion": "ยืมจากโรงเรียนใกล้เคียง"},
                   follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code
        db.expire_all()
        u = db.get(LessonUnit, rows[0].id)
        assert u.k_text == "นักเรียนร้อยละ 85 ผ่านเกณฑ์"
        assert u.taught_at is not None and u.taught_at.year == 2026, u.taught_at
        assert u.result_at is not None

        # ดาวน์โหลดบันทึกหลังสอน (ทุกหน่วย และเฉพาะหน่วย)
        for url in (f"/academic/lesson-plans/{plan.id}/after",
                    f"/academic/lesson-plans/{plan.id}/after?unit={rows[0].id}"):
            r = c.get(url)
            assert r.status_code == 200 and r.content[:2] == b"PK", url

        # ไฟล์แผนรายหน่วยเปิดได้
        r = c.get(f"/academic/lesson-plans/{plan.id}/units/{rows[1].id}/file")
        assert r.status_code == 200 and r.content == _PDF
    finally:
        _clean()
        db.close()


def test_oversized_plan_file_is_rejected_with_a_clear_message():
    from app.tenancy import session_for
    from app.models import LessonPlan, Person
    mark = "ทดสอบไฟล์ใหญ่_"
    db = session_for(1)
    teacher = Person(name=mark + "ครู", position="ครู")
    db.add(teacher); db.commit()
    c = _login_client(person_id=teacher.id)
    try:
        big = _PDF + b"0" * (11 * 1024 * 1024)
        r = c.post("/academic/lesson-plans/submit",
                   data={"title": mark + "แผนใหญ่", "term": "1", "note": "", "units": ""},
                   files=[("file", ("big.pdf", big, "application/pdf"))],
                   follow_redirects=False)
        assert r.status_code in (302, 303)
        assert "err=" in r.headers.get("location", ""), "ไฟล์เกินเพดานต้องไม่ผ่าน"
        assert db.query(LessonPlan).filter(LessonPlan.title.like(mark + "%")).first() is None
    finally:
        for q in db.query(Person).filter(Person.name.like(mark + "%")).all():
            db.delete(q)
        db.commit()
        db.close()
