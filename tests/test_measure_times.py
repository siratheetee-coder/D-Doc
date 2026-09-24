# -*- coding: utf-8 -*-
"""ชั่งน้ำหนัก/วัดส่วนสูง ภาคเรียนละ 2 ครั้ง (4 ครั้งต่อปี)

แบบบันทึกของทางราชการให้ช่องชั่งภาคเรียนละ 2 ครั้ง เดิมระบบเก็บได้ภาคละครั้งเดียว
ตรวจ: ช่องเก็บครบ 4 · migration ฐานข้อมูลเก่าไม่ทำข้อมูลหาย · สรุปใช้ครั้งล่าสุด
"""
import datetime as dt

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from types import SimpleNamespace as NS

import app.database as dbm
from app.services import growth


def _legacy_engine(path):
    """ฐานข้อมูลรุ่นเก่า: student_measure ที่ UNIQUE = (student_id, year, term) ไม่มี times"""
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE student (id INTEGER PRIMARY KEY, name TEXT)")
        c.exec_driver_sql("""CREATE TABLE student_measure (
            id INTEGER NOT NULL, student_id INTEGER NOT NULL, year INTEGER NOT NULL,
            term INTEGER, date DATETIME, weight FLOAT, height FLOAT, created_at DATETIME,
            PRIMARY KEY (id), CONSTRAINT uq_student_measure UNIQUE (student_id, year, term),
            FOREIGN KEY(student_id) REFERENCES student (id))""")
        c.exec_driver_sql("INSERT INTO student VALUES (1,'เด็กเก่า')")
        c.exec_driver_sql("INSERT INTO student_measure (id,student_id,year,term,weight,height) "
                          "VALUES (1,1,2568,1,25.0,120.0),(2,1,2568,2,27.0,124.0)")
    return eng


def test_slots():
    assert growth.SLOTS == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert growth.slot_label((2, 1)) == "ภาคเรียนที่ 2 ครั้งที่ 1"


def test_migration_keeps_old_rows_and_allows_second_time(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    eng = _legacy_engine(tmp_path / "old.db")
    dbm.init_school_db(eng)

    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(student_measure)"))]
        assert "times" in cols
        rows = c.execute(text("SELECT term, times, weight FROM student_measure "
                              "ORDER BY term")).fetchall()
    assert rows == [(1, 1, 25.0), (2, 1, 27.0)], rows   # ของเดิม = ครั้งที่ 1 ไม่หาย

    # เดิมจะติด UNIQUE เพราะซ้ำ (student, year, term)
    with Session(bind=eng) as db:
        growth.set_measure(db, 1, 2568, 1, 26.0, 122.0, None, times=2)
        ms = growth.measures_for(db, 1, 2568)
    assert sorted(ms) == [(1, 1), (1, 2), (2, 1)]
    assert ms[(1, 2)].weight == 26.0

    dbm.init_school_db(eng)                              # รันซ้ำต้องไม่ทำข้อมูลหาย
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM student_measure")).scalar() == 3


def test_summary_uses_latest_measure():
    """สรุป/เฝ้าระวังต้องใช้ผลการชั่งครั้งล่าสุดของปี ไม่ใช่ครั้งสุดท้ายที่มีเลขเทอมสูงสุด"""
    res = {(1, 1): {"wh": "ผอม"}, (1, 2): {"wh": "ค่อนข้างผอม"},
           (2, 1): {"wh": "สมส่วน"}, (2, 2): None}
    assert growth.latest(res) == {"wh": "สมส่วน"}
    assert growth.wh_trend(res) == "up"                  # ผอม -> สมส่วน = ดีขึ้น
    assert growth.latest({sl: None for sl in growth.SLOTS}) is None
    assert growth.wh_trend({(1, 1): {"wh": "ผอม"}}) is None   # ชั่งครั้งเดียวเทียบไม่ได้


def test_documents_show_four_rows(tmp_path, monkeypatch):
    """ทั้งสมุดพกอนุบาลและ ปพ.6 ต้องมีช่องชั่งครบ 4 ครั้ง"""
    import app.services.kinder_book as kb
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(kb, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(kb, "_results_of", lambda db, aid: {})
    monkeypatch.setattr(kb, "_notes_of", lambda db, aid: {"comments": {}, "improve": {},
                                                          "summary": {}, "works": []})
    monkeypatch.setattr(kb, "_personal", lambda *a, **k: None)
    monkeypatch.setattr(growth, "measures_for", lambda db, sid, yr: {})

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    school = NS(name="รร.ทดสอบ", district="", province="", area_office="",
                director_name="", director_position="", logo=None)
    klass = NS(id=1, year=2569, level="อ.2", room="1", homeroom=None, co_homeroom=None)
    student = NS(id=1, name="เด็กชายทดสอบ ทดสอบ", seq=1, student_no="1",
                 student_id=5, klass=klass)
    klass.students = [student]
    db = NS(query=lambda *a, **k: _Q(), get=lambda *a, **k: None)

    from docx import Document
    doc = Document(kb.render_kinder_book(school, student, db))
    for t in doc.tables:
        head = " ".join(c.text for c in t.rows[0].cells)
        if "ครั้งที่" in head and "น้ำหนัก" in head:
            assert len(t.rows) - 2 == 4, "ตารางน้ำหนัก/ส่วนสูงต้องมี 4 แถว (ภาคละ 2 ครั้ง)"
            break
    else:
        raise AssertionError("ไม่พบตารางน้ำหนัก/ส่วนสูงในสมุดพกอนุบาล")
