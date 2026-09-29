# -*- coding: utf-8 -*-
"""ทะเบียนเลขหนังสือต้องตรงกับเรื่องพัสดุเสมอ (1 เอกสาร = 1 เลข)

บั๊กที่เคยเจอจริง
  1. แก้เลขเอกสาร (เช่น ใบสั่งจ้าง 21 -> 22) แล้วเลขเก่ายังค้างในทะเบียน
     กลายเป็นเอกสารใบเดียวมีสองเลข
  2. คัดลอกเรื่อง -> ทะเบียนค้างชื่อ "(สำเนา)" ถึงแม้จะเปลี่ยนชื่อเรื่องใหม่แล้ว
     เพราะหน้าแก้ไขเรื่องไม่เคยอัปเดตทะเบียนเลย
  3. ลบเรื่อง แต่เลขยังค้างอยู่ในทะเบียน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_docno_sync.py
"""
from app.models import IssuedDocNo, Procurement
from app.routers.pages import _sync_proc_docnos
from app.services.doc_number import parse_seq
from tests.test_assignments import _db, _login

MARK = "ทดสอบทะเบียนเลข_"
FY = 2569


def _rows(db, proc_id, doc_type=None):
    q = db.query(IssuedDocNo).filter_by(source="procurement", ref_id=proc_id)
    if doc_type:
        q = q.filter_by(doc_type=doc_type)
    return q.order_by(IssuedDocNo.seq).all()


def _mk(db, **kw):
    kw.setdefault("subject", MARK + "จ้างรถทัศนศึกษา")
    p = Procurement(fiscal_year=FY, proc_type="จ้าง", **kw)
    db.add(p)
    db.flush()
    _sync_proc_docnos(db, p)
    db.commit()
    return p


def _cleanup(db, *procs):
    for p in procs:
        db.query(IssuedDocNo).filter_by(source="procurement", ref_id=p.id).delete(
            synchronize_session=False)
        db.delete(p)
    db.commit()


def test_changing_a_number_replaces_it_not_adds_a_second():
    """แก้เลขใบสั่งจ้าง 21 -> 22: ทะเบียนต้องเหลือเลขเดียว ไม่ใช่มีทั้ง 21 และ 22"""
    db = _db()
    p = _mk(db, memo_no="90/2569", order_no="21/2569")
    try:
        assert [r.seq for r in _rows(db, p.id, "hire_order")] == [21]
        p.order_no = "22/2569"
        _sync_proc_docnos(db, p)
        db.commit()
        assert [r.seq for r in _rows(db, p.id, "hire_order")] == [22], "เลขเก่ายังค้างในทะเบียน"
        assert [r.seq for r in _rows(db, p.id, "memo")] == [90]      # เลขอื่นไม่ถูกกระทบ
    finally:
        _cleanup(db, p)


def test_clearing_a_number_removes_it_from_register():
    db = _db()
    p = _mk(db, memo_no="91/2569", command_no="7/2569")
    try:
        assert _rows(db, p.id, "command")
        p.command_no = ""
        _sync_proc_docnos(db, p)
        db.commit()
        assert not _rows(db, p.id, "command")
    finally:
        _cleanup(db, p)


def test_renaming_subject_updates_register_title():
    """เปลี่ยนชื่อเรื่องแล้ว ทะเบียนต้องขึ้นชื่อใหม่ ไม่ใช่ค้างชื่อ (สำเนา) เดิม"""
    db = _db()
    p = _mk(db, memo_no="92/2569", subject=MARK + "จ้างรถทัศนศึกษา (สำเนา)")
    try:
        assert "(สำเนา)" in _rows(db, p.id, "memo")[0].subject
        p.subject = MARK + "จ้างรถทัศนศึกษาระดับประถมศึกษา 4-6"
        _sync_proc_docnos(db, p)
        db.commit()
        got = _rows(db, p.id, "memo")[0].subject
        assert "(สำเนา)" not in got and "4-6" in got, got
    finally:
        _cleanup(db, p)


def test_edit_page_and_duplicate_keep_register_in_sync():
    """ผ่าน HTTP จริง: คัดลอกเรื่อง -> เปลี่ยนชื่อในหน้าแก้ไข -> ทะเบียนต้องเป็นชื่อใหม่
    และลบเรื่องแล้วเลขต้องหายจากทะเบียนด้วย"""
    c = _login()
    db = _db()
    src = _mk(db, memo_no="93/2569")
    new_id = None
    try:
        r = c.post(f"/procurement/{src.id}/duplicate", follow_redirects=False)
        assert r.status_code == 303, r.status_code
        new_id = int(r.headers["location"].split("/")[2])
        db.expire_all()
        new = db.get(Procurement, new_id)
        assert "(สำเนา)" in (new.subject or "")
        assert _rows(db, new_id, "memo"), "คัดลอกแล้วเลขต้องผูกกับเรื่องใหม่"

        title = MARK + "จ้างรถทัศนศึกษาระดับประถมศึกษา 4-6"
        c.post(f"/procurement/{new_id}/edit",
               data={"fiscal_year": FY, "subject": title, "proc_type": "จ้าง",
                     "memo_no": new.memo_no})
        db.expire_all()
        subj = _rows(db, new_id, "memo")[0].subject
        assert "(สำเนา)" not in subj and title in subj, subj

        c.post(f"/procurement/{new_id}/delete")
        db.expire_all()
        assert not _rows(db, new_id), "ลบเรื่องแล้วเลขต้องไม่ค้างในทะเบียน"
        new_id = None
    finally:
        if new_id:
            p = db.get(Procurement, new_id)
            if p:
                _cleanup(db, p)
        _cleanup(db, src)


def test_startup_prune_clears_leftovers():
    """ตัวเก็บกวาดตอนเปิดระบบ: ลบเลขที่ไม่ตรงกับเรื่องแล้ว + ผูกเลขลอยคืนให้เรื่อง"""
    from app.database import _prune_stale_procurement_docnos
    db = _db()
    p = _mk(db, memo_no="94/2569", order_no="31/2569")
    try:
        # จำลองข้อมูลเก่า: เลขใบสั่งจ้างเก่าที่ค้าง + เลขลอยที่ไม่รู้ว่าของงานไหน
        db.add(IssuedDocNo(doc_type="hire_order", fiscal_year=FY, seq=30, full_no="30/2569",
                           source="procurement", ref_id=p.id, subject="ชื่อเก่า (สำเนา)"))
        db.query(IssuedDocNo).filter_by(source="procurement", ref_id=p.id,
                                        doc_type="memo").update(
            {"source": "", "ref_id": None, "subject": ""}, synchronize_session=False)
        db.commit()
        _prune_stale_procurement_docnos(db.get_bind())
        db.expire_all()
        assert [r.seq for r in _rows(db, p.id, "hire_order")] == [31], "เลขค้างไม่ถูกลบ"
        memo = _rows(db, p.id, "memo")
        assert [r.seq for r in memo] == [94], "เลขลอยไม่ถูกผูกคืนให้เรื่อง"
        assert p.subject in memo[0].subject
    finally:
        db.query(IssuedDocNo).filter_by(doc_type="hire_order", fiscal_year=FY,
                                        seq=30).delete(synchronize_session=False)
        _cleanup(db, p)


def test_parse_seq_ignores_non_numbers():
    assert parse_seq("22/2569") == 22 and parse_seq("-") == 0 and parse_seq("") == 0
