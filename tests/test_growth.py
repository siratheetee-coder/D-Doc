"""
ทดสอบ Phase 2: รวมภาวะโภชนาการเข้าทะเบียนกลาง (StudentMeasure)
- บันทึกน้ำหนัก/ส่วนสูงผ่าน /students/{id}/measure -> StudentMeasure + จัดกลุ่มถูก
- ทั้งหน้า /students/growth และ /lunch/nutrition อ่านข้อมูลชุดเดียวกัน
- growth.build_ctx / report_data สรุปถูก
- migration LunchMeasure -> StudentMeasure ทำงานและ idempotent
รัน: .venv\\Scripts\\python.exe -m tests.test_growth
"""
import app.routers.auth as auth_mod
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import Base, _migrate_lunch_measures
from app.tenancy import session_for
from app.models import (Student, StudentMeasure, LunchProgram, LunchStudent, LunchMeasure)
from app.main import app
from app.services import growth

TID = 1
MARK = "ทดสอบพช_"


def _db():
    return session_for(TID)


def _cleanup(db):
    ids = [s.id for s in db.query(Student).filter(Student.name.like(MARK + "%")).all()]
    if ids:
        db.query(StudentMeasure).filter(StudentMeasure.student_id.in_(ids)).delete(synchronize_session=False)
        db.query(Student).filter(Student.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def _login():
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": TID,
        "display_name": "x", "must_change": False}
    c = TestClient(app)
    c.post("/login", data={"username": "t", "password": "x"})
    return c


def test_measure_flow():
    c = _login()
    db = _db()
    _cleanup(db)
    try:
        db.add(Student(name=MARK + "เด็กชายโภช", sex="M", level="ป.6", room="9",
                       birthdate=__import__("datetime").datetime(2013, 5, 16)))
        db.commit()
        sid = db.query(Student).filter(Student.name == MARK + "เด็กชายโภช").first().id
        yr = growth.current_academic_year()

        r = c.post(f"/students/{sid}/measure",
                   data={"year": str(yr), "term": "1", "weight": "30", "height": "135",
                         "date": "01/06/2567"}, follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code
        db.expire_all()
        m = db.query(StudentMeasure).filter(StudentMeasure.student_id == sid,
                                            StudentMeasure.year == yr, StudentMeasure.term == 1).first()
        assert m is not None and m.weight == 30 and m.height == 135, m
        print("[ok] บันทึกการชั่งลง StudentMeasure ส่วนกลางถูก")

        # จัดกลุ่มภาวะโภชนาการ
        res = growth.measure_result(db.get(Student, sid), m)
        assert res and res.get("wh") in growth.WH_LABELS, res
        print(f"[ok] จัดกลุ่มภาวะโภชนาการ: wh={res['wh']} ha={res.get('ha')}")

        # upsert (แก้ค่าเดิม ไม่เพิ่มแถว)
        c.post(f"/students/{sid}/measure",
               data={"year": str(yr), "term": "1", "weight": "31", "height": "136", "date": "01/06/2567"})
        db.expire_all()
        cnt = db.query(StudentMeasure).filter(StudentMeasure.student_id == sid, StudentMeasure.year == yr,
                                              StudentMeasure.term == 1).count()
        assert cnt == 1, f"upsert ซ้ำแถว ({cnt})"
        assert db.get(StudentMeasure, m.id).weight == 31
        print("[ok] upsert แก้ค่าเดิม ไม่เพิ่มแถว")

        # ทั้งสองหน้าเห็นชื่อ + ค่าเดียวกัน
        for url in [f"/students/growth?year={yr}", f"/lunch/nutrition?year={yr}"]:
            html = c.get(url).text
            assert (MARK + "เด็กชายโภช") in html, f"{url} ไม่เห็นนักเรียน"
        print("[ok] /students/growth และ /lunch/nutrition อ่านข้อมูลชุดเดียวกัน")

        # build_ctx สรุปนับคนที่ประเมินแล้ว
        ctx = growth.build_ctx(db, yr)
        assert ctx["assessed"] >= 1
        cats, cc, sx, tot, assessed = growth.report_data(db, yr)
        assert assessed >= 1 and sum(tot.values()) >= 1
        print(f"[ok] build_ctx/report_data สรุปถูก (assessed={ctx['assessed']})")
    finally:
        _cleanup(db)
        db.close()


def test_lunch_migration():
    """LunchMeasure (ผูก student_id) -> StudentMeasure + idempotent (temp sqlite)"""
    import datetime as dt
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    from sqlalchemy.orm import Session
    with Session(bind=eng) as db:
        st = Student(name="มgrate", sex="F", level="ป.5")
        db.add(st); db.commit()
        prog = LunchProgram(year=2567, pool=1)
        db.add(prog); db.commit()
        ls = LunchStudent(program_id=prog.id, student_id=st.id, name=st.name, sex="F", level="ป.5")
        db.add(ls); db.commit()
        db.add(LunchMeasure(student_id=ls.id, term=1, weight=28.0, height=130.0, date=dt.datetime(2024, 6, 1)))
        db.add(LunchMeasure(student_id=ls.id, term=2, weight=29.5, height=132.0, date=dt.datetime(2024, 11, 1)))
        db.commit()
        stid = st.id

    _migrate_lunch_measures(eng)
    with Session(bind=eng) as db:
        rows = db.query(StudentMeasure).filter(StudentMeasure.student_id == stid).all()
        assert len(rows) == 2, f"ควรย้าย 2 แถว ได้ {len(rows)}"
        assert {r.term for r in rows} == {1, 2}
        assert all(r.year == 2567 for r in rows), [r.year for r in rows]

    # รันซ้ำ ไม่ควรเพิ่มแถว (idempotent)
    _migrate_lunch_measures(eng)
    with Session(bind=eng) as db:
        assert db.query(StudentMeasure).filter(StudentMeasure.student_id == stid).count() == 2
    print("[ok] migration LunchMeasure -> StudentMeasure + idempotent")


def main():
    test_measure_flow()
    test_lunch_migration()
    print("\nPhase 2 ผ่านทั้งหมด")


if __name__ == "__main__":
    main()
