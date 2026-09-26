# -*- coding: utf-8 -*-
"""กระดาษทำการของผู้ตรวจสอบ · บัญชีพัสดุแยกตามสภาพ · หนังสือแจ้งผลการตรวจสอบ

อิงแบบฟอร์มใน "แนวทางการตรวจสอบพัสดุประจำปีและการจำหน่ายพัสดุสำหรับสถานศึกษา"
(ฉบับปรับปรุง พ.ศ. 2563)
"""
import datetime as dt

import pytest
from docx import Document
from docx.oxml.ns import qn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.database as dbm
from app.models import Asset, MaterialItem, MaterialTxn, School
from app.services import asset_audit_papers as ap
from app.services import asset_audit_doc as ad


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ad, "get_data_dir", lambda: tmp_path)
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    dbm.init_school_db(eng)
    with Session(bind=eng) as s:
        yield s


@pytest.fixture()
def school():
    return School(name="โรงเรียนบ้านตัวอย่าง", address="ต.ในเมือง อ.เมือง จ.นครราชสีมา",
                  area_office="สำนักงานเขตพื้นที่การศึกษาประถมศึกษานครราชสีมา เขต 1",
                  director_name="นายเอนก ทดสอบ", head_officer_name="นายหัวหน้า พัสดุ")


CTX = {"year": 2569, "date": dt.datetime(2026, 9, 12),
       "result_date": dt.datetime(2026, 10, 1), "memo_no": "ศธ 04166/1",
       "order_no": "40/2569", "result_memo_no": "ศธ 04166/9", "damaged_count": "4",
       "sao_kind": "จังหวัด", "sao_region": "นครราชสีมา", "phone": "044-000111",
       "area_no": "ศธ 04166/20", "area_date": dt.datetime(2026, 10, 5),
       "sao_no": "ศธ 04166/21", "sao_date": dt.datetime(2026, 10, 5),
       "members": [{"name": "นางสมศรี ตรวจสอบ", "position": "ครู", "role": "ประธานกรรมการ"},
                   {"name": "นายสมชาย นับของ", "position": "ครู", "role": "กรรมการ"}]}


def _seed(db, n=10):
    sts = ["ใช้งาน", "ชำรุด", "เสื่อมสภาพ", "สูญไป", "ไม่ใช้"]
    assets = []
    for i in range(1, n + 1):
        a = Asset(asset_code=f"7440-001-{i:04d}/2569", name=f"ครุภัณฑ์ {i}",
                  category=["ครุภัณฑ์สำนักงาน", "ครุภัณฑ์คอมพิวเตอร์"][i % 2],
                  brand_model=f"รุ่น X-{i}", cost=5000.0, quantity=2, unit="ชุด",
                  useful_life=8, status=sts[i % 5], location="อาคาร 1",
                  fund_type="เงินงบประมาณ", acquire_method="วิธีเฉพาะเจาะจง",
                  acquired_date=dt.datetime(2023, 8, 31))
        db.add(a)
        assets.append(a)
    mats = []
    for i in range(1, 4):
        m = MaterialItem(name=f"วัสดุ {i}", unit="ชิ้น", category="วัสดุสำนักงาน")
        db.add(m)
        db.flush()
        db.add(MaterialTxn(material_id=m.id, kind="in", qty=100, unit_price=12.5,
                           ref=f"ร.{i}/2569", date=dt.datetime(2025, 11, i)))
        db.add(MaterialTxn(material_id=m.id, kind="out", qty=30, note="ครูสมศรี",
                           ref=f"บ.{i}/2569", date=dt.datetime(2026, 2, i)))
        mats.append(m)
    db.commit()
    return assets, mats


def _grid_width(t):
    """ความกว้างตารางจาก tblGrid · row.cells คืนเซลล์ที่ merge ซ้ำหลายตำแหน่ง ใช้บวกไม่ได้"""
    grid = t._tbl.find(qn('w:tblGrid'))
    if grid is None:
        return 0
    return sum(int(gc.get(qn('w:w'))) for gc in grid.findall(qn('w:gridCol'))
               if gc.get(qn('w:w'))) * 635


