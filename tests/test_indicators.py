"""
ทดสอบตัวชี้วัดรายวิชา (หลักสูตรแกนกลาง 2551) - กลุ่มสาระภาษาไทย
- ชุดข้อมูลกลางโหลดได้ + ผูกด้วยกลุ่มสาระ+ชั้น
- หน้าประเมิน /academic/indicators + บันทึกผล
- ปพ.6 หน้าสรุป ข้อ "ผ่านตัวชี้วัดร้อยละ 100" คิดจากผลจริง
- ปพ.5 มีหน้าผลการประเมินตัวชี้วัด
รัน: .venv\\Scripts\\python.exe -m tests.test_indicators
"""
import zipfile

import app.routers.auth as auth_mod
import app.main as main_mod
from fastapi.testclient import TestClient

from app.tenancy import session_for
from app.models import AcadClass, AcadStudent, AcadSubject, AcadIndicatorResult
from app.main import app
from app.services.acad_doc import render_pp5, render_pp6
from app.routers.pages import get_school
from app.services.curriculum import indicators_for

TID = 1
MARK = "ทดสอบตช_"


def _login():
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": TID,
        "display_name": "x", "must_change": False}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {
        "is_owner": True, "modules": "", "active": True, "welcomed": True}
    c = TestClient(app)
    c.post("/login", data={"username": "t", "password": "x"})
    return c


def _cleanup(db):
    for cls in db.query(AcadClass).filter(AcadClass.note.like(MARK + "%")).all():
        for a in cls.students:
            db.query(AcadIndicatorResult).filter_by(acad_student_id=a.id).delete()
        db.query(AcadSubject).filter_by(year=2590, level=cls.level).delete()
        db.delete(cls)
    db.commit()


def test_curriculum_data():
    assert len(indicators_for("ภาษาไทย", "ป.6")) == 34, "ภาษาไทย ป.6 ต้องมี 34 ตัวชี้วัด"
    assert len(indicators_for("ภาษาไทย", "ป.1")) == 22
    assert indicators_for("ภาษาไทย", "ป.6")[0]["code"] == "ท 1.1 ป.6/1"
    assert len(indicators_for("คณิตศาสตร์", "ป.6")) == 31, "คณิตศาสตร์ ป.6 ต้องมี 31 ตัวชี้วัด (รวม ค6.1 ครบ 6)"
    assert indicators_for("คณิตศาสตร์", "ป.6")[0]["code"] == "ค 1.1 ป.6/1"
    assert len([x for x in indicators_for("คณิตศาสตร์", "ป.6") if x["std"] == "ค 6.1"]) == 6
    assert len(indicators_for("วิทยาศาสตร์และเทคโนโลยี", "ป.6")) == 27, "วิทยาศาสตร์ ป.6 ต้องมี 27"
    assert len([x for x in indicators_for("วิทยาศาสตร์และเทคโนโลยี", "ป.6") if x["std"] == "ว 8.1"]) == 6
    assert len(indicators_for("สังคมศึกษา ศาสนา และวัฒนธรรม", "ป.6")) == 39, "สังคมศึกษา ป.6 ต้องมี 39"
    assert len(indicators_for("สุขศึกษาและพลศึกษา", "ป.6")) == 14
    assert len(indicators_for("ศิลปะ", "ป.6")) == 19
    assert len(indicators_for("การงานอาชีพ", "ป.6")) == 13
    assert len(indicators_for("ภาษาต่างประเทศ", "ป.6")) == 19  # ครบ 8 กลุ่มสาระ
    print("[ok] ชุดข้อมูลตัวชี้วัด: ไทย(34)+คณิต(31)+วิทย์(27)+สังคม(ป.6=39)")


def test_flow():
    c = _login()
    db = session_for(TID)
    _cleanup(db)
    try:
        cls = AcadClass(year=2590, level="ป.6", room="9", note=MARK + "ป.6")
        db.add(cls); db.commit()
        db.add(AcadStudent(class_id=cls.id, seq=1, name=MARK + "เด็กหญิงตช", sex="F"))
        db.commit()
        s = cls.students[0]
        sub = AcadSubject(year=2590, level="ป.6", code="ท16101", name="ภาษาไทย",
                          learn_group="ภาษาไทย", term=0, seq=1)
        db.add(sub); db.commit()
        n = len(indicators_for("ภาษาไทย", "ป.6"))

        html = c.get(f"/academic/indicators?cid={cls.id}&sid={sub.id}").text
        assert html.count('name="sc_') == n and "ท 1.1" in html
        print(f"[ok] หน้าประเมินแสดง {n} ช่องคะแนน 0-3 + หัวมาตรฐาน")

        # ให้คะแนน 3 ทุกข้อ -> ผ่านทุกข้อ
        c.post("/academic/indicators/save", data={
            "cid": str(cls.id), "sid": str(sub.id),
            **{f"sc_{s.id}_{i}": "3" for i in range(n)}})
        db.expire_all()
        rows = db.query(AcadIndicatorResult).filter_by(acad_student_id=s.id).all()
        assert all(r.score == 3 for r in rows) and sum(1 for r in rows if r.passed) == n
        x6 = zipfile.ZipFile(render_pp6(get_school(db), s, db)).read("word/document.xml").decode()
        assert "100.00" in x6
        print("[ok] คะแนน 3 ทุกข้อ -> ผ่านทุกข้อ, ปพ.6 ข้อ 2 = 100.00")

        # ให้ 3 ข้อได้ 0 -> ไม่ผ่าน 3 ข้อ = 31/34 = 91.18
        for r in db.query(AcadIndicatorResult).filter_by(
                acad_student_id=s.id).limit(3).all():
            r.score = 0; r.passed = False
        db.commit()
        x6b = zipfile.ZipFile(render_pp6(get_school(db), s, db)).read("word/document.xml").decode()
        assert "91.18" in x6b
        x5 = zipfile.ZipFile(render_pp5(get_school(db), cls, sub, db)).read("word/document.xml").decode()
        assert "ผลการประเมินตัวชี้วัดรายวิชา" in x5 and "คะแนน 0-3 ต่อตัวชี้วัด" in x5
        print("[ok] 3 ข้อได้ 0 -> ปพ.6=91.18, ปพ.5 เมทริกซ์ 0-3")
    finally:
        _cleanup(db)
        db.close()


def main():
    test_curriculum_data()
    test_flow()
    print("\nตัวชี้วัดรายวิชา ผ่านทั้งหมด")


if __name__ == "__main__":
    main()
