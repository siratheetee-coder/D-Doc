# -*- coding: utf-8 -*-
"""สมุดพกอนุบาล (สมุดรายงานประจำตัวนักเรียน ระดับปฐมวัย)

ตรวจ 3 เรื่อง
  1. ชุดตัวบ่งชี้ครบตามไฟล์ต้นฉบับ (อ.1/อ.2/อ.3 ด้านละ 10-10-10-20 ข้อ · ไม่ซ้ำกันข้ามชั้น)
  2. สรุประดับคุณภาพรายด้านจากผลรายข้อ
  3. เอกสารออกได้ครบทุกหน้าและมีข้อความสำคัญ (ตัวบ่งชี้ · ความเห็นครู · สรุป)
"""
from types import SimpleNamespace as NS

from app.services import kinder as kd


def test_indicator_sets_complete():
    assert set(kd.KINDER_LEVELS) == {"อ.1", "อ.2", "อ.3"}
    for level in kd.KINDER_LEVELS:
        counts = {k: len(kd.items_for(level, k)) for k, _, _ in kd.DOMAINS}
        assert counts == {"phys": 10, "emo": 10, "soc": 10, "intel": 20}, (level, counts)
        for key, _full, _short in kd.DOMAINS:
            nums = [n for n, _, _ in kd.items_for(level, key)]
            assert nums == list(range(1, len(nums) + 1))
    assert len(kd.HOME_ITEMS) == 10
    assert kd.is_kinder("อ.2") and not kd.is_kinder("ป.1")


def test_indicators_differ_by_age():
    """แต่ละช่วงอายุต้องมีตัวบ่งชี้ของตัวเอง ไม่ใช่ชุดเดียวใช้ทุกชั้น"""
    first = {lv: kd.items_for(lv, "phys")[0][2] for lv in kd.KINDER_LEVELS}
    assert len(set(first.values())) == 3, first
    # ตัวอย่างจากไฟล์จริง: 3 ขวบต่อบล็อก 8 ชิ้น · 4 ขวบต่อเป็นรูปง่าย ๆ
    assert "8 ชิ้น" in kd.items_for("อ.1", "phys")[6][2]
    assert "จินตนาการ" in kd.items_for("อ.2", "phys")[8][2]


def test_domain_average():
    assert kd.domain_average([3, 3, 3]) == 3
    assert kd.domain_average([3, 2, 2]) == 2          # 2.33 -> ปานกลาง
    assert kd.domain_average([3, 3, 2]) == 3          # 2.67 -> ดี
    assert kd.domain_average([1, 1, 2]) == 1
    assert kd.domain_average([]) == 0
    assert kd.domain_average([None, 3]) == 3          # ข้อที่ยังไม่ประเมินไม่ถ่วง


def test_render_book(tmp_path, monkeypatch):
    """ออกเอกสารจริงแล้วอ่านกลับมาตรวจข้อความ"""
    import app.database as dbm
    import app.services.kinder_book as kb
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(kb, "get_data_dir", lambda: tmp_path)

    school = NS(name="โรงเรียนบ้านตัวอย่าง", district="เมือง", province="สมมติ",
                area_office="ประถมศึกษาสมมติ เขต 1", director_name="นายเอนก ทดสอบ",
                director_position="ผู้อำนวยการโรงเรียน", logo=None)
    klass = NS(id=1, year=2569, level="อ.2", room="1", homeroom=NS(name="นางสาวครู ใจดี"),
               co_homeroom=None)
    student = NS(id=7, name="เด็กหญิงตัวอย่าง ทดสอบ", seq=3, student_no="4611",
                 student_id=None, klass=klass)
    klass.students = [student]

    res = {}
    for n, _g, _t in kd.items_for("อ.2", "phys"):
        res[(1, kd.code_of("phys", n))] = 3
        res[(2, kd.code_of("phys", n))] = 2
    notes = {"comments": {"1": {"phys": "ร่างกายแข็งแรงดี"}, "2": {}},
             "improve": {"1": "ควรฝึกการตัดกระดาษ", "2": ""},
             "summary": {"soc": 2}, "works": [{"date": "10/08/2569", "work": "วาดภาพระบายสี",
                                               "award": "ชนะเลิศ", "org": "โรงเรียน"}]}
    monkeypatch.setattr(kb, "_results_of", lambda db, aid: res)
    monkeypatch.setattr(kb, "_notes_of", lambda db, aid: notes)
    monkeypatch.setattr(kb, "_attendance", lambda *a, **k: None)   # ใช้ DB จริง ข้ามในเทสต์นี้
    monkeypatch.setattr(kb, "_personal", lambda *a, **k: None)

    path = kb.render_kinder_book(school, student, db=None)

    from docx import Document
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                text += "\n" + c.text
    assert "สมุดรายงานประจำตัวนักเรียน" in text
    assert "อบ.1/2" in text                       # แบบของอายุ 4 ขวบ
    assert "เด็กหญิงตัวอย่าง ทดสอบ" in text
    # ตัวบ่งชี้ต้องขึ้นครบทั้ง 4 ด้าน (50 ข้อ)
    for key, _full, _short in kd.DOMAINS:
        for _n, _g, body in kd.items_for("อ.2", key):
            assert body in text, body
    assert "ร่างกายแข็งแรงดี" in text and "ควรฝึกการตัดกระดาษ" in text
    assert "วาดภาพระบายสี" in text
    assert kd.HOME_ITEMS[0] in text               # หน้าผู้ปกครอง
    assert "นายเอนก ทดสอบ" in text                # ลงนามผู้บริหาร
