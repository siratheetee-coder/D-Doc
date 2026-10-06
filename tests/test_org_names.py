# -*- coding: utf-8 -*-
"""ตำแหน่งผู้บริหารในเอกสาร ต้องเดินตามที่ผู้ใช้ตั้งไว้ ไม่ใช่เดาจากชื่อหน่วยงาน

เคยพลาด: โค้ดกระจายอยู่เกือบยี่สิบจุดเขียนกติกาเองว่า ถ้าชื่อไม่ขึ้นต้นด้วย
"โรงเรียน" ให้ใช้คำว่า "ผู้อำนวยการโรงเรียน" ทับ ทำให้หน่วยงานอื่นที่กรอกตำแหน่ง
ไว้ถูกแล้วยังได้คำว่าผู้อำนวยการโรงเรียนในเอกสาร และโรงเรียนที่ชื่อไม่ขึ้นต้น
ด้วยคำนั้นก็ไม่มีชื่อโรงเรียนต่อท้าย
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_org_names.py
"""
import pathlib
import re

import pytest

from app.models import School
from app.services.org_names import head_title, head_title_short

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _school(name="", position=None):
    s = School(name=name)
    if position is not None:
        s.director_position = position
    return s


# ------------------------------------------------------------ โรงเรียน
def test_school_gets_its_own_name_in_the_title():
    assert head_title(_school("โรงเรียนบ้านหินลาด")) == "ผู้อำนวยการโรงเรียนบ้านหินลาด"


def test_school_whose_name_does_not_start_with_the_word_still_gets_named():
    """เคยได้แค่ 'ผู้อำนวยการโรงเรียน' ลอย ๆ ไม่มีชื่อโรงเรียน"""
    assert head_title(_school("อนุบาลขอนแก่น")) == "ผู้อำนวยการโรงเรียนอนุบาลขอนแก่น"


def test_position_left_at_the_default_is_not_treated_as_a_custom_title():
    assert head_title(_school("โรงเรียนบ้านหินลาด", "ผู้อำนวยการโรงเรียน")) \
        == "ผู้อำนวยการโรงเรียนบ้านหินลาด"


# ------------------------------------------------------------ หน่วยงานอื่น
def test_other_agency_keeps_the_title_it_set():
    s = _school("เทศบาลตำบลหินลาด", "นายกเทศมนตรีตำบลหินลาด")
    assert head_title(s) == "นายกเทศมนตรีตำบลหินลาด"
    assert "โรงเรียน" not in head_title(s)


def test_other_agency_title_is_never_overwritten_even_when_short():
    s = _school("สำนักงานเขตพื้นที่การศึกษาประถมศึกษาขอนแก่น เขต 1", "ผู้อำนวยการสำนักงานเขต")
    assert head_title(s) == "ผู้อำนวยการสำนักงานเขต"


def test_a_title_that_already_names_the_agency_is_not_doubled():
    s = _school("โรงเรียนบ้านหินลาด", "ผู้อำนวยการโรงเรียนบ้านหินลาด")
    assert head_title(s) == "ผู้อำนวยการโรงเรียนบ้านหินลาด"


def test_generic_school_tail_works_for_สถานศึกษา_too():
    assert head_title(_school("วิทยาลัยการอาชีพเมือง", "หัวหน้าสถานศึกษา")) \
        == "หัวหน้าสถานศึกษาวิทยาลัยการอาชีพเมือง"


# ------------------------------------------------------------ ขอบ
def test_no_name_falls_back_to_the_plain_title():
    assert head_title(_school("")) == "ผู้อำนวยการโรงเรียน"
    assert head_title(_school("", "นายกเทศมนตรี")) == "นายกเทศมนตรี"


def test_blank_position_uses_the_system_default():
    assert head_title(_school("โรงเรียนบ้านหินลาด", "")) == "ผู้อำนวยการโรงเรียนบ้านหินลาด"
    assert head_title(_school("โรงเรียนบ้านหินลาด", "   ")) == "ผู้อำนวยการโรงเรียนบ้านหินลาด"


