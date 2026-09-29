"""
ทดสอบการคำนวณผลการเรียน (ประถม 2 ภาค -> เกรดรายปี) ครบวงจร
- เกรดคิดอัตโนมัติต้องคิดใหม่เมื่อคะแนนเปลี่ยน (เดิมหน้ากรอก pre-select เกรดเก่า -> เกรดล็อกค้าง)
- เกรดที่ครูเลือกเอง (ร/มส) คงไว้ และส่งผลถึงเกรดรายปี
- เกรดรายปี = เฉลี่ย "ร้อยละ" 2 ภาค (คะแนนเต็มแต่ละภาคต่างกันได้)
- แก้ชิ้นงาน (คะแนนเต็ม/ลบชิ้น) -> คะแนนรวม เกรด เกรดรายปี คิดใหม่ทันที
- ปพ.6 ประถม GPA ถ่วงด้วยเวลาเรียน (ตรงกับ ปพ.5)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_grade_calc.py
"""
import re
import zipfile

from tests.test_assignments import _login, _db, _cleanup, MARK
from app.models import AcadClass, AcadStudent, AcadSubject, AcadScore, AcadAssignment


def _setup(db, level="ป.1"):
    cls = AcadClass(year=2567, level=level, room="9", note=MARK + "calc")
    db.add(cls); db.commit()
    st = AcadStudent(class_id=cls.id, seq=1, name=MARK + "ก", sex="M")
    db.add(st); db.commit()
    sub = AcadSubject(year=2567, level=level, code="ท11101", name=MARK + "ไทย",
                      hours=200, term=0, seq=1)
    db.add(sub); db.commit()
    return cls, st, sub


def _page(c, cls, sub, term):
    return c.get(f"/academic/grades?cid={cls.id}&sid={sub.id}&term={term}&year=2567").text


def _form_from(html):
    """จำลองเบราว์เซอร์: ส่งทุกช่องตามค่าที่หน้าเติมไว้ให้"""
    d = {}
    for n, v in re.findall(r'<input name="((?:item|fin)_[^"]+)" value="([^"]*)"', html):
        d[n] = v
    for name, body in re.findall(r'<select name="(grade_\d+)"[^>]*>(.*?)</select>', html, re.S):
        sel = re.search(r'<option value="([^"]*)" selected', body)
        d[name] = sel.group(1) if sel else ""
    return d


def _save(c, db, cls, st, sub, term, mid=None, fin=None, grade=None):
    html = _page(c, cls, sub, term)
    d = _form_from(html)
    m = db.query(AcadAssignment).filter_by(subject_id=sub.id, term=term, is_midterm=True).first()
    if mid is not None:
        d[f"item_{st.id}_{m.id}"] = str(mid)
    if fin is not None:
        d[f"fin_{st.id}"] = str(fin)
    if grade is not None:
        d[f"grade_{st.id}"] = grade
    c.post("/academic/grades/save", data={**d, "cid": cls.id, "sid": sub.id, "term": term})
    db.expire_all()


def _row(db, sub, term):
    return db.query(AcadScore).filter_by(subject_id=sub.id, term=term).first()


def test_auto_grade_follows_score_change():
    c = _login(); db = _db(); _cleanup(db)
    try:
        cls, st, sub = _setup(db)
        _save(c, db, cls, st, sub, 1, mid=30, fin=30)          # 60/60 = 100%
        assert _row(db, sub, 1).grade == "4"
        # หน้ากรอกต้องไม่ล็อกเกรดอัตโนมัติไว้ในช่องเลือก
        assert _form_from(_page(c, cls, sub, 1))[f"grade_{st.id}"] == ""
        _save(c, db, cls, st, sub, 1, mid=10, fin=10)          # 20/60 = 33%
        r = _row(db, sub, 1)
        assert r.grade == "0" and not r.grade_manual
    finally:
        _cleanup(db)


