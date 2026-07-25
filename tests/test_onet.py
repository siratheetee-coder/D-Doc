"""
ทดสอบ Phase 3: O-NET (ผลทดสอบระดับชาติ ชั้นปลายทาง)
- หน้า /academic/eval ของชั้น ป.6 แสดงตาราง O-NET, ชั้นอื่นไม่แสดง
- บันทึกผ่าน /academic/eval/save -> AcadOnet + onet_for อ่านกลับ
รัน: .venv\\Scripts\\python.exe -m tests.test_onet
"""
import app.routers.auth as auth_mod
import app.main as main_mod
from fastapi.testclient import TestClient

from app.tenancy import session_for
from app.models import AcadClass, AcadStudent, AcadOnet
from app.main import app
from app.services import academic as acad

TID = 1
MARK = "ทดสอบonet_"


def _db():
    return session_for(TID)


def _cleanup(db):
    cls = db.query(AcadClass).filter(AcadClass.note.like(MARK + "%")).all()
    for c in cls:
        sids = [s.id for s in c.students]
        if sids:
            db.query(AcadOnet).filter(AcadOnet.acad_student_id.in_(sids)).delete(synchronize_session=False)
        db.delete(c)
    db.commit()


def _login():
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": TID,
        "display_name": "x", "must_change": False}
    main_mod.can_use_module = lambda tid, mod: True   # ข้าม module-gate ในการทดสอบ
    c = TestClient(app)
    c.post("/login", data={"username": "t", "password": "x"})
    return c


def _mkclass(db, level):
    c = AcadClass(year=2567, level=level, room="9", note=MARK + level)
    db.add(c); db.commit()
    db.add(AcadStudent(class_id=c.id, seq=1, name=MARK + "เด็กชายโอเน็ต", sex="M"))
    db.commit()
    return c


def test_unit_exit_level():
    assert acad.is_exit_level("ป.6") and acad.is_exit_level("ม.3") and acad.is_exit_level("ม.6")
    assert not acad.is_exit_level("ป.5") and not acad.is_exit_level("")
    assert acad.ONET_SUBJECTS == ["ภาษาไทย", "คณิตศาสตร์", "วิทยาศาสตร์", "ภาษาอังกฤษ"]
    print("[ok] is_exit_level / ONET_SUBJECTS ถูก")


def test_http_onet():
    c = _login()
    db = _db()
    _cleanup(db)
    try:
        # ชั้น ป.5 : ไม่มีตาราง O-NET
        c5 = _mkclass(db, "ป.5")
        html5 = c.get(f"/academic/eval?cid={c5.id}").text
        assert "ผลการทดสอบระดับชาติ (O-NET)" not in html5, "ป.5 ไม่ควรมี O-NET"
        print("[ok] ชั้น ป.5 ไม่แสดงตาราง O-NET")

        # ชั้น ป.6 : มีตาราง O-NET
        c6 = _mkclass(db, "ป.6")
        s = c6.students[0]
        html6 = c.get(f"/academic/eval?cid={c6.id}").text
        assert "ผลการทดสอบระดับชาติ (O-NET)" in html6, "ป.6 ควรมี O-NET"
        assert f"onet_{s.id}_ภาษาไทย_score" in html6
        print("[ok] ชั้น ป.6 แสดงตาราง O-NET ครบวิชา")

        # บันทึก O-NET
        r = c.post("/academic/eval/save", data={
            "cid": str(c6.id),
            f"onet_{s.id}_ภาษาไทย_score": "45.5", f"onet_{s.id}_ภาษาไทย_full": "100",
            f"onet_{s.id}_คณิตศาสตร์_score": "38", f"onet_{s.id}_คณิตศาสตร์_full": "100",
        }, follow_redirects=False)
        assert r.status_code in (302, 303)
        db.expire_all()
        o = acad.onet_for(db.get(AcadStudent, s.id), db)
        assert o["ภาษาไทย"].score == 45.5 and o["ภาษาไทย"].full_score == 100, o["ภาษาไทย"].score
        assert o["คณิตศาสตร์"].score == 38
        assert "วิทยาศาสตร์" not in o, "ไม่ควรสร้างแถวว่าง"
        print("[ok] บันทึก O-NET + onet_for อ่านกลับถูก (ไม่สร้างแถวว่าง)")

        # แก้ค่าเดิม (upsert ไม่เพิ่มแถว)
        c.post("/academic/eval/save", data={
            "cid": str(c6.id), f"onet_{s.id}_ภาษาไทย_score": "50", f"onet_{s.id}_ภาษาไทย_full": "100"})
        db.expire_all()
        cnt = db.query(AcadOnet).filter(AcadOnet.acad_student_id == s.id,
                                        AcadOnet.subject == "ภาษาไทย").count()
        assert cnt == 1, f"upsert ซ้ำแถว ({cnt})"
        assert acad.onet_for(db.get(AcadStudent, s.id), db)["ภาษาไทย"].score == 50
        print("[ok] upsert O-NET แก้ค่าเดิม ไม่เพิ่มแถว")
    finally:
        _cleanup(db)
        db.close()


def main():
    test_unit_exit_level()
    test_http_onet()
    print("\nPhase 3 ผ่านทั้งหมด")


if __name__ == "__main__":
    main()