def test_short_title_never_carries_the_agency_name():
    s = _school("โรงเรียนบ้านหินลาด")
    assert head_title_short(s) == "ผู้อำนวยการโรงเรียน"
    assert head_title_short(_school("เทศบาลตำบลหินลาด", "นายกเทศมนตรี")) == "นายกเทศมนตรี"


# ------------------------------------------------------------ ไม่ให้กติกาเดิมกลับมา
GUESS = re.compile(r"startswith\(\s*[\"']โรงเรียน[\"']\s*\)")


def test_no_file_guesses_the_title_from_the_name_any_more():
    offenders = []
    for p in list((ROOT / "app").rglob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if GUESS.search(line) and "ผู้อำนวยการ" in line:
                offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, "ยังเดาตำแหน่งจากชื่อหน่วยงานอยู่: " + ", ".join(offenders)


def test_the_dead_document_builder_is_gone():
    """docgen.py เป็นโค้ดตายและพังอยู่ (อ้างฟิลด์ supply_officer ที่ไม่มีแล้ว)"""
    assert not (ROOT / "app" / "services" / "docgen.py").exists()
    for p in list((ROOT / "app").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        assert "services.docgen" not in text and "import docgen" not in text, p


# ------------------------------------------------------------ ของจริง: ออกเอกสารให้หน่วยงานที่ไม่ใช่โรงเรียน
@pytest.fixture
def agency(monkeypatch, tmp_path):
    """หน่วยงานที่ไม่ใช่โรงเรียน พร้อมเรื่องจัดซื้อหนึ่งเรื่อง"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Procurement, ProcurementItem
    import app.database as dbm

    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    for mod in ("proc_alt_doc", "w119_doc", "proc_plan_doc"):
        m = __import__(f"app.services.{mod}", fromlist=["x"])
        if hasattr(m, "get_data_dir"):
            monkeypatch.setattr(m, "get_data_dir", lambda: tmp_path)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    school = School(name="เทศบาลตำบลหินลาด", director_name="นายสมชาย ใจดี",
                    director_position="นายกเทศมนตรีตำบลหินลาด",
                    address="อำเภอเมือง จังหวัดขอนแก่น")
    db.add(school)
    proc = Procurement(subject="จัดซื้อวัสดุสำนักงาน", proc_type="ซื้อ",
                       total_amount=5000.0, fiscal_year=2570)
    db.add(proc)
    db.flush()
    db.add(ProcurementItem(procurement_id=proc.id, name="กระดาษ A4", quantity=10,
                           unit_price=500.0))
    db.commit()
    yield proc, school
    db.close()
    engine.dispose()


def _words(path):
    import re
    import zipfile
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def test_procurement_papers_never_say_school_for_another_agency(agency):
    """ของจริง: ตั้งชื่อหน่วยงานเป็นเทศบาล เอกสารพัสดุต้องไม่มีคำว่าโรงเรียนโผล่"""
    import app.services.proc_alt_doc as alt
    import app.services.w119_doc as w119
    proc, school = agency
    made, failed = [], []
    for kind, fn in list(alt.RENDERERS.items()) + list(w119.RENDERERS.items()):
        try:
            made.append((kind, fn(proc, school)))
        except Exception as exc:                 # noqa: BLE001
            failed.append(f"{kind}: {type(exc).__name__}: {exc}")
    assert not failed, failed
    assert made, "ไม่ได้เอกสารสักฉบับ"
    dirty = {kind: [w for w in _words(p).split() if "โรงเรียน" in w]
             for kind, p in made}
    dirty = {k: v for k, v in dirty.items() if v}
    assert not dirty, dirty


def test_procurement_papers_carry_the_agency_title(agency):
    import app.services.proc_alt_doc as alt
    proc, school = agency
    text = _words(alt.RENDERERS["w119t1"](proc, school))
    assert "นายกเทศมนตรีตำบลหินลาด" in text
