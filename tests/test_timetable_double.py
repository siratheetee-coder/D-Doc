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


def test_locked_cells_survive_clear_and_existing_count_toward_target(db):
    from app.routers.academic import _auto_schedule
    k, ps, sci, tha, t = seed(db)
    db.add(AcadTimetable(class_id=k.id, day=1, period_id=ps[0].id, subject_id=tha.id, locked=True))
    db.add(AcadTimetable(class_id=k.id, day=2, period_id=ps[0].id, subject_id=tha.id))
    db.commit()
    placed, unplaced, split = _auto_schedule(db, k, {tha.id: 3}, True, {}, {"keep_locked": True})
    rows = db.query(AcadTimetable).filter_by(class_id=k.id, subject_id=tha.id).all()
    assert len(rows) == 3 and placed == 2                       # ล็อก 1 คาบอยู่แล้ว จัดเพิ่ม 2 ให้ครบ 3
    assert any(r.day == 1 and r.period_id == ps[0].id and r.locked for r in rows)
    # ไม่ล้าง: คาบที่มีอยู่นับรวม ครบแล้วไม่จัดเพิ่ม
    assert _auto_schedule(db, k, {tha.id: 3}, False)[0] == 0


def test_clear_keeps_activity_and_homeroom_cells(db):
    from app.routers.academic import _auto_schedule
    k, ps, sci, tha, t = seed(db)
    db.add(AcadTimetable(class_id=k.id, day=5, period_id=ps[3].id, note="ชุมนุม"))
    db.add(AcadTimetable(class_id=k.id, day=1, period_id=ps[0].id, subject_id=tha.id))
    db.commit()
    _auto_schedule(db, k, {sci.id: 2}, True)
    rows = db.query(AcadTimetable).filter_by(class_id=k.id).all()
    assert any(r.note == "ชุมนุม" and r.day == 5 for r in rows)      # กิจกรรมยังอยู่
    assert not any(r.subject_id == tha.id for r in rows)             # วิชาเดิมถูกล้าง

import pytest


@pytest.fixture
def tt_env(env):
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        k, ps, sci, tha, t = seed(s)
        ids = dict(cid=k.id, p1=ps[0].id, p2=ps[1].id, p3=ps[3].id, sci=sci.id, tha=tha.id)
    return env, tn, tid, ids


from tests.test_subsidy import env  # noqa: E402,F401


def test_timetable_routes_plan_lock_undo(tt_env):
    from app.models import AcadTimetablePlan
    env, tn, tid, i = tt_env
    cid, p1 = i["cid"], i["p1"]
    form = {"cid": cid, f"cell_1_{p1}": f"s{i['tha']}", f"lock_1_{p1}": "1", f"n_{i['tha']}": "3", f"d_{i['tha']}": "0",
            f"n_{i['sci']}": "4", f"d_{i['sci']}": "1"}
    r = env.post("/academic/timetable/save", data=form, follow_redirects=False)
    assert r.status_code == 303
    with tn.session_for(tid) as s:
        row = s.query(AcadTimetable).filter_by(class_id=cid, day=1, period_id=p1).one()
        assert row.locked and row.subject_id == i["tha"]
        plan = {x.subject_id: (x.periods, x.doubles) for x in s.query(AcadTimetablePlan).filter_by(class_id=cid)}
        assert plan == {i["tha"]: (3, 0), i["sci"]: (4, 1)}
    page = env.get(f"/academic/timetable?cid={cid}").text
    assert 'value="3"' in page and "ตั้งค่าจำนวนคาบต่อสัปดาห์" in page and "จัดใหม่ทั้งตาราง" in page
    # จัดใหม่ทั้งตาราง + รักษาคาบล็อก
    form.update({"clear": "on", "opt_keep_locked": "1", "opt_use_doubles": "1", "opt_same_day": "1", "opt_spread": "1"})
    r = env.post("/academic/timetable/auto", data=form, follow_redirects=False)
    assert r.status_code == 303 and "auto=6" in r.headers["location"]
    with tn.session_for(tid) as s:
        assert s.query(AcadTimetable).filter_by(class_id=cid).count() == 7
        assert s.query(AcadTimetable).filter_by(class_id=cid, day=1, period_id=p1).one().locked
    assert "ย้อนกลับ" in env.get(r.headers["location"]).text
    r = env.post("/academic/timetable/undo", data={"cid": cid}, follow_redirects=False)
    assert r.status_code == 303
    with tn.session_for(tid) as s:
        rows = s.query(AcadTimetable).filter_by(class_id=cid).all()
        assert len(rows) == 1 and rows[0].locked                 # กลับเป็นก่อนจัด


def test_blocked_cell_and_teacher_from_plan_panel(tt_env):
    env, tn, tid, i = tt_env
    cid, p1, p2 = i["cid"], i["p1"], i["p2"]
    with tn.session_for(tid) as s:
        new_t = Person(name="ครูคนใหม่"); s.add(new_t); s.commit(); new_tid = new_t.id
    form = {"cid": cid, f"cell_1_{p1}": "x", f"n_{i['tha']}": "5", f"d_{i['tha']}": "0",
            f"n_{i['sci']}": "0", f"d_{i['sci']}": "0", f"t_{i['tha']}": str(new_tid), f"t_{i['sci']}": "",
            "clear": "on", "opt_keep_locked": "1", "opt_spread": "1", "opt_same_day": "1", "opt_use_doubles": "1"}
    r = env.post("/academic/timetable/auto", data=form, follow_redirects=False)
    assert r.status_code == 303
    with tn.session_for(tid) as s:
        b = s.query(AcadTimetable).filter_by(class_id=cid, day=1, period_id=p1).one()
        assert b.blocked and b.subject_id is None                  # เว้นว่างไว้ ไม่ถูกล้าง ไม่ถูกลงวิชา
        assert s.query(AcadTimetable).filter_by(class_id=cid, subject_id=i["tha"]).count() == 5
        teach = {t.subject_id: t.teacher_id for t in s.query(AcadTeaching).filter_by(class_id=cid)}
        assert teach.get(i["tha"]) == new_tid and i["sci"] not in teach   # ตั้งครูใหม่ / เอาครูวิทย์ออก
    page = env.get(f"/academic/timetable?cid={cid}").text
    assert 'value="x" data-cp-label="เว้นว่าง (ไม่ลงวิชา)"' in page and "selected>เว้นว่าง" in page.replace("  ", " ")
