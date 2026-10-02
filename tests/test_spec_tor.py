# -*- coding: utf-8 -*-
"""ชุดเอกสารตามระเบียบฯ ข้อ 21 (ร่างขอบเขตของงาน/รายละเอียดคุณลักษณะเฉพาะ)

กติกาที่ต้องถูก
  - ข้อ 21 ให้เลือกได้ 2 ทาง: มอบหมายบุคคลใดบุคคลหนึ่ง หรือ แต่งตั้งคณะกรรมการ
  - ทางมอบหมาย: บันทึกมอบหมาย 1 ใบ ไม่ต้องมีคำสั่งแต่งตั้ง (ครุฑ)
  - ทางคณะกรรมการ: บันทึกขออนุมัติ + คำสั่งแต่งตั้ง + TOR ลงนามครบคณะ
  - คำเรียกต้องตรงประเภท: ซื้อ = รายละเอียดคุณลักษณะเฉพาะ · จ้าง = ขอบเขตของงาน
  - ข้อ 21 อยู่ในระเบียบกระทรวงการคลัง ไม่ใช่ พ.ร.บ. (เคยอ้างผิด)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_spec_tor.py
"""
import importlib.util
import pathlib
import re
import sys
import tempfile
import zipfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _text(path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    from app.services.build_templates import ensure_templates
    ensure_templates(force=True)
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from app.models import School
    from app.tenancy import session_for
    db = session_for(1)
    school = db.query(School).first()
    school.delegation_cmd_no = "1340/2566"
    school.delegation_cmd_date = datetime(2023, 9, 1)
    db.commit()
    return db, school


def _make(db, *, mode="single", proc_type="ซื้อ", members=None):
    from app.models import Committee, CommitteeMember, Procurement, ProcurementItem
    members = members or [("นางสาวสมหญิง ใจดี", "ครู", "ผู้ได้รับมอบหมาย")]
    p = Procurement(fiscal_year=2569, subject="วัสดุสำนักงาน", proc_type=proc_type,
                    method="เฉพาะเจาะจง", budget_source="อุดหนุน",
                    purpose="มีความจำเป็นต้องจัดหาวัสดุสำนักงาน",
                    spec_memo_no="ศธ 04000/15", spec_memo_date=datetime(2026, 10, 1),
                    spec_cmd_no="25/2569", spec_cmd_date=datetime(2026, 10, 1),
                    total_amount=2500.0, request_date=datetime(2026, 10, 1))
    p.items.append(ProcurementItem(name="ซองเอกสาร", quantity=500, unit="ซอง",
                                   unit_price=5, spec="ขนาด A4 กระดาษคราฟท์"))
    c = Committee(kind="spec", mode=mode)
    for i, (name, pos, role) in enumerate(members):
        c.members.append(CommitteeMember(name=name, position=pos, role=role, seq=i))
    p.committees.append(c)
    db.add(p)
    db.commit()
    return p


COMMITTEE = [("นายสมชาย รักเรียน", "ครู", "ประธานกรรมการ"),
             ("นางสาวสมหญิง ใจดี", "ครู", "กรรมการ"),
             ("นางมาลี พัสดุดี", "ครู", "กรรมการ")]


def test_single_assignment_needs_no_appointment_order(env):
    """มอบหมายคนเดียวตามข้อ 21 วรรคท้าย ไม่ต้องออกคำสั่งแต่งตั้ง (ครุฑ)"""
    db, school = env
    from app.services.render import kinds_for
    p = _make(db, mode="single")
    kinds = kinds_for(p)
    assert "แต่งตั้งกรรมการคุณลักษณะ" in kinds
    assert "รายละเอียดคุณลักษณะ(TOR)" in kinds
    assert "คำสั่งแต่งตั้งกรรมการคุณลักษณะ" not in kinds


def test_committee_mode_gets_the_order(env):
    db, school = env
    from app.services.render import kinds_for
    p = _make(db, mode="committee", members=COMMITTEE)
    assert "คำสั่งแต่งตั้งกรรมการคุณลักษณะ" in kinds_for(p)


def test_memo_wording_follows_the_mode(env):
    db, school = env
    from app.services.render import render_document
    single = _text(render_document("แต่งตั้งกรรมการคุณลักษณะ", _make(db, mode="single"), school))
    assert "จึงเห็นควรมอบหมาย" in single and "นางสาวสมหญิง ใจดี" in single
    assert "ข้อ 21" in single and "ระเบียบกระทรวงการคลัง" in single

    group = _text(render_document("แต่งตั้งกรรมการคุณลักษณะ",
                                  _make(db, mode="committee", members=COMMITTEE), school))
    assert "จึงเห็นควรแต่งตั้งคณะกรรมการ" in group
    assert "นายสมชาย รักเรียน" in group and "ประธานกรรมการ" in group


def test_order_cites_the_delegation(env):
    """คำสั่งต้องอ้างคำสั่งมอบอำนาจของ สพฐ. ที่โรงเรียนตั้งค่าไว้"""
    db, school = env
    from app.services.render import render_document
    p = _make(db, mode="committee", members=COMMITTEE)
    text = _text(render_document("คำสั่งแต่งตั้งกรรมการคุณลักษณะ", p, school))
    assert "1340/2566" in text
    assert "มาตรา 61" in text and "มาตรา 100" in text
    assert "ข้อ 21 ข้อ 25" in text
    assert "มาตรา 56 วรรคหนึ่ง (2) (ข)" in text      # วิธีเฉพาะเจาะจง


def test_tor_has_every_required_section(env):
    db, school = env
    from app.services.render import render_document
    text = _text(render_document("รายละเอียดคุณลักษณะ(TOR)", _make(db, mode="single"), school))
    for head in ("1. ความเป็นมา", "2. วัตถุประสงค์", "3. คุณสมบัติผู้ยื่นข้อเสนอ",
                 "4. รายละเอียดคุณลักษณะเฉพาะหรือขอบเขตของงาน",
                 "5. การเสนอราคา และกำหนดส่งมอบ", "6. เกณฑ์การพิจารณาผลการยื่นข้อเสนอ",
                 "7. งบประมาณในการดำเนินการ", "8. อัตราค่าปรับ",
                 "9. การรับประกันความชำรุดบกพร่อง", "10. หน่วยงานที่รับผิดชอบ"):
        assert head in text, head
    assert "ขนาด A4 กระดาษคราฟท์" in text          # คอลัมน์คุณลักษณะเฉพาะรายรายการ
    assert "ยืนราคาไม่น้อยกว่า 30 วัน" in text


def test_tor_signature_follows_the_mode(env):
    db, school = env
    from app.services.render import render_document
    single = _text(render_document("รายละเอียดคุณลักษณะ(TOR)", _make(db, mode="single"), school))
    assert "ผู้จัดทำร่างขอบเขตของงาน" in single
    assert "เจ้าหน้าที่พัสดุ" not in single
    assert "ประธานกรรมการ" not in single

    group = _text(render_document("รายละเอียดคุณลักษณะ(TOR)",
                                  _make(db, mode="committee", members=COMMITTEE), school))
    assert "ประธานกรรมการ" in group
    assert "ประธานกรรมการขอบเขตของงาน" not in group
    assert group.count("(ลงชื่อ)") >= 3


def test_hire_job_is_not_called_a_specification_of_goods(env):
    """งานจ้างต้องเรียกว่าขอบเขตของงาน ไม่ใช่ 'คุณลักษณะเฉพาะของงานจ้างที่จะจ้าง'"""
    db, school = env
    from app.services.render import render_document
    text = _text(render_document("รายละเอียดคุณลักษณะ(TOR)",
                                 _make(db, mode="single", proc_type="จ้าง"), school))
    assert "คุณลักษณะเฉพาะของงานจ้างที่จะจ้าง" not in text
    assert "จัดจ้าง" in text
    assert "งานจ้างให้คิดค่าปรับเป็นรายวัน" in text     # ข้อ 8 แยกซื้อ/จ้าง


def test_clause_21_is_cited_as_a_ministry_regulation(env):
    """ข้อ 21 อยู่ในระเบียบกระทรวงการคลัง ไม่ใช่ พ.ร.บ. (พ.ร.บ. เรียกเป็นมาตรา)"""
    db, school = env
    from app.services.render import render_document
    text = _text(render_document("แต่งตั้งกรรมการคุณลักษณะ", _make(db, mode="single"), school))
    bad = re.search(r"พระราชบัญญัติ[^\n]{0,80}\(ข้อ 21\)", text)
    assert not bad, bad.group(0) if bad else ""


def test_old_records_without_a_mode_still_render(env):
    """เรื่องเก่าที่ไม่มีค่า mode ให้ดูจากจำนวนคนที่กรอกไว้"""
    db, school = env
    from app.services.render import spec_mode_of
    p1 = _make(db, mode="", members=[("นางสาวสมหญิง ใจดี", "ครู", "")])
    p2 = _make(db, mode="", members=COMMITTEE)
    assert spec_mode_of(p1) == "single"
    assert spec_mode_of(p2) == "committee"


def test_tor_fields_survive_reference_saves_and_allow_clear(env):
    from app.routers.pages import _populate_tor_fields, _populate_proc_from_form
    from starlette.datastructures import FormData
    db, school = env
    p = _make(db)
    _populate_proc_from_form(p, FormData(dict(subject='วัสดุสำนักงาน', fiscal_year='2569', purpose='ใช้ในการเรียนการสอน', objective='เพื่อพัฒนาการเรียนรู้', quote_valid_days='45', warranty_text='2 ปี', fix_days='14')), db)
    db.commit(); db.expire_all()
    assert (p.objective, p.quote_valid_days, p.warranty_text, p.fix_days) == ('เพื่อพัฒนาการเรียนรู้', 45, '2 ปี', 14)
    _populate_tor_fields(p, FormData(dict(memo_no='123')))
    db.commit(); db.expire_all()
    assert p.objective == 'เพื่อพัฒนาการเรียนรู้' and p.fix_days == 14
    from app.services.render import render_document
    text = _text(render_document('รายละเอียดคุณลักษณะ(TOR)', p, school))
    assert 'เพื่อพัฒนาการเรียนรู้' in text and '45 วัน' in text and '2 ปี' in text
    _populate_tor_fields(p, FormData(dict(objective='')))
    assert p.objective == ''


def test_assignment_uses_selected_position_and_borderless_member_rows(env):
    from app.services.render import render_document, build_context
    from docx import Document
    db, school = env
    p = _make(db, members=[('นายทดสอบ งานร่าง', 'ครูชำนาญการพิเศษ', 'ผู้ได้รับมอบหมาย')])
    text = _text(render_document('แต่งตั้งกรรมการคุณลักษณะ', p, school))
    assert 'จึงเห็นควรมอบหมาย นายทดสอบ งานร่าง ตำแหน่ง ครูชำนาญการพิเศษ' in text
    p2 = _make(db, mode='committee', members=COMMITTEE)
    doc = Document(render_document('แต่งตั้งกรรมการคุณลักษณะ', p2, school))
    table = next(t for t in doc.tables if 'นายสมชาย รักเรียน' in t._element.xml)
    assert len(table.rows) == 3
    for row, member in zip(table.rows, COMMITTEE):
        assert member[0] in row.cells[1].text
        assert member[1] in row.cells[2].text
        assert member[2] in row.cells[3].text
    p3 = _make(db); p3.committees.clear()
    assert build_context(p3, school)['spec_drafter_position'] != 'เจ้าหน้าที่พัสดุ'
