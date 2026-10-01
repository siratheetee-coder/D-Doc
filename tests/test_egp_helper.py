# -*- coding: utf-8 -*-
"""หน้าช่วยกรอก e-GP ต้องมีเลขที่/วันที่ของเอกสารครบทุกใบที่ระบบเก็บ

เดิมตารางมีแค่ 6 ใบ ขาดใบเสนอราคา (ซึ่งยังไม่มีช่องเลขที่ในระบบด้วย)
และขาดคำสั่งแต่งตั้ง กก.คุณลักษณะ / กก.ซื้อ-จ้าง / ใบส่งของ
ครูต้องเปิดเอกสารจริงมาดูเลขเอง ซึ่งเสียเวลาและพิมพ์ผิดง่าย
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_egp_helper.py
"""
from datetime import datetime

import pytest

from app.models import Procurement, Vendor
from app.routers.pages import get_school
from app.services.render import build_context, render_document
from tests.test_assignments import _db, _login

MARK = "ทดสอบeGP_"


def _mk(db):
    v = Vendor(name=MARK + "ร้านทดสอบ", owner_name="นายทดสอบ ใจดี", tax_id="3440100123456")
    db.add(v)
    db.flush()
    p = Procurement(
        fiscal_year=2569, proc_type="จ้าง", subject=MARK + "จ้างรถทัศนศึกษา",
        total_amount=15000, vendor_id=v.id,
        memo_no="208/2569", request_date=datetime(2026, 9, 29),
        spec_memo_no="207/2569", spec_memo_date=datetime(2026, 9, 25),
        spec_cmd_no="54/2569", spec_cmd_date=datetime(2026, 9, 25),
        purchase_cmd_no="53/2569", purchase_cmd_date=datetime(2026, 9, 26),
        command_no="102/2569", command_date=datetime(2026, 9, 29),
        quotation_no="Q68/001", quotation_date=datetime(2026, 9, 29),
        result_memo_no="209/2569", result_memo_date=datetime(2026, 9, 30),
        winner_no="5/2569", winner_date=datetime(2026, 9, 30),
        order_no="22/2569", order_date=datetime(2026, 9, 30),
        delivery_note_no="ส.45", delivery_date=datetime(2026, 10, 5),
        inspect_memo_no="210/2569", inspect_date=datetime(2026, 10, 7),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p, v


@pytest.fixture()
def proc():
    db = _db()
    p, v = _mk(db)
    try:
        yield p
    finally:
        from app.models import Document as Doc
        db.query(Doc).filter_by(procurement_id=p.id).delete(synchronize_session=False)
        db.delete(p)
        db.delete(v)
        db.commit()


def test_quotation_number_is_stored_and_shown(proc):
    c = _login()
    html = c.get(f"/procurement/{proc.id}/egp").text
    assert "ใบเสนอราคา" in html and "Q68/001" in html


@pytest.mark.parametrize("label,value", [
    ("แต่งตั้ง กก.กำหนดคุณลักษณะ/ราคากลาง (บันทึก)", "207/2569"),
    ("คำสั่งแต่งตั้ง กก.กำหนดคุณลักษณะ/ราคากลาง", "54/2569"),
    ("รายงานขอจ้าง", "208/2569"),
    ("คำสั่งแต่งตั้ง กก.จ้าง", "53/2569"),
    ("คำสั่งแต่งตั้งผู้ตรวจรับ", "102/2569"),
    ("ใบเสนอราคา", "Q68/001"),
    ("อนุมัติสั่งซื้อสั่งจ้างและรายงานผลพิจารณา", "209/2569"),
    ("ประกาศผู้ชนะการเสนอราคา", "5/2569"),
    ("ใบสั่งจ้าง / สัญญา", "22/2569"),
    ("ใบส่งของ / ใบส่งมอบงาน", "ส.45"),
    ("บันทึกเสนอผลตรวจรับ", "210/2569"),
])
def test_every_document_number_is_listed(proc, label, value):
    c = _login()
    html = c.get(f"/procurement/{proc.id}/egp").text
    assert label in html, f"ไม่มีแถว {label}"
    assert value in html, f"ไม่มีเลข {value} ของ {label}"


def test_dates_are_buddhist_era(proc):
    c = _login()
    html = c.get(f"/procurement/{proc.id}/egp").text
    for d in ("29/09/2569", "30/09/2569", "07/10/2569", "05/10/2569", "25/09/2569"):
        assert d in html, d


@pytest.mark.parametrize("kind,want", [("ใบเสนอราคา", "Q68/001"), ("ประกาศผู้ชนะ", "5/2569")])
def test_number_prints_on_the_document(proc, kind, want):
    """เลขที่ต้องขึ้นบนตัวเอกสารด้วย ไม่ใช่มีแต่ในหน้า e-GP"""
    import re
    import zipfile
    db = _db()
    path = render_document(kind, proc, get_school(db))
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    assert want in re.sub(r"<[^>]+>", "", xml)


def test_context_falls_back_when_numbers_are_blank(proc):
    """ยังไม่ได้กรอกเลข -> เอกสารขึ้นจุดไข่ปลาให้เขียนเอง ไม่ใช่ค่าว่างเปล่า"""
    db = _db()
    proc.quotation_no = ""
    proc.winner_no = ""
    db.commit()
    ctx = build_context(proc, get_school(db))
    for k in ("quotation_no", "winner_no"):
        assert ctx[k] and ctx[k].strip(".") == "", (k, ctx[k])


def test_result_memo_uses_the_egp_wording(proc):
    """e-GP เรียกขั้นตอนนี้ว่า 'อนุมัติสั่งซื้อสั่งจ้าง' ครูจะได้หาช่องเจอ"""
    c = _login()
    html = c.get(f"/procurement/{proc.id}/egp").text
    assert "อนุมัติสั่งซื้อสั่งจ้างและรายงานผลพิจารณา" in html


def _with_committee(p):
    from sqlalchemy.orm import object_session

    from app.models import Committee, CommitteeMember
    db = object_session(p)
    c = Committee(kind="inspect", mode="committee")
    for i, (nm, role) in enumerate([
            ("นายอมรพรรณ จรนามน", "ประธานกรรมการ"),
            ("นางสาวสุวิญญา พลชำนิ", "กรรมการ"),
            ("เด็กชายทดสอบ", "กรรมการ")], 1):      # ไม่มีนามสกุล
        c.members.append(CommitteeMember(name=nm, position="ครู", role=role, seq=i))
    p.committees.append(c)
    db.commit()


def test_committee_names_split_for_egp_search(proc):
    """e-GP ค้นด้วยชื่อ/นามสกุลแยกช่อง วางชื่อเต็มจะหาไม่เจอ -> ต้องคัดลอกแยกได้"""
    _with_committee(proc)
    html = _login().get(f"/procurement/{proc.id}/egp").text
    assert ">อมรพรรณ<" in html and ">จรนามน<" in html
    assert ">สุวิญญา<" in html and ">พลชำนิ<" in html
    assert "นายอมรพรรณ จรนามน" in html          # ชื่อเต็มยังคัดลอกได้อยู่
    assert "นาย" in html and "นางสาว" in html   # คำนำหน้าบอกให้เลือกใน dropdown


def test_member_without_surname_does_not_break(proc):
    _with_committee(proc)
    html = _login().get(f"/procurement/{proc.id}/egp").text
    assert ">ทดสอบ<" in html
    assert html.count("คัดลอก") > 10


def test_date_copies_digits_by_default(proc):
    """ช่องวันที่ของ e-GP เติม / ให้เอง ถ้าวางแบบมี / ไปด้วยจะตัดท้ายทิ้ง
    (30/09/2569 -> 30/09/25) ปุ่มหลักจึงต้องคัดลอกเป็นตัวเลขล้วน"""
    html = _login().get(f"/procurement/{proc.id}/egp").text
    assert "cpText(this,'30092569')" in html, "ปุ่มหลักไม่ได้คัดลอกตัวเลขล้วน"
    assert "แบบมี /" in html and "30/09/2569" in html    # ทางเลือกยังอยู่
    for d in ("29092569", "07102569", "25092569"):
        assert d in html, d
