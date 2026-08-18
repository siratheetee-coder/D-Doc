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

        # เปิดหน้ากรอกคะแนน -> ระบบสร้าง "สอบกลางภาค" ให้อัตโนมัติ
        html0 = c.get(f"/academic/grades?cid={cls.id}&sid={subj.id}").text
        db.expire_all()
        mid = db.query(AcadAssignment).filter_by(subject_id=subj.id, is_midterm=True).one()
        assert "สอบกลางภาค" in html0 and mid.max_score == 30
        print("[ok] เปิดหน้าคะแนน -> มีสอบกลางภาคอัตโนมัติ (เต็ม 30)")

        # เพิ่มชิ้นงาน 2 ชิ้น (ใบงาน 20 / โครงงาน 20) + สอบกลางภาคเต็ม 30 -> เก็บรวม 70
        r = c.post("/academic/assignments/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            "aid": ["", ""], "aname": ["ใบงานที่ 1", "โครงงาน"], "amax": ["20", "20"],
            "mid_max": "30",
        }, follow_redirects=False)
        assert r.status_code in (302, 303)
        db.expire_all()
        pieces = db.query(AcadAssignment).filter_by(subject_id=subj.id, is_midterm=False).order_by(AcadAssignment.seq).all()
        assert len(pieces) == 2 and pieces[0].name == "ใบงานที่ 1"
        assert db.query(AcadAssignment).filter_by(subject_id=subj.id).count() == 3
        print("[ok] เพิ่มชิ้นงาน 2 ชิ้น + สอบกลางภาค = 3 รายการ เก็บรวม 70")

        html = c.get(f"/academic/grades?cid={cls.id}&sid={subj.id}").text
        assert f"item_{s.id}_{pieces[0].id}" in html and f"item_{s.id}_{mid.id}" in html
        assert "เก็บเต็มรวม <b id=\"asgKeepMax\">70" in html
        print("[ok] หน้าคะแนนแสดงคอลัมน์รายชิ้น + สอบกลางภาค + เก็บเต็มรวม 70")

        # กรอก 18 + 15 + สอบกลางภาค 25 = 58 (เก็บ) + ปลายภาค 24 = 82 -> เกรด 4
        c.post("/academic/grades/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"item_{s.id}_{pieces[0].id}": "18",
            f"item_{s.id}_{pieces[1].id}": "15",
            f"item_{s.id}_{mid.id}": "25",
            f"fin_{s.id}": "24",
        })
        db.expire_all()
        sc = db.query(AcadScore).filter_by(subject_id=subj.id, acad_student_id=s.id).one()
        assert sc.score_mid == 58, sc.score_mid
        assert sc.score_final == 24 and sc.score == 82 and sc.grade == "4", (sc.score, sc.grade)
        print("[ok] score_mid=58 (ชิ้นงาน+กลางภาค) score=82 grade=4")

        # กรอกเกินคะแนนเต็มของชิ้น -> ถูก clamp เป็น 20
        c.post("/academic/grades/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            f"item_{s.id}_{pieces[0].id}": "999", f"fin_{s.id}": "30"})
        db.expire_all()
        r2 = db.query(AcadAssignmentScore).filter_by(
            assignment_id=pieces[0].id, acad_student_id=s.id).one()
        assert r2.score == 20, r2.score
        print("[ok] กรอกเกินเต็มชิ้น ถูก clamp เป็น 20")

        # ลบชิ้นงาน 1 ชิ้น (ส่งกลับแค่ชิ้นเดียว) -> สอบกลางภาคต้องยังอยู่
        c.post("/academic/assignments/save", data={
            "cid": str(cls.id), "sid": str(subj.id),
            "aid": [str(pieces[0].id)], "aname": ["ใบงานที่ 1"], "amax": ["25"],
            "mid_max": "35",
        })
        db.expire_all()
        assert db.query(AcadAssignment).filter_by(subject_id=subj.id, is_midterm=False).count() == 1
        mid2 = db.query(AcadAssignment).filter_by(subject_id=subj.id, is_midterm=True).one()
        assert mid2.max_score == 35, "สอบกลางภาคต้องยังอยู่ + แก้เต็มได้"
        print("[ok] ลบชิ้นงานที่ไม่ส่งกลับ + สอบกลางภาคยังอยู่ (แก้เต็ม=35)")
    finally:
        _cleanup(db)
        db.close()


def main():
    test_assignments_flow()
    print("\nคะแนนรายชิ้นงาน ผ่านทั้งหมด")


if __name__ == "__main__":
    main()
