"""
ทดสอบคะแนนรายชิ้นงาน ปพ.5:
- สร้างชิ้นงานผ่าน /academic/assignments/save
- กรอกคะแนนรายชิ้นผ่าน /academic/grades/save -> score_mid = ผลรวมรายชิ้น, รวม+เกรดถูก
- เว้นชื่อว่าง = ลบชิ้นงาน · โหมดเดิม (ไม่มีชิ้นงาน) ยังกรอกคะแนนเก็บก้อนเดียวได้
รัน: .venv\\Scripts\\python.exe -m tests.test_assignments
"""
import app.routers.auth as auth_mod
import app.main as main_mod
from fastapi.testclient import TestClient

from app.tenancy import session_for
from app.models import (AcadClass, AcadStudent, AcadSubject, AcadScore,
                        AcadAssignment, AcadAssignmentScore)
from app.main import app

TID = 1
MARK = "ทดสอบassign_"


def _db():
    return session_for(TID)


def _cleanup(db):
    for sub in db.query(AcadSubject).filter(AcadSubject.name.like(MARK + "%")).all():
        aids = [a.id for a in db.query(AcadAssignment).filter_by(subject_id=sub.id).all()]
        if aids:
            db.query(AcadAssignmentScore).filter(
                AcadAssignmentScore.assignment_id.in_(aids)).delete(synchronize_session=False)
        db.query(AcadAssignment).filter_by(subject_id=sub.id).delete(synchronize_session=False)
        db.query(AcadScore).filter_by(subject_id=sub.id).delete(synchronize_session=False)
        db.delete(sub)
    for c in db.query(AcadClass).filter(AcadClass.note.like(MARK + "%")).all():
        db.delete(c)
    db.commit()


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


def test_assignments_flow():
    c = _login()
    db = _db()
    _cleanup(db)
    try:
        cls = AcadClass(year=2567, level="ป.6", room="9", note=MARK + "ป.6")
        db.add(cls); db.commit()
        db.add(AcadStudent(class_id=cls.id, seq=1, name=MARK + "เด็กหญิงเก็บคะแนน", sex="F"))
        db.commit()
        s = cls.students[0]
        subj = AcadSubject(year=2567, level="ป.6", code="ท16101",
                           name=MARK + "ภาษาไทย", term=0, mid_max=70, final_max=30)
        db.add(subj); db.commit()

        # สร้างชิ้นงาน 3 ชิ้น (ใบงาน 20 / โครงงาน 20 / สอบกลางภาค 30) รวมเก็บ = 70
        r = c.post("/academic/assignments/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            "new_name": ["ใบงานที่ 1", "โครงงาน", "สอบกลางภาค"],
            "new_max": ["20", "20", "30"],
            "new_mid": ["", "", "1"],
        }, follow_redirects=False)
        assert r.status_code in (302, 303)
        db.expire_all()
        asgs = db.query(AcadAssignment).filter_by(subject_id=subj.id).order_by(AcadAssignment.seq).all()
        assert len(asgs) == 3, [a.name for a in asgs]
        assert asgs[2].is_midterm and asgs[2].max_score == 30
        print("[ok] สร้างชิ้นงาน 3 ชิ้น (รวมสอบกลางภาค)")

        # หน้ากรอกคะแนนต้องมีคอลัมน์รายชิ้น
        html = c.get(f"/academic/grades?cid={cls.id}&sid={subj.id}").text
        assert f"item_{s.id}_{asgs[0].id}" in html and "เก็บเต็มรวม 70" in html
        print("[ok] หน้าคะแนนแสดงคอลัมน์รายชิ้น + เก็บเต็มรวม 70")

        # กรอกคะแนนรายชิ้น 18 + 15 + 25 = 58 (เก็บ) + ปลายภาค 24 = 82 -> เกรด 4
        c.post("/academic/grades/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"item_{s.id}_{asgs[0].id}": "18",
            f"item_{s.id}_{asgs[1].id}": "15",
            f"item_{s.id}_{asgs[2].id}": "25",
            f"fin_{s.id}": "24",
        })
        db.expire_all()
        sc = db.query(AcadScore).filter_by(subject_id=subj.id, acad_student_id=s.id).one()
        assert sc.score_mid == 58, sc.score_mid
        assert sc.score_final == 24 and sc.score == 82, sc.score
        assert sc.grade == "4", sc.grade
        print("[ok] score_mid=58 (รวมรายชิ้น) score=82 grade=4")

        # กรอกเกินคะแนนเต็มของชิ้น -> ถูก clamp
        c.post("/academic/grades/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"item_{s.id}_{asgs[0].id}": "999",     # เต็ม 20
            f"fin_{s.id}": "30",
        })
        db.expire_all()
        r2 = db.query(AcadAssignmentScore).filter_by(
            assignment_id=asgs[0].id, acad_student_id=s.id).one()
        assert r2.score == 20, r2.score
        print("[ok] กรอกเกินเต็มชิ้น ถูก clamp เป็น 20")

        # ลบชิ้นงาน (เว้นชื่อว่าง) -> โหมดเดิมกลับมา
        c.post("/academic/assignments/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"del": [str(asgs[0].id), str(asgs[1].id), str(asgs[2].id)],
        })
        db.expire_all()
        assert db.query(AcadAssignment).filter_by(subject_id=subj.id).count() == 0
        html2 = c.get(f"/academic/grades?cid={cls.id}&sid={subj.id}").text
        assert f"mid_{s.id}" in html2, "ควรกลับมาโหมดกรอกคะแนนเก็บก้อนเดียว"
        print("[ok] ลบชิ้นงานหมด -> กลับโหมดเดิม (คะแนนเก็บก้อนเดียว)")

        # โหมดเดิม: กรอกคะแนนเก็บก้อนเดียวยังทำงาน
        c.post("/academic/grades/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"mid_{s.id}": "60", f"fin_{s.id}": "20"})
        db.expire_all()
        sc2 = db.query(AcadScore).filter_by(subject_id=subj.id, acad_student_id=s.id).one()
        assert sc2.score_mid == 60 and sc2.score == 80 and sc2.grade == "4", (sc2.score_mid, sc2.score, sc2.grade)
        print("[ok] โหมดเดิม (คะแนนเก็บก้อนเดียว) ยังทำงาน score=80 grade=4")
    finally:
        _cleanup(db)
        db.close()


def main():
    test_assignments_flow()
    print("\nคะแนนรายชิ้นงาน ผ่านทั้งหมด")


if __name__ == "__main__":
    main()
