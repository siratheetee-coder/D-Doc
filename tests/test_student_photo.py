"""
ทดสอบ Phase 5: อัปโหลดรูปนักเรียน
- อัปโหลด -> เก็บ JPEG ย่อขนาดใน DB · เสิร์ฟผ่าน /students/{id}/photo
- ฝังรูปในสมุดพก ปพ.6 (มีไฟล์ใน word/media)
- ลบรูปได้
รัน: .venv\\Scripts\\python.exe -m tests.test_student_photo
"""
import io
import zipfile
import app.routers.auth as auth_mod
from fastapi.testclient import TestClient
from PIL import Image

from app.tenancy import session_for, current_school_id
from app.models import Student, AcadClass, AcadStudent
from app.main import app
from app.services.acad_doc import render_pp6
from app.routers.pages import get_school

TID = 1
MARK = "ทดสอบรูป_"


def _db():
    return session_for(TID)


def _cleanup(db):
    for c in db.query(AcadClass).filter(AcadClass.note.like(MARK + "%")).all():
        db.delete(c)
    for s in db.query(Student).filter(Student.name.like(MARK + "%")).all():
        db.delete(s)
    db.commit()


def _login():
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": TID,
        "display_name": "x", "must_change": False}
    c = TestClient(app)
    c.post("/login", data={"username": "t", "password": "x"})
    return c


def _png_bytes(color=(200, 60, 60)):
    img = Image.new("RGB", (900, 1200), color)
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


def main():
    current_school_id.set(TID)
    c = _login()
    db = _db()
    _cleanup(db)
    try:
        db.add(Student(name=MARK + "เด็กชายรูป", sex="M", level="ป.6", room="9", student_no="60001"))
        db.commit()
        sid = db.query(Student).filter(Student.name == MARK + "เด็กชายรูป").first().id

        # อัปโหลด
        r = c.post(f"/students/{sid}/photo",
                   files={"file": ("p.png", _png_bytes(), "image/png")}, follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code
        db.expire_all()
        s = db.get(Student, sid)
        assert s.photo and len(s.photo) > 0 and s.photo_ext == "jpg", "ไม่ได้เก็บรูป"
        # ย่อขนาดแล้ว: JPEG + ด้านยาวสุด <= 480
        im = Image.open(io.BytesIO(s.photo))
        assert im.format == "JPEG" and max(im.size) <= 480, im.size
        print(f"[ok] อัปโหลด+ย่อรูปเก็บใน DB (JPEG {im.size}, {len(s.photo)} bytes)")

        # เสิร์ฟรูป
        r = c.get(f"/students/{sid}/photo")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        print("[ok] เสิร์ฟรูปผ่าน /students/{id}/photo")

        # หน้าแก้ไขมีแท็กรูป
        assert f"/students/{sid}/photo" in c.get(f"/students/{sid}").text
        print("[ok] หน้าแก้ไขแสดงรูป")

        # ฝังในสมุดพก ปพ.6
        cls = AcadClass(year=2567, level="ป.6", room="9", note=MARK)
        db.add(cls); db.commit()
        ast = AcadStudent(class_id=cls.id, student_id=sid, seq=1, name=s.name, sex="M")
        db.add(ast); db.commit()
        path = render_pp6(get_school(db), ast, db)
        with zipfile.ZipFile(path) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert media, "สมุดพกไม่มีรูปฝัง (word/media ว่าง)"
        print(f"[ok] ฝังรูปในสมุดพก ปพ.6 ({media})")

        # ลบรูป
        r = c.post(f"/students/{sid}/photo/delete", follow_redirects=False)
        assert r.status_code in (302, 303)
        db.expire_all()
        assert db.get(Student, sid).photo is None
        assert c.get(f"/students/{sid}/photo").status_code == 404
        print("[ok] ลบรูปได้ (เสิร์ฟคืน 404)")
        print("\nPhase 5 ผ่านทั้งหมด")
    finally:
        _cleanup(db)
        db.close()


if __name__ == "__main__":
    main()