def _text(path):
    d = Document(path)
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            out += [c.text for c in r.cells]
    return "\n".join(out)


def test_all_papers_render(db, school):
    assets, mats = _seed(db)
    for key, (label, fn, need) in ap.PAPERS.items():
        path = fn(school, CTX, mats if need == "mat" else assets)
        assert len(_text(path)) > 150, key


def test_material_count_uses_ledger_balance(db, school):
    """ช่อง 'จำนวนตามบัญชี' ต้องมาจากยอดคงเหลือจริง (รับ 100 - จ่าย 30 = 70)"""
    _assets, mats = _seed(db)
    txt = _text(ap.render_wp_material_count(school, CTX, mats))
    assert "70" in txt and "วัสดุ 1" in txt


def test_asset_count_ticks_condition(db, school):
    """ชุด ง ต้องติ๊กช่องสภาพให้ตรงกับสถานะในทะเบียน และสูญไป = ไม่มี/สูญหาย"""
    assets, _m = _seed(db)
    doc = Document(ap.render_wp_asset_count(school, CTX, assets))
    t = doc.tables[0]
    rows = {}
    for r in t.rows[2:]:
        cells = [c.text.strip() for c in r.cells]
        if cells[1]:
            rows[cells[1]] = cells
    lost = next(a for a in assets if a.status == "สูญไป")
    got = rows[lost.asset_code]
    assert got[4] == ap.BOX and got[5] == ap.TICK, got[4:6]      # ไม่มี/สูญหาย
    assert got[6:10] == [ap.BOX] * 4, got[6:10]                  # ไม่ติ๊กสภาพ
    broken = next(a for a in assets if a.status == "ชำรุด")
    got = rows[broken.asset_code]
    assert got[4] == ap.TICK and got[7] == ap.TICK, got[4:10]    # มี + ชำรุด


def test_ledger_value_is_unit_cost_times_qty(db, school):
    """แบบฟอร์มกำหนด มูลค่า = ราคาต่อหน่วย x จำนวน (ของทดสอบ 5,000 x 2 = 10,000)"""
    assets, _m = _seed(db)
    txt = _text(ap.render_condition_ledger(school, CTX, assets, "damaged"))
    assert "5,000.00" in txt and "10,000.00" in txt


def test_ledger_splits_by_condition(db, school):
    """แต่ละบัญชีต้องมีเฉพาะครุภัณฑ์ที่สภาพตรงกับบัญชีนั้น"""
    assets, _m = _seed(db)
    for kind, _title, statuses, _r in ap.LEDGERS:
        txt = _text(ap.render_condition_ledger(school, CTX, assets, kind))
        want = {a.asset_code for a in assets if a.status in statuses}
        other = {a.asset_code for a in assets if a.status not in statuses}
        assert all(code in txt for code in want), kind
        assert not any(code in txt for code in other), kind


def test_ledger_bundle_skips_empty(db, school):
    """ไม่มีครุภัณฑ์สภาพไหน ก็ไม่ต้องออกบัญชีฉบับนั้น"""
    assets = [Asset(asset_code="7440-001-0001/2569", name="ของดี", cost=100.0,
                    quantity=1, status="ใช้งาน")]
    with pytest.raises(ValueError):
        ap.render_ledgers_bundle(school, CTX, assets)


def test_letters_name_the_right_offices(db, school):
    """หนังสือแจ้ง 2 ฉบับต้องจ่าหน้าถึงคนละหน่วยงาน และแนบเอกสารคนละชุด"""
    area = _text(ap.render_audit_letter(school, {**CTX, "all_clean": True}, "area"))
    sao = _text(ap.render_audit_letter(school, {**CTX, "all_clean": True}, "sao"))
    assert "สำนักงานเขตพื้นที่การศึกษาประถมศึกษานครราชสีมา เขต 1" in area
    assert "สำนักงานตรวจเงินแผ่นดินจังหวัดนครราชสีมา" in sao
    assert "สำเนาหนังสือแจ้งสำนักงานตรวจเงินแผ่นดิน" in area   # แนบสำเนาหนังสือ สตง. ไปด้วย
    assert "มาตรา 112" in area and "ข้อ 213" in area


