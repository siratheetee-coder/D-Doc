"""
doc_number.py
-------------
ระบบรันเลขทะเบียน (เฟส 2) - โหมด "เสนอเลข + แก้ได้ + bump"

ทำไมต้องแก้ได้: เลขบันทึกข้อความ/คำสั่ง มาจากทะเบียนหนังสือกลางของโรงเรียน
ซึ่งมีงานอื่นมาแทรกเลขด้วย ระบบจึงไม่ล็อกเลขตายตัว แต่:
  1) เสนอเลขถัดไปให้ (last + 1)
  2) ผู้ใช้แก้/พิมพ์ทับได้
  3) เมื่อบันทึก ระบบ bump ฐานเป็นเลขที่ใช้จริง (ถ้าสูงกว่าเดิม) -> ครั้งหน้าต่อจากนั้น

ชนิด counter (doc_type):
  memo           = บันทึกข้อความทุกชนิด (ใช้ชุดเดียวต่อเนื่อง)
  command        = คำสั่ง
  purchase_order = ใบสั่งซื้อ
  hire_order     = ใบสั่งจ้าง
"""
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import DocNumberCounter, IssuedDocNo

# ชนิด counter ที่ระบบรองรับ (ไว้ตรวจสอบและแสดงผล)
COUNTER_TYPES = {
    "memo": "บันทึกข้อความ",
    "command": "คำสั่ง",
    "outgoing": "หนังสือส่ง",
    "incoming": "หนังสือรับ",
    "purchase_order": "ใบสั่งซื้อ",
    "hire_order": "ใบสั่งจ้าง",
}


def _get_or_create(db: Session, doc_type: str, fiscal_year: int) -> DocNumberCounter:
    counter = (
        db.query(DocNumberCounter)
        .filter_by(doc_type=doc_type, fiscal_year=fiscal_year)
        .first()
    )
    if counter is None:
        counter = DocNumberCounter(doc_type=doc_type, fiscal_year=fiscal_year, last_number=0)
        db.add(counter)
        db.flush()
    return counter


def suggest_next(db: Session, doc_type: str, fiscal_year: int) -> int:
    """เสนอเลขถัดไป (ไม่บันทึก/ไม่เพิ่มเลข) ใช้แสดงเป็นค่าเริ่มต้นในฟอร์ม"""
    counter = (
        db.query(DocNumberCounter)
        .filter_by(doc_type=doc_type, fiscal_year=fiscal_year)
        .first()
    )
    return (counter.last_number if counter else 0) + 1


def commit_number(db: Session, doc_type: str, fiscal_year: int, used_number: int) -> None:
    """
    บันทึกว่าใช้เลข used_number ไปแล้ว และ bump ฐานเป็นเลขนี้ถ้าสูงกว่าเดิม
    (เรียกตอนผู้ใช้กดบันทึกเอกสาร)
    """
    if not used_number:
        return
    counter = _get_or_create(db, doc_type, fiscal_year)
    if used_number > counter.last_number:
        counter.last_number = used_number
        db.flush()


def format_doc_no(number: int, fiscal_year: int) -> str:
    """จัดรูปเลขที่เอกสาร เช่น 68/2569"""
    return f"{number}/{fiscal_year}"


def parse_seq(doc_no: str) -> int:
    """
    ดึงเฉพาะเลขลำดับจากข้อความเลขที่เอกสาร เช่น '68/2569' -> 68
    คืน 0 ถ้าหาไม่เจอ (เช่น เป็นเครื่องหมาย '-')
    """
    m = re.match(r"\s*(\d+)", doc_no or "")
    return int(m.group(1)) if m else 0


def suggest_doc_no(db: Session, doc_type: str, fiscal_year: int) -> str:
    """เสนอเลขที่เอกสารแบบเต็ม เช่น '68/2569'"""
    return format_doc_no(suggest_next(db, doc_type, fiscal_year), fiscal_year)


def log_issued(db: Session, doc_type: str, fiscal_year: int, seq: int,
               full_no: str = "", source: str = "", ref_id=None, subject: str = "") -> None:
    """บันทึก/อัปเดตเลขที่ใช้จริงลงทะเบียนเลขกลาง (upsert ตาม doc_type+ปีงบ+seq)"""
    if not seq:
        return
    row = (db.query(IssuedDocNo)
           .filter_by(doc_type=doc_type, fiscal_year=fiscal_year, seq=seq).first())
    if row is None:
        row = IssuedDocNo(doc_type=doc_type, fiscal_year=fiscal_year, seq=seq)
        db.add(row)
    row.full_no = full_no or format_doc_no(seq, fiscal_year)
    if source:
        row.source = source
    if ref_id is not None:
        row.ref_id = ref_id
    if subject:
        row.subject = subject
    row.date = datetime.now()
    db.flush()


def commit_doc_no(db: Session, doc_type: str, fiscal_year: int, doc_no: str,
                  source: str = "", ref_id=None, subject: str = "") -> None:
    """แยกเลขลำดับจากข้อความเลขที่ แล้ว bump counter + บันทึกลงทะเบียนเลขกลาง"""
    seq = parse_seq(doc_no)
    commit_number(db, doc_type, fiscal_year, seq)
    if seq:
        log_issued(db, doc_type, fiscal_year, seq, full_no=(doc_no or "").strip(),
                   source=source, ref_id=ref_id, subject=subject)


def check_doc_no(db: Session, doc_type: str, fiscal_year: int, doc_no: str,
                 exclude_ref=None, exclude_source: str = "") -> dict | None:
    """ตรวจเลขที่กรอก คืน None ถ้าปกติ หรือ dict เตือน:
      {'level':'duplicate'|'passed', 'msg':..., 'owner':...}
    - duplicate = มีเลขนี้ในทะเบียนแล้ว (ของเรื่องอื่น)
    - passed    = เลขต่ำกว่า/เท่ากับเลขล่าสุดที่ใช้ไป (เลยเลขมาแล้ว)
    """
    seq = parse_seq(doc_no)
    if not seq:
        return None
    dup = (db.query(IssuedDocNo)
           .filter_by(doc_type=doc_type, fiscal_year=fiscal_year, seq=seq).first())
    if dup and not (exclude_ref is not None and dup.ref_id == exclude_ref and dup.source == exclude_source):
        owner = (dup.subject or "").strip() or "(ไม่ระบุเรื่อง)"
        return {"level": "duplicate",
                "msg": f"เลข {dup.full_no} ถูกใช้แล้ว: {owner}", "owner": owner}
    counter = (db.query(DocNumberCounter)
               .filter_by(doc_type=doc_type, fiscal_year=fiscal_year).first())
    last = counter.last_number if counter else 0
    if seq <= last:
        return {"level": "passed",
                "msg": f"เลขนี้เลยเลขล่าสุดที่ใช้ไปแล้ว (ล่าสุดคือ {last}/{fiscal_year})", "owner": ""}
    return None
