# -*- coding: utf-8 -*-
"""เวลาเรียน: ยอดรายคนต้องเดินตามปฏิทิน และทุกยอดต้องคิดตามภาคเรียนที่เลือก

ปัญหาเดิม
  1) AcadEval.days_open ถูกเขียนครั้งเดียวตอนบันทึกครั้งแรก แก้ปฏิทินแล้วไม่ขยับ
     ผลคือห้องหนึ่งค้าง 220 อีกห้องค้างเลขอื่น ทั้งที่ควรเท่ากันทุกห้อง
  2) ปุ่มภาคเรียนซ่อนคอลัมน์ด้วย CSS แต่ตัวรวมยอดนับช่องที่ซ่อนด้วย
     กดภาคเรียน 1 จึงได้วันเปิดเรียนทั้งปี ร้อยละก็คิดจากฐานผิด
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_attendance_terms.py
"""
import importlib.util
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
YEAR = 2569
TERM1 = {5: 10, 6: 20, 7: 22, 8: 20, 9: 22, 10: 20}      # รวม 114
TERM2 = {11: 20, 12: 20, 1: 21, 2: 20, 3: 24}            # รวม 105
ALL_MONTHS = {**TERM1, **TERM2}                          # รวม 219


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    import app.main as main_mod
    import app.routers.auth as auth_mod
    monkeypatch.setattr(auth_mod, "authenticate", ac.authenticate)
    for key in ("tenant_state", "can_use_module", "get_account_access"):
        monkeypatch.setattr(main_mod, key, getattr(ac, key))

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from app.models import AcadClass, AcadEval, AcadStudent
    from app.tenancy import session_for
    db = session_for(1)
    c = AcadClass(year=YEAR, level="ป.1", room="1")
    db.add(c)
    db.flush()
    for i, nm in enumerate(["เด็กหนึ่ง ทดสอบ", "เด็กสอง ทดสอบ"], start=1):
        db.add(AcadStudent(class_id=c.id, seq=i, name=nm))
    db.flush()
    for st in db.query(AcadStudent).filter_by(class_id=c.id):
        db.add(AcadEval(acad_student_id=st.id, days_open=220))   # ค่าค้างเก่าแบบที่เจอจริง
    db.commit()
    cid = c.id
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/login", data={"username": "demo", "password": "Demo!2569"},
                follow_redirects=False)
    return client, cid