def test_letter_wording_follows_result(db, school):
    clean = _text(ap.render_audit_letter(school, {**CTX, "all_clean": True}, "area"))
    dirty = _text(ap.render_audit_letter(school, {**CTX, "all_clean": False}, "area"))
    assert "ไม่มีพัสดุชำรุด" in clean
    assert "มีพัสดุชำรุด" in dirty and "หมวด 9 ส่วนที่ 4" in dirty


def test_single_inspector_wording(db, school):
    """โรงเรียนที่แต่งตั้งคนเดียว เอกสารต้องใช้คำว่า 'ผู้ตรวจสอบพัสดุประจำปี'"""
    ctx1 = {**CTX, "single": True, "members": CTX["members"][:1]}
    txt = _text(ad.render_appoint_order(school, ctx1))
    assert "แต่งตั้งผู้ตรวจสอบพัสดุประจำปี" in txt
    assert "แต่งตั้งคณะกรรมการตรวจสอบพัสดุ" not in txt
    many = _text(ad.render_appoint_order(school, CTX))
    assert "แต่งตั้งคณะกรรมการตรวจสอบพัสดุประจำปี" in many


def test_appoint_order_cites_delegation(db, school):
    """คำสั่งแต่งตั้งต้องอ้าง มาตรา 112 + ข้อ 213 + คำสั่งมอบอำนาจ สพฐ. 1340/2560"""
    txt = _text(ad.render_appoint_order(school, CTX))
    assert "มาตรา 112" in txt and "ข้อ 213" in txt and "1340/2560" in txt


def test_no_table_exceeds_paper(db, school):
    assets, mats = _seed(db, n=14)
    paths = [ap.render_papers_bundle(school, CTX, assets, mats),
             ap.render_ledgers_bundle(school, CTX, assets)]
    for path in paths:
        doc = Document(path)
        widest = max(s.page_width - s.left_margin - s.right_margin for s in doc.sections)
        for ti, t in enumerate(doc.tables):
            w = _grid_width(t)
            assert w <= widest + 20000, f"{path} ตาราง {ti}: {w/360000:.2f} ซม."


def test_bundle_starts_on_page_one(db, school):
    """ฉบับแรกของชุดต้องไม่ขึ้น section ใหม่ ไม่งั้นได้หน้าแรกเปล่า"""
    assets, mats = _seed(db)
    doc = Document(ap.render_papers_bundle(school, CTX, assets, mats))
    first = next(e for e in doc.element.body.iterchildren()
                 if e.tag in (qn('w:p'), qn('w:tbl')))
    from docx.text.paragraph import Paragraph
    assert first.tag == qn('w:tbl') or Paragraph(first, doc).text.strip(), \
        "เอกสารเริ่มด้วยย่อหน้าว่าง = เสี่ยงหน้าแรกเปล่า"
    # 4 ชุด + บัญชีพัสดุที่เหลือไม่ตรง -> 5 section (หน้านอนทั้งหมด) ไม่ใช่ 6
    assert len(doc.sections) == 5, len(doc.sections)


# ------------------- แต่งตั้งผู้ตรวจสอบคนเดียว: ต้องไม่เหลือคำว่า "กรรมการ" -------------------
SOLO = {**CTX, "single": True,
        "members": [{"name": "นายมรรคพันธุ์ คุณวงค์", "position": "ครูชำนาญการ",
                     "role": "ประธานกรรมการ"}]}      # บทบาทที่ค้างมาจากฟอร์ม ต้องถูกทับ


def _roles(path):
    """บทบาทที่ปรากฏในเอกสาร (ไม่รวม 'คณะกรรมการการศึกษาขั้นพื้นฐาน' ในข้อความอ้างระเบียบ)"""
    t = _text(path).replace("คณะกรรมการการศึกษาขั้นพื้นฐาน", "")
    return [w for w in ("ประธานกรรมการ", "กรรมการและเลขานุการ", "กรรมการ") if w in t]


