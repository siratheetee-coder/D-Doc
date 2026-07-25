"""
ทดสอบ Phase 4: สมุดพก ปพ.6 ฉบับ 9 หน้า
- เนื้อหาครบทุกหน้า (ปก/ข้อมูลส่วนตัว/เวลาเรียน+ภาวะโภชนาการ/ผลการเรียน/คุณลักษณะ/
  อ่านคิดเขียน/กิจกรรม+O-NET/ความเห็น/สรุป)
- ขึ้นหน้าใหม่ 8 ครั้ง (9 หน้า) · Word COM นับ 9 หน้า/คน ไม่มีหน้าว่าง (ถ้ามี Word)
รัน: .venv\\Scripts\\python.exe -m tests.test_pp6_book
"""
import datetime as dt
import zipfile

from app.tenancy import current_school_id, session_for
from app.models import (Student, StudentMeasure, AcadClass, AcadStudent, AcadSubject, AcadScore,
                        AcadCharEval, AcadReadEval, AcadAttendance, AcadActivity,
                        AcadActivityResult, AcadOnet)
from app.services.acad_doc import render_pp6, render_pp6_class
from app.routers.pages import get_school

TID = 1
MARK = "ทดสอบpp6_"


def _setup(db):
    st = Student(name=MARK + "เด็กหญิงหินลาด", sex="F", student_no="60099", level="ป.6", room="9",
                 birthdate=dt.datetime(2013, 6, 1), id_card="1449900000001", father_name="นายพ่อ ใจดี",
                 mother_name="นางแม่ ใจดี", race="ไทย", nationality="ไทย", religion="พุทธ",
                 blood_group="O", congenital_disease="ไม่มี", addr_no="9", addr_moo="3",
                 addr_tambon="หินลาด", addr_amphoe="เมือง", addr_province="มหาสารคาม",
                 addr_zip="44000", phone="0800000000", prev_school="อนุบาลเดิม",
                 enroll_date=dt.datetime(2019, 5, 16))
    db.add(st); db.commit()
    db.add(StudentMeasure(student_id=st.id, year=2567, term=1, weight=32, height=138, date=dt.datetime(2024, 6, 1)))
    db.add(StudentMeasure(student_id=st.id, year=2567, term=2, weight=34, height=140, date=dt.datetime(2024, 11, 1)))
    c = AcadClass(year=2567, level="ป.6", room="9", note=MARK)
    db.add(c); db.commit()
    ast = AcadStudent(class_id=c.id, student_id=st.id, seq=1, student_no="60099", name=st.name, sex="F")
    db.add(ast); db.commit()
    sub = AcadSubject(year=2567, level="ป.6", code="ท16101", name="ภาษาไทย", hours=200, term=0, seq=1)
    db.add(sub); db.commit()
    db.add(AcadScore(acad_student_id=ast.id, subject_id=sub.id, term=0, score=78, grade="4"))
    db.add(AcadCharEval(acad_student_id=ast.id, subject_id=sub.id, c1=3, c2=3, c3=2, c4=3, c5=3, c6=2, c7=3, c8=3))
    db.add(AcadReadEval(acad_student_id=ast.id, subject_id=sub.id, r_read=3, r_think=2, r_write=3))
    db.add(AcadAttendance(acad_student_id=ast.id, month=6, marks="/" * 20 + "ป"))
    act = AcadActivity(year=2567, level="ป.6", code="ก16901", name="แนะแนว", seq=1)
    db.add(act); db.commit()
    db.add(AcadActivityResult(acad_student_id=ast.id, activity_id=act.id, result="ผ"))
    db.add(AcadOnet(acad_student_id=ast.id, subject="ภาษาไทย", full_score=100, score=55))
    db.commit()
    return st, c, ast, sub, act


def _teardown(db, st, c, ast, sub, act):
    db.query(AcadOnet).filter_by(acad_student_id=ast.id).delete()
    db.query(AcadActivityResult).filter_by(acad_student_id=ast.id).delete()
    db.query(AcadAttendance).filter_by(acad_student_id=ast.id).delete()
    db.query(AcadReadEval).filter_by(acad_student_id=ast.id).delete()
    db.query(AcadCharEval).filter_by(acad_student_id=ast.id).delete()
    db.query(AcadScore).filter_by(acad_student_id=ast.id).delete()
    db.delete(act); db.delete(ast); db.delete(sub); db.delete(c)
    db.query(StudentMeasure).filter_by(student_id=st.id).delete()
    db.delete(st); db.commit()