def test_manual_grade_kept_and_flows_to_annual():
    c = _login(); db = _db(); _cleanup(db)
    try:
        cls, st, sub = _setup(db)
        _save(c, db, cls, st, sub, 1, mid=30, fin=30, grade="ร")
        r = _row(db, sub, 1)
        assert r.grade == "ร" and r.grade_manual
        # หน้ากรอกยังเลือก ร ไว้ -> กดบันทึกซ้ำ (แก้คะแนน) ร ต้องไม่หาย
        assert _form_from(_page(c, cls, sub, 1))[f"grade_{st.id}"] == "ร"
        _save(c, db, cls, st, sub, 1, mid=25)
        assert _row(db, sub, 1).grade == "ร"
        # ยังไม่มีภาค 2 -> ยังสรุปรายปีไม่ได้ (ไม่ใช่ขึ้น ร เป็นผลรายปีก่อนเวลา)
        assert _row(db, sub, 0) is None or not _row(db, sub, 0).grade
        # ภาค 2 ได้เต็ม -> รายปีต้องเป็น ร (ไม่ใช่เอาคะแนนมาเฉลี่ยทับ)
        _save(c, db, cls, st, sub, 2, mid=30, fin=30)
        assert _row(db, sub, 0).grade == "ร"
        # ครูแก้ภาค 1 กลับเป็นคิดอัตโนมัติ -> รายปีกลับมาเฉลี่ยจากคะแนน
        _save(c, db, cls, st, sub, 1, grade="")
        a = _row(db, sub, 0)
        assert a.grade == "4" and a.score == round((55 / 60 * 100 + 100) / 2, 2)
    finally:
        _cleanup(db)


def test_annual_is_average_of_percent_with_different_full_marks():
    c = _login(); db = _db(); _cleanup(db)
    try:
        cls, st, sub = _setup(db)
        _save(c, db, cls, st, sub, 1, mid=24, fin=24)           # ภาค 1: 48/60 = 80%
        assert _row(db, sub, 0) is None or not _row(db, sub, 0).grade   # ยังไม่ครบ 2 ภาค
        # ภาค 2: กลางภาคเต็ม 70 -> เต็มรวม 100 · ได้ 60/100 = 60%
        m2 = db.query(AcadAssignment).filter_by(subject_id=sub.id, term=2).first()
        if m2 is None:
            _page(c, cls, sub, 2)
        c.post("/academic/assignments/save",
               data={"cid": cls.id, "sid": sub.id, "term": 2, "mid_max": "70"})
        _save(c, db, cls, st, sub, 2, mid=40, fin=20)
        a = _row(db, sub, 0)
        assert a.score == 70.0 and a.grade == "3"               # (80 + 60) / 2 = 70 -> 3
    finally:
        _cleanup(db)


def test_assignment_change_recalculates():
    c = _login(); db = _db(); _cleanup(db)
    try:
        cls, st, sub = _setup(db)
        _save(c, db, cls, st, sub, 1, mid=30, fin=30)           # 60/60 -> 4
        _save(c, db, cls, st, sub, 2, mid=30, fin=30)
        assert _row(db, sub, 0).grade == "4"
        # ขยายคะแนนเต็มกลางภาค ภาค 1 เป็น 90 -> 60/120 = 50% -> 1 · รายปี (50+100)/2 = 75 -> 3.5
        c.post("/academic/assignments/save",
               data={"cid": cls.id, "sid": sub.id, "term": 1, "mid_max": "90"})
        db.expire_all()
        assert _row(db, sub, 1).grade == "1"
        a = _row(db, sub, 0)
        assert a.score == 75.0 and a.grade == "3.5"
    finally:
        _cleanup(db)


def test_pp6_primary_gpa_weighted_by_hours():
    from app.services.acad_doc import render_pp6
    from app.routers.pages import get_school
    db = _db(); _cleanup(db)
    try:
        cls, st, sub = _setup(db)
        sub2 = AcadSubject(year=2567, level="ป.1", code="ศ11101", name=MARK + "ศิลปะ",
                           hours=40, term=0, seq=2)
        db.add(sub2); db.commit()
        db.add(AcadScore(acad_student_id=st.id, subject_id=sub.id, term=0, score=85, grade="4"))
        db.add(AcadScore(acad_student_id=st.id, subject_id=sub2.id, term=0, score=55, grade="1.5"))
        db.commit()
        xml = zipfile.ZipFile(render_pp6(get_school(db), st, db)).read("word/document.xml").decode()
        txt = re.sub(r"<[^>]+>", "", xml)
        # (4*200 + 1.5*40) / 240 = 3.58 · ถ้าเฉลี่ยตรง (ผิด) จะได้ 2.75
        assert "GPA): 3.58" in txt
    finally:
        _cleanup(db)