@pytest.mark.parametrize("name", ["memo", "order", "result", "damaged"])
def test_solo_never_says_committee(db, school, name):
    """ติ๊กคนเดียวแล้ว ทุกฉบับต้องใช้ 'ผู้ตรวจสอบพัสดุ' ไม่ใช่ 'ประธานกรรมการ'"""
    assets, _m = _seed(db)
    path = {"memo": lambda: ad.render_appoint_memo(school, SOLO),
            "order": lambda: ad.render_appoint_order(school, SOLO),
            "result": lambda: ad.render_result_memo(school, SOLO, assets),
            "damaged": lambda: ad.render_damaged_list(school, SOLO, assets)}[name]()
    assert ad.SOLO_ROLE in _text(path), name
    assert _roles(path) == [], (name, _roles(path))


def test_solo_lists_one_person_only(db, school):
    """ตารางรายชื่อในคำสั่งต้องมีแถวเดียว แม้ฟอร์มจะส่งชื่อมาหลายคน"""
    many = {**SOLO, "members": SOLO["members"] + [
        {"name": "คนที่สอง", "position": "ครู", "role": "กรรมการ"},
        {"name": "คนที่สาม", "position": "ครู", "role": "กรรมการ"}]}
    doc = Document(ad.render_appoint_order(school, many))
    names = doc.tables[0]
    assert len(names.rows) == 1, [r.cells[1].text for r in names.rows]
    assert names.rows[0].cells[3].text.strip() == ad.SOLO_ROLE
    assert "คนที่สอง" not in _text(ad.render_appoint_order(school, many))


def test_committee_mode_unchanged(db, school):
    """โหมดคณะกรรมการต้องยังเป็นเหมือนเดิม"""
    assets, _m = _seed(db)
    path = ad.render_appoint_order(school, CTX)
    assert "ประธานกรรมการ" in _text(path)
    assert ad.SOLO_ROLE not in _text(path)


def test_solo_papers_sign_once(db, school):
    """กระดาษทำการต้องลงชื่อช่องเดียว ไม่ใช่ 3 ช่องแบบคณะกรรมการ"""
    assets, mats = _seed(db)
    solo = _text(ap.render_wp_material_count(school, SOLO, mats))
    many = _text(ap.render_wp_material_count(school, CTX, mats))
    assert solo.count("ลงชื่อ") == 1, solo.count("ลงชื่อ")
    assert many.count("ลงชื่อ") == 2, many.count("ลงชื่อ")
    assert "ผู้ตรวจสอบพัสดุประจำปี" in solo


def test_mismatch_list_prefills_lost_assets(db, school):
    """บัญชีพัสดุที่เหลือไม่ตรงตามบัญชี: ครุภัณฑ์สถานะ 'สูญไป' ต้องถูกเติมให้ (ทะเบียนมี · นับได้ 0)"""
    assets, mats = _seed(db)
    txt = _text(ap.render_mismatch_list(school, CTX, assets, mats))
    lost = [a for a in assets if a.status == "สูญไป"]
    assert lost
    for a in lost:
        assert a.asset_code in txt, a.asset_code
    assert "เหตุที่พัสดุคงเหลือไม่ตรงตามบัญชีหรือทะเบียน" in txt
    assert "หัวหน้าเจ้าหน้าที่ผู้ตรวจสอบ" in txt and "เจ้าหน้าที่ผู้ตรวจสอบ" in txt
    # ครุภัณฑ์ที่ยังอยู่ครบต้องไม่ถูกลากมาด้วย
    fine = next(a for a in assets if a.status == "ใช้งาน")
    assert fine.asset_code not in txt


def test_mismatch_list_solo_signature(db, school):
    assets, mats = _seed(db)
    txt = _text(ap.render_mismatch_list(school, SOLO, assets, mats))
    assert "ผู้ตรวจสอบพัสดุ" in txt and "หัวหน้าเจ้าหน้าที่ผู้ตรวจสอบ" not in txt
