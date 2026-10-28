"""คาบคู่: จัดอัตโนมัติวาง 2 คาบติดกันวันเดียวกัน ไม่คร่อมคาบพัก และพิมพ์ Word รวมช่อง"""
from tests.test_academic_lessons import db
from app.models import AcadClass, AcadPeriod, AcadTimetable, AcadSubject, AcadTeaching, Person


def seed(db, with_lunch=True):
    k = AcadClass(year=2569, level='ม.1', room='1')
    ps = [AcadPeriod(year=2569, seq=1, name='คาบ 1'), AcadPeriod(year=2569, seq=2, name='คาบ 2'),
          AcadPeriod(year=2569, seq=3, name='พักเที่ยง', is_break=with_lunch), AcadPeriod(year=2569, seq=4, name='คาบ 3')]
    t = Person(name='ครูวิทย์')
    sci = AcadSubject(year=2569, level='ม.1', name='วิทยาศาสตร์', term=1)
    tha = AcadSubject(year=2569, level='ม.1', name='ภาษาไทย', term=1)
    db.add_all([k, t, sci, tha, *ps]); db.flush()
    db.add(AcadTeaching(class_id=k.id, subject_id=sci.id, teacher_id=t.id)); db.commit()
    return k, ps, sci, tha, t


def _cells(db, k, sid):
    return sorted((r.day, r.period_id) for r in db.query(AcadTimetable).filter_by(class_id=k.id, subject_id=sid))


def test_double_period_is_consecutive_and_not_across_break(db):
    from app.routers.academic import _auto_schedule
    k, ps, sci, tha, t = seed(db)
    placed, unplaced, split = _auto_schedule(db, k, {sci.id: 4, tha.id: 5}, True, {sci.id: 1})
    assert (placed, unplaced, split) == (9, 0, 0)
    sc = _cells(db, k, sci.id)
    days = {}
    for d, pid in sc:
        days.setdefault(d, []).append(pid)
    pair_days = [d for d, pids in days.items() if len(pids) == 2]
    assert len(pair_days) == 1                                   # คาบคู่ 1 ชุดอยู่วันเดียว
    assert sorted(days[pair_days[0]]) == [ps[0].id, ps[1].id]    # คาบ 1-2 ติดกัน (คาบ 2 กับ 3 คั่นพักเที่ยง)
    assert sum(len(v) for v in days.values()) == 4               # ที่เหลือ 2 คาบเดี่ยว
    assert all(len(v) == 1 for d, v in days.items() if d != pair_days[0])


def test_double_period_falls_back_to_singles_when_no_adjacent_slot(db):
    from app.routers.academic import _auto_schedule
    k, ps, sci, tha, t = seed(db)
    other = AcadClass(year=2569, level='ม.2', room='1'); db.add(other); db.flush()
    sub2 = AcadSubject(year=2569, level='ม.2', name='วิทย์ ม.2', term=1); db.add(sub2); db.flush()
    db.add(AcadTeaching(class_id=other.id, subject_id=sub2.id, teacher_id=t.id))
    for d in range(1, 6):                                        # ครูไม่ว่างคาบ 2 ทุกวัน -> ไม่มีคู่ติดกันเลย
        db.add(AcadTimetable(class_id=other.id, day=d, period_id=ps[1].id, subject_id=sub2.id))
    db.commit()
    placed, unplaced, split = _auto_schedule(db, k, {sci.id: 2}, True, {sci.id: 1})
    assert (placed, unplaced, split) == (2, 0, 1)
    assert len({d for d, _ in _cells(db, k, sci.id)}) == 2       # แยกเป็น 2 วัน


def test_double_capped_and_docx_merges(db, tmp_path, monkeypatch):
    from app.routers.academic import _auto_schedule
    from app.services import acad_doc
    from docx import Document
    k, ps, sci, tha, t = seed(db)
    _auto_schedule(db, k, {sci.id: 2}, True, {sci.id: 5})          # ขอ 5 ชุดแต่มีแค่ 2 คาบ -> 1 ชุด
    assert len(_cells(db, k, sci.id)) == 2
    monkeypatch.setattr(acad_doc, "get_data_dir", lambda: tmp_path)

    class School: name = "โรงเรียนทดสอบ"; logo_path = None
    out = acad_doc.render_timetable_class(School(), k, db)
    xml = Document(out).tables[0]._tbl.xml
    assert 'w:gridSpan w:val="2"' in xml and "(คาบคู่)" in xml