def _save(client, cid, *, manual_for=None, manual_value=None):
    from app.models import AcadStudent
    from app.tenancy import session_for
    db = session_for(1)
    students = db.query(AcadStudent).filter_by(class_id=cid).order_by(AcadStudent.seq).all()
    ids = [s.id for s in students]
    db.close()
    data = {"cid": str(cid), "mode": "overall"}
    for m, n in ALL_MONTHS.items():
        data[f"open_{m}"] = str(n)
    for sid in ids:
        if manual_for == sid:
            data[f"dopen_{sid}"] = str(manual_value)
            data[f"dmanual_{sid}"] = "1"
        else:
            data[f"dopen_{sid}"] = "220"      # หน้าเว็บส่งค่าเก่ามา ระบบต้องไม่เชื่อ
    r = client.post("/academic/attendance/save", data=data, follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    return ids


def _opens(cid):
    from app.models import AcadEval, AcadStudent
    from app.tenancy import session_for
    db = session_for(1)
    rows = (db.query(AcadStudent.id, AcadEval.days_open, AcadEval.days_open_manual)
            .join(AcadEval, AcadEval.acad_student_id == AcadStudent.id)
            .filter(AcadStudent.class_id == cid).all())
    db.close()
    return {r[0]: (r[1], bool(r[2])) for r in rows}


def test_student_open_days_follow_the_class_calendar(env):
    """ค่าค้างเก่า 220 ต้องถูกคำนวณใหม่เป็น 219 ตามวันเปิดเรียนจริงของห้อง"""
    client, cid = env
    _save(client, cid)
    for days, manual in _opens(cid).values():
        assert days == sum(ALL_MONTHS.values()) == 219, days
        assert manual is False


def test_changing_the_calendar_moves_every_student(env):
    """แก้ปฏิทินแล้วทุกคนต้องขยับตาม ไม่ค้างเลขเดิม"""
    client, cid = env
    _save(client, cid)
    global ALL_MONTHS
    ALL_MONTHS = {**ALL_MONTHS, 5: 12}        # เพิ่มวันเปิดเรียน พ.ค. อีก 2 วัน
    try:
        _save(client, cid)
        for days, _m in _opens(cid).values():
            assert days == 221, days
    finally:
        ALL_MONTHS = {**TERM1, **TERM2}


def test_manual_override_is_kept(env):
    """เด็กย้ายเข้ากลางปี ครูตั้งเอง ระบบต้องไม่คำนวณทับ"""
    client, cid = env
    ids = _save(client, cid)
    _save(client, cid, manual_for=ids[0], manual_value=150)
    opens = _opens(cid)
    assert opens[ids[0]] == (150, True)
    assert opens[ids[1]] == (219, False)


def test_clearing_the_flag_returns_to_the_class_total(env):
    client, cid = env
    ids = _save(client, cid)
    _save(client, cid, manual_for=ids[0], manual_value=150)
    _save(client, cid)                         # ไม่ส่งธงมาแล้ว = คืนค่าตามห้อง
    assert _opens(cid)[ids[0]] == (219, False)


# ---------------------------------------------------------------- ฝั่งหน้าจอ
def _page():
    return (ROOT / "app" / "templates" / "academic_attendance.html").read_text(encoding="utf-8")


def test_totals_only_count_the_months_of_the_selected_term():
    html = _page()
    assert "function inTerm(" in html, "ต้องมีตัวกรองเดือนตามภาคเรียน"
    assert "if (!inTerm(i)) return;" in html, "ตัวรวมยอดต้องข้ามเดือนนอกภาคเรียน"


def test_sick_leave_absent_hidden_per_term():
    """ป่วย/ลา/ขาด เก็บเป็นยอดทั้งปี โชว์คู่กับวันเปิดเรียนของภาคเดียวจะอ่านผิด"""
    html = _page()
    assert "#attTable.show-t1 .gapcol" in html and "#attTable.show-t2 .gapcol" in html


def test_manual_flag_is_set_before_the_recalculation_runs():
    """เคยพลาด: ติดธงตอน bubble ทำให้ตัวคำนวณเขียนทับเลขที่ครูเพิ่งพิมพ์"""
    html = _page()
    i = html.index("[data-dopen]')) return;")
    tail = html[i:i + 400]
    assert "}, true);" in tail, "ต้องผูกแบบ capture phase"


# ---------------------------------------------------------------- หน้าสรุปท้ายเล่ม
def _doc_text(path):
    import re
    import zipfile
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", chr(10), xml))


def _class_with_months(cid):
    from app.models import AcadAttendance, AcadClass, AcadClassMonth, AcadStudent, School
    from app.tenancy import session_for
    db = session_for(1)
    c = db.get(AcadClass, cid)
    for m, n in ALL_MONTHS.items():
        db.add(AcadClassMonth(class_id=cid, month=m, days_open=n))
    for st in db.query(AcadStudent).filter_by(class_id=cid):
        for m, n in ALL_MONTHS.items():
            db.add(AcadAttendance(acad_student_id=st.id, month=m, present=n, subject_id=None))
    db.commit()
    return db, db.query(School).first(), c


def test_term_book_summarises_only_that_term(env):
    """ออกเอกสารภาคไหน ต้องสรุปเฉพาะเดือนของภาคนั้น ไม่เอายอดทั้งปีมาปน"""
    from app.services.acad_doc import render_attendance_term
    client, cid = env
    db, school, c = _class_with_months(cid)
    try:
        t1 = _doc_text(render_attendance_term(school, c, db, 1))
        t2 = _doc_text(render_attendance_term(school, c, db, 2))
    finally:
        db.close()

    assert "สรุปเวลาเรียนรายเดือน ภาคเรียนที่ 1" in t1
    s1 = t1[t1.index("สรุปเวลาเรียนรายเดือน"):]
    assert "พฤษภาคม" in s1 and "ตุลาคม" in s1
    assert "พฤศจิกายน" not in s1 and "มีนาคม" not in s1, "เดือนของภาค 2 ต้องไม่โผล่ในเล่มภาค 1"
    assert str(sum(TERM1.values())) in s1

    s2 = t2[t2.index("สรุปเวลาเรียนรายเดือน"):]
    assert "พฤศจิกายน" in s2 and "พฤษภาคม" not in s2
    assert str(sum(TERM2.values())) in s2


def test_summary_has_the_columns_asked_for(env):
    from app.services.acad_doc import render_attendance_term
    client, cid = env
    db, school, c = _class_with_months(cid)
    try:
        text = _doc_text(render_attendance_term(school, c, db, 1))
    finally:
        db.close()
    page = text[text.index("สรุปเวลาเรียนรายเดือน"):]
    for col in ("เดือน", "วันเปิดเรียน", "มาเรียน", "ป่วย", "ลา", "ขาด", "ร้อยละการมาเรียน", "รวม"):
        assert col in page, col