def _xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def _word_pages(path):
    """นับหน้าจริงด้วย Word COM (คืน None ถ้าไม่มี Word)"""
    try:
        import time
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        try:
            d = word.Documents.Open(path, ReadOnly=True)
            d.Repaginate(); time.sleep(1.5)
            n = d.ComputeStatistics(2)   # wdStatisticPages
            d.Close(False)
            return n
        finally:
            word.Quit()
    except Exception as e:
        print(f"   (ข้าม Word COM: {e})")
        return None


def main():
    current_school_id.set(TID)
    db = session_for(TID)
    # ลบของค้างจากรอบก่อน
    for c in db.query(AcadClass).filter(AcadClass.note.like(MARK + "%")).all():
        for a in c.students:
            for M in (AcadOnet, AcadActivityResult, AcadAttendance, AcadReadEval, AcadCharEval, AcadScore):
                db.query(M).filter_by(acad_student_id=a.id).delete()
        db.delete(c)
    for stu in db.query(Student).filter(Student.name.like(MARK + "%")).all():
        db.query(StudentMeasure).filter_by(student_id=stu.id).delete()
        db.delete(stu)
    db.commit()

    st, c, ast, sub, act = _setup(db)
    try:
        path = render_pp6(get_school(db), ast, db)
        xml = _xml(path)

        checks = {
            "ปก": "สมุดรายงานประจำตัวนักเรียน",
            "ข้อมูลส่วนตัว": "ข้อมูลส่วนตัว",
            "เลขบัตรประชาชน": "1449900000001",
            "ที่อยู่": "หินลาด",
            "ภาวะโภชนาการ": "ภาวะโภชนาการ",
            "เกณฑ์กรมอนามัย": "กรมอนามัย",
            "ผลการเรียน": "ผลการเรียน",
            "รหัสวิชา": "ท16101",
            "GPA": "ผลการเรียนเฉลี่ย",
            "คุณลักษณะ": "คุณลักษณะอันพึงประสงค์",
            "อ่านคิดเขียน": "คิดวิเคราะห์",
            "กิจกรรม": "กิจกรรมพัฒนาผู้เรียน",
            "O-NET": "O-NET",
            "กิจกรรมแนะแนว": "แนะแนว",
            "ความเห็น": "ความเห็นของครูประจำชั้นและผู้ปกครอง",
            "ภาคเรียนที่2": "ภาคเรียนที่ 2",
            "สรุป": "สรุปผลการประเมิน",
        }
        missing = [k for k, v in checks.items() if v not in xml]
        assert not missing, f"เนื้อหาขาด: {missing}"
        print(f"[ok] เนื้อหาครบทุกหน้า ({len(checks)} จุดตรวจ)")

        nbreak = xml.count("<w:pageBreakBefore")
        assert nbreak == 8, f"ควรขึ้นหน้าใหม่ 8 ครั้ง (9 หน้า) ได้ {nbreak}"
        print(f"[ok] ขึ้นหน้าใหม่ {nbreak} ครั้ง = 9 หน้า")

        pages = _word_pages(path)
        if pages is not None:
            assert pages == 9, f"Word นับได้ {pages} หน้า (ควร 9 - อาจมีหน้าว่างหรือเนื้อล้น)"
            print(f"[ok] Word COM นับได้ {pages} หน้า ไม่มีหน้าว่าง")

        # ทั้งห้อง 1 คน = 9 หน้า (page_break คนแรก=False -> 8 breaks)
        pth2 = render_pp6_class(get_school(db), c, db)
        xml2 = _xml(pth2)
        assert xml2.count("<w:pageBreakBefore") == 8, xml2.count("<w:pageBreakBefore")
        print("[ok] สมุดพกทั้งห้อง (1 คน) = 9 หน้า")
        print("\nPhase 4 ผ่านทั้งหมด")
    finally:
        _teardown(db, st, c, ast, sub, act)
        db.close()


if __name__ == "__main__":
    main()
