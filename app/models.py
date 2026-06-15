"""
models.py
---------
นิยาม "ตาราง" ในฐานข้อมูล (แต่ละคลาส = 1 ตาราง)

เฟส 2 เพิ่ม:
- Person      : รายชื่อครู/บุคลากร (มาสเตอร์ลิสต์ ใช้เลือกเป็นกรรมการ/ผู้ลงนาม)
- Department  : ฝ่าย/งานที่ขอจัดซื้อ (มาสเตอร์ลิสต์)
- Project     : ชื่อโครงการ (มาสเตอร์ลิสต์)
- Committee + CommitteeMember : คณะกรรมการ/ผู้ตรวจรับในแต่ละเรื่อง
- ฟิลด์เพิ่มใน Procurement (ราคากลาง, กำหนดส่งมอบ, ค่าปรับ, เลขเอกสารหลายชนิด ฯลฯ)
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint, Boolean
)
from sqlalchemy.orm import relationship

from app.database import Base


class School(Base):
    """ข้อมูลโรงเรียน (ตั้งค่าครั้งเดียว ใช้เติมหัวกระดาษเอกสาร)"""
    __tablename__ = "school"

    id = Column(Integer, primary_key=True)
    name = Column(String, default="")              # ชื่อโรงเรียน
    address = Column(Text, default="")             # ที่อยู่ (บรรทัดเดียวสำหรับส่วนราชการ)
    district = Column(String, default="")          # อำเภอ
    province = Column(String, default="")          # จังหวัด

    director_name = Column(String, default="")     # ชื่อผู้อำนวยการ
    director_position = Column(String, default="ผู้อำนวยการโรงเรียน")

    officer_name = Column(String, default="")      # เจ้าหน้าที่ (พัสดุ)
    head_officer_name = Column(String, default="") # หัวหน้าเจ้าหน้าที่ (พัสดุ)

    finance_officer_name = Column(String, default="")  # เจ้าหน้าที่การเงิน
    finance_head_name = Column(String, default="")     # หัวหน้าเจ้าหน้าที่การเงิน
    admin_officer_name = Column(String, default="")    # เจ้าหน้าที่ธุรการ

    doc_prefix = Column(String, default="ศธ")      # อักษรนำเลขที่หนังสือ

    # เกณฑ์วงเงิน (บาท) ที่ใช้แบ่ง "ชุดเอกสารแบบย่อ + ผู้ตรวจรับคนเดียว"
    # ออกจาก "ชุดเต็ม + คณะกรรมการตรวจรับ" — ปรับได้ตามแต่ละโรงเรียน
    doc_set_threshold = Column(Float, default=5000.0)

    ai_api_key = Column(String, default="")        # Anthropic API key (สำหรับอ่านไฟล์ด้วย AI ทางเลือก)


class Person(Base):
    """รายชื่อครู/บุคลากร (มาสเตอร์ลิสต์) ใช้เลือกเป็นกรรมการหรือผู้ลงนาม"""
    __tablename__ = "person"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # ชื่อ-นามสกุล (มีคำนำหน้า)
    position = Column(String, default="ครู")       # ตำแหน่ง
    active = Column(Boolean, default=True)


class Department(Base):
    """ฝ่าย/งานที่ขอจัดซื้อ (มาสเตอร์ลิสต์)"""
    __tablename__ = "department"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # เช่น ฝ่ายบริหารงานวิชาการ


class Project(Base):
    """ชื่อโครงการ (มาสเตอร์ลิสต์)"""
    __tablename__ = "project"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    budget = Column(Float, default=0.0)            # วงเงินงบประมาณของโครงการ (บาท)
    budget_note = Column(String, default="")       # รายละเอียด/แหล่งงบเพิ่มเติม


class Vendor(Base):
    """ผู้ขาย / ผู้รับจ้าง"""
    __tablename__ = "vendor"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # ชื่อ-นามสกุล หรือชื่อร้าน
    tax_id = Column(String, default="")            # เลขประจำตัวผู้เสียภาษี
    address = Column(Text, default="")             # ที่อยู่
    phone = Column(String, default="")             # เบอร์โทร
    bank_account = Column(String, default="")      # เลขบัญชีธนาคาร
    owner_name = Column(String, default="")        # ชื่อเจ้าของ/ผู้มีอำนาจลงนาม (นาย/นาง/นางสาว...)

    procurements = relationship("Procurement", back_populates="vendor")


class Procurement(Base):
    """เรื่องจัดซื้อ/จัดจ้าง 1 เรื่อง = แม่ของทุกอย่าง"""
    __tablename__ = "procurement"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)  # ปีงบประมาณ พ.ศ. เช่น 2569

    subject = Column(String, nullable=False)       # ชื่อเรื่อง/รายการที่จัดซื้อ
    project_name = Column(String, default="")      # ชื่อโครงการ
    department = Column(String, default="")        # ฝ่าย/งานที่ขอ
    purpose = Column(Text, default="")             # เหตุผลความจำเป็น

    proc_type = Column(String, default="ซื้อ")     # ซื้อ / จ้าง
    method = Column(String, default="เฉพาะเจาะจง") # วิธีจัดซื้อจัดจ้าง

    budget_source = Column(String, default="เงินอุดหนุน")  # แหล่งงบประมาณ
    total_amount = Column(Float, default=0.0)      # วงเงินรวม (บาท)
    price_ref_source = Column(String, default="การสืบราคาจากท้องตลาด")  # ที่มาราคากลาง

    delivery_days = Column(Integer, default=7)     # กำหนดส่งมอบภายใน (วัน)
    penalty_rate = Column(Float, default=0.10)     # อัตราค่าปรับ ร้อยละต่อวัน
    overdue_days = Column(Integer, default=0)      # ส่งมอบเกินกำหนด (วัน) -> คำนวณค่าปรับ

    vat_mode = Column(String, default="none")      # none = ไม่คิด VAT, include = ราคารวม VAT 7%
    order_signer = Column(String, default="director")  # ผู้ลงนามใบสั่ง: director / head_officer

    delivery_note_no = Column(String, default="")  # เลขที่ใบส่งของ (งานซื้อ)
    delivery_note_book = Column(String, default="")  # เล่มที่ใบส่งของ

    # โหมดตรวจรับ: "single" = ผู้ตรวจรับคนเดียว (โดยอนุโลม) / "committee" = คณะกรรมการ
    inspection_mode = Column(String, default="single")

    # เลขเอกสารแต่ละชนิด (เสนออัตโนมัติ แก้เองได้) — เก็บเป็นข้อความ เช่น "68/2569"
    memo_no = Column(String, default="")           # รายงานขอซื้อ/จ้าง (เลขหลัก ใช้ในทะเบียน)
    spec_memo_no = Column(String, default="")      # บันทึกแต่งตั้ง กก.กำหนดคุณลักษณะ
    result_memo_no = Column(String, default="")    # รายงานผลพิจารณาและขออนุมัติสั่งซื้อ
    inspect_memo_no = Column(String, default="")   # บันทึกเสนอผลตรวจรับ+ขอเบิกจ่าย
    command_no = Column(String, default="")        # คำสั่งแต่งตั้งคณะกรรมการตรวจรับ
    order_no = Column(String, default="")          # ใบสั่งซื้อ/ใบสั่งจ้าง

    status = Column(String, default="ร่าง")        # ร่าง/อนุมัติ/ตรวจรับแล้ว/เบิกจ่ายแล้ว

    vendor_id = Column(Integer, ForeignKey("vendor.id"), nullable=True)
    request_date = Column(DateTime, default=datetime.now)   # วันที่รายงานขอซื้อ
    # วันที่ที่เกิดภายหลัง (แก้ไขได้ในหน้ารายละเอียด)
    order_date = Column(DateTime, nullable=True)            # วันที่ใบสั่งซื้อ/สั่งจ้าง
    delivery_due_date = Column(DateTime, nullable=True)     # ครบกำหนดส่งมอบ
    delivery_date = Column(DateTime, nullable=True)         # วันที่ส่งมอบจริง (ใบส่งมอบงาน)
    inspect_date = Column(DateTime, nullable=True)          # วันที่ตรวจรับพัสดุ
    spec_memo_date = Column(DateTime, nullable=True)        # วันที่แต่งตั้ง กก.กำหนดคุณลักษณะ
    result_memo_date = Column(DateTime, nullable=True)      # วันที่รายงานผลพิจารณา
    command_date = Column(DateTime, nullable=True)          # วันที่คำสั่งแต่งตั้งผู้ตรวจรับ
    file_path = Column(String, default="")                 # ไฟล์ต้นฉบับที่อัปโหลด (สร้างเรื่องจากไฟล์)
    created_at = Column(DateTime, default=datetime.now)

    vendor = relationship("Vendor", back_populates="procurements")
    items = relationship("ProcurementItem", back_populates="procurement",
                         cascade="all, delete-orphan")
    committees = relationship("Committee", back_populates="procurement",
                             cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="procurement",
                            cascade="all, delete-orphan")

    @property
    def doc_no(self) -> str:
        """ความเข้ากันได้ย้อนหลัง: เลขหลัก = เลขรายงานขอซื้อ"""
        return self.memo_no or ""


class ProcurementItem(Base):
    """รายการพัสดุย่อยในแต่ละเรื่อง"""
    __tablename__ = "procurement_item"

    id = Column(Integer, primary_key=True)
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=False)

    name = Column(String, nullable=False)          # ชื่อพัสดุ
    quantity = Column(Float, default=1)            # จำนวน
    unit = Column(String, default="หน่วย")         # หน่วยนับ
    unit_price = Column(Float, default=0.0)        # ราคาต่อหน่วย

    procurement = relationship("Procurement", back_populates="items")

    @property
    def amount(self) -> float:
        return (self.quantity or 0) * (self.unit_price or 0)


class Committee(Base):
    """
    คณะกรรมการ/ผู้ตรวจรับในแต่ละเรื่อง
    kind: "spec" = กำหนดคุณลักษณะ/ราคากลาง, "inspect" = ตรวจรับพัสดุ
    mode: "single" = คนเดียว, "committee" = คณะกรรมการ
    """
    __tablename__ = "committee"

    id = Column(Integer, primary_key=True)
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=False)
    kind = Column(String, default="inspect")
    mode = Column(String, default="committee")

    procurement = relationship("Procurement", back_populates="committees")
    members = relationship("CommitteeMember", back_populates="committee",
                          cascade="all, delete-orphan", order_by="CommitteeMember.seq")


class CommitteeMember(Base):
    """กรรมการแต่ละคนในคณะกรรมการ"""
    __tablename__ = "committee_member"

    id = Column(Integer, primary_key=True)
    committee_id = Column(Integer, ForeignKey("committee.id"), nullable=False)

    name = Column(String, nullable=False)          # ชื่อ-นามสกุล
    position = Column(String, default="ครู")       # ตำแหน่ง
    role = Column(String, default="กรรมการ")       # ประธานกรรมการ/กรรมการ/กรรมการและเลขานุการ/ผู้ตรวจรับ
    seq = Column(Integer, default=0)               # ลำดับ

    committee = relationship("Committee", back_populates="members")


class DocNumberCounter(Base):
    """
    ตัวรันเลขทะเบียน — แยกตาม (ชนิดเอกสาร + ปีงบประมาณ)
    ชนิด: memo (บันทึกข้อความรวม), command (คำสั่ง),
          purchase_order (ใบสั่งซื้อ), hire_order (ใบสั่งจ้าง)
    """
    __tablename__ = "doc_number_counter"
    __table_args__ = (
        UniqueConstraint("doc_type", "fiscal_year", name="uq_doctype_year"),
    )

    id = Column(Integer, primary_key=True)
    doc_type = Column(String, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    last_number = Column(Integer, default=0)


class IssuedDocNo(Base):
    """ทะเบียนเลขหนังสือกลาง — บันทึกทุกเลขที่ถูกใช้จริง (ทุกงาน) ต่อชนิด/ปีงบ
    ใช้ตรวจเลขซ้ำ/เลขเลยมาแล้ว และเป็นทะเบียนเลขรวมของโรงเรียน"""
    __tablename__ = "issued_doc_no"
    __table_args__ = (
        UniqueConstraint("doc_type", "fiscal_year", "seq", name="uq_issued_type_year_seq"),
    )

    id = Column(Integer, primary_key=True)
    doc_type = Column(String, nullable=False)      # memo / command / outgoing / incoming / ...
    fiscal_year = Column(Integer, nullable=False)
    seq = Column(Integer, nullable=False)          # เลขลำดับ
    full_no = Column(String, default="")           # เลขเต็ม เช่น 68/2569
    source = Column(String, default="")            # admin / procurement / finance
    ref_id = Column(Integer, nullable=True)         # id ของเรื่องต้นทาง
    subject = Column(String, default="")           # เรื่อง (ไว้แสดงว่าเลขนี้ของอะไร)
    date = Column(DateTime, default=datetime.now)


class Document(Base):
    """เอกสารที่สร้างออกมาแล้ว (เก็บประวัติ + ที่อยู่ไฟล์)"""
    __tablename__ = "document"

    id = Column(Integer, primary_key=True)
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=False)

    doc_kind = Column(String, nullable=False)      # ชนิดเอกสาร
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    procurement = relationship("Procurement", back_populates="documents")


# ============================================================
# งานธุรการ: ทะเบียนหนังสือรับ-ส่ง / บันทึกข้อความ / คำสั่ง
# ============================================================

class IncomingLetter(Base):
    """ทะเบียนหนังสือรับ (หนังสือที่รับเข้ามาจากหน่วยงานภายนอก)"""
    __tablename__ = "incoming_letter"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    recv_no = Column(Integer, default=0)           # เลขทะเบียนรับ (รันอัตโนมัติ)
    recv_date = Column(DateTime, nullable=True)     # วันที่รับ
    letter_no = Column(String, default="")          # ที่หนังสือ (ของผู้ส่ง)
    letter_date = Column(DateTime, nullable=True)   # ลงวันที่ (ของหนังสือ)
    from_org = Column(String, default="")           # จาก (หน่วยงาน)
    to_person = Column(String, default="")          # มอบให้/ถึง
    subject = Column(String, default="")            # เรื่อง
    action_note = Column(String, default="")        # การปฏิบัติ/หมายเหตุ
    file_path = Column(String, default="")          # ไฟล์ PDF ต้นฉบับที่แนบ (จาก AMSS)
    created_at = Column(DateTime, default=datetime.now)


class OutgoingLetter(Base):
    """ทะเบียนหนังสือส่ง (หนังสือออกภายนอก เลขที่ ศธ.../เลข)"""
    __tablename__ = "outgoing_letter"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    send_seq = Column(Integer, default=0)           # เลขลำดับหนังสือส่ง
    send_no = Column(String, default="")            # เลขที่เต็ม เช่น ศธ 04123/45
    date = Column(DateTime, nullable=True)          # ลงวันที่
    to_org = Column(String, default="")             # ถึง (หน่วยงานปลายทาง)
    subject = Column(String, default="")            # เรื่อง
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class OfficeMemo(Base):
    """บันทึกข้อความภายใน (ใช้เลขชุด 'memo' ร่วมกับทุกงานในโรงเรียน)"""
    __tablename__ = "office_memo"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    memo_no = Column(String, default="")            # เลขที่บันทึก เช่น 68/2569
    seq = Column(Integer, default=0)
    date = Column(DateTime, nullable=True)
    from_dept = Column(String, default="")          # ส่วนราชการ/ฝ่ายที่ออก
    to_person = Column(String, default="")          # เรียน
    subject = Column(String, default="")            # เรื่อง
    body = Column(Text, default="")                 # เนื้อหา (หลายย่อหน้า)
    signer_name = Column(String, default="")        # ผู้ลงนาม
    signer_position = Column(String, default="")    # ตำแหน่งผู้ลงนาม
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class SchoolOrder(Base):
    """คำสั่งโรงเรียน (ใช้เลขชุด 'command' ร่วมทั้งโรงเรียน)"""
    __tablename__ = "school_order"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    order_no = Column(String, default="")           # เลขที่คำสั่ง เช่น 12/2569
    seq = Column(Integer, default=0)
    date = Column(DateTime, nullable=True)
    subject = Column(String, default="")            # เรื่อง
    body = Column(Text, default="")                 # เนื้อหาคำสั่ง
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


# ============================================================
# เฟส 3: ทะเบียนครุภัณฑ์ (+ค่าเสื่อม) และบัญชีวัสดุ (+ใบเบิก)
# ============================================================

# ============================================================
# งานการเงิน: ทะเบียนคุมเงินแยกบัญชี / ขอเบิกจ่าย / ใบเสร็จ-ใบสำคัญ
# ============================================================

class FinanceAccount(Base):
    """บัญชี/ประเภทเงิน (เงินอุดหนุน, รายได้สถานศึกษา, อาหารกลางวัน ฯลฯ)
    ยอดคงเหลือ = ยอดยกมา + รวมรับ - รวมจ่าย (คำนวณจากการเคลื่อนไหว)"""
    __tablename__ = "finance_account"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)            # ชื่อบัญชี/ประเภทเงิน
    opening_balance = Column(Float, default=0.0)     # ยอดยกมา (ต้นปีงบ)
    deposit_type = Column(String, default="bank")    # เก็บเงินไว้ที่: cash/bank/agency (สำหรับรายงานเงินคงเหลือ)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    txns = relationship("FinanceTxn", back_populates="account",
                        cascade="all, delete-orphan", order_by="FinanceTxn.id")
    openings = relationship("AccountOpening", back_populates="account",
                            cascade="all, delete-orphan")
    items = relationship("AccountItem", back_populates="account",
                         cascade="all, delete-orphan")


class AccountOpening(Base):
    """ยอดยกมาของบัญชี แยกตามปีงบประมาณ (ทำให้แต่ละปีเป็น 'เล่ม' แยกกัน)
    ปีที่ไม่มีระเบียนนี้ จะใช้ FinanceAccount.opening_balance เป็นยอดตั้งต้น"""
    __tablename__ = "account_opening"
    __table_args__ = (
        UniqueConstraint("account_id", "fiscal_year", name="uq_acct_open_year"),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("finance_account.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    amount = Column(Float, default=0.0)

    account = relationship("FinanceAccount", back_populates="openings")


class AccountItem(Base):
    """หมวด/รายการย่อยในบัญชี แยกตามปีงบ (เช่น เงินอุดหนุน -> ค่าจัดการเรียนการสอน,
    ค่าหนังสือเรียน, ค่าอุปกรณ์...) แต่ละหมวดมีงบที่ตั้งไว้ + ติดตามรับ-จ่าย-คงเหลือรายหมวด"""
    __tablename__ = "account_item"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("finance_account.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    name = Column(String, nullable=False)            # ชื่อหมวด/รายการ
    budget = Column(Float, default=0.0)              # งบที่ตั้งไว้/ได้รับจัดสรร
    deposit_type = Column(String, default="bank")    # เก็บเงินไว้ที่: cash/bank/agency
    note = Column(String, default="")

    account = relationship("FinanceAccount", back_populates="items")


class FinanceTxn(Base):
    """การเคลื่อนไหวเงิน: รับ (in) / จ่าย (out) ของแต่ละบัญชี"""
    __tablename__ = "finance_txn"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("finance_account.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("account_item.id"), nullable=True)  # หมวดที่ผูก (ถ้ามี)
    fiscal_year = Column(Integer, nullable=False)
    date = Column(DateTime, default=datetime.now)
    kind = Column(String, default="in")              # in = รับ, out = จ่าย
    amount = Column(Float, default=0.0)
    category = Column(String, default="")            # หมวด/ประเภทรายการ
    ref = Column(String, default="")                 # อ้างอิงเอกสาร (เลขที่เรื่อง/ใบเสร็จ)
    note = Column(String, default="")
    disburse_id = Column(Integer, ForeignKey("disburse_memo.id"), nullable=True)

    account = relationship("FinanceAccount", back_populates="txns")
    item = relationship("AccountItem")


class DisburseMemo(Base):
    """บันทึกข้อความขออนุมัติเบิกจ่ายเงิน (ใช้เลขชุด 'memo' ร่วมทั้งโรงเรียน)
    เชื่อมกับเรื่องจัดซื้อ/จัดจ้างได้ (procurement_id)"""
    __tablename__ = "disburse_memo"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    memo_no = Column(String, default="")             # เลขที่บันทึก เช่น 70/2569
    seq = Column(Integer, default=0)
    date = Column(DateTime, nullable=True)
    subject = Column(String, default="")             # เรื่อง
    payee = Column(String, default="")               # จ่ายให้ (ผู้ขาย/ผู้รับเงิน)
    amount = Column(Float, default=0.0)              # จำนวนเงินขอเบิก (รวม VAT)
    vat = Column(Float, default=0.0)                 # ภาษีมูลค่าเพิ่ม
    wht = Column(Float, default=0.0)                 # หัก ภาษี ณ ที่จ่าย
    fine = Column(Float, default=0.0)                # ค่าปรับ
    proc_kind = Column(String, default="จัดซื้อ")    # จัดซื้อ/จัดจ้าง (ใช้ในข้อความ)
    budget_source = Column(String, default="")       # แหล่งเงิน/หมวดงบ
    account_id = Column(Integer, ForeignKey("finance_account.id"), nullable=True)
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)
    note = Column(Text, default="")                  # รายละเอียดเพิ่มเติม
    status = Column(String, default="ร่าง")          # ร่าง / อนุมัติ / จ่ายแล้ว
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    account = relationship("FinanceAccount")


class Receipt(Base):
    """ทะเบียนคุมใบเสร็จ/ใบสำคัญรับเงิน-จ่ายเงิน"""
    __tablename__ = "receipt"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    receipt_no = Column(String, default="")          # เลขที่ใบเสร็จ/ใบสำคัญ
    date = Column(DateTime, nullable=True)
    kind = Column(String, default="รับ")             # รับ / จ่าย
    party = Column(String, default="")               # ผู้รับ/ผู้จ่ายเงิน
    amount = Column(Float, default=0.0)
    account_id = Column(Integer, ForeignKey("finance_account.id"), nullable=True)
    txn_id = Column(Integer, ForeignKey("finance_txn.id"), nullable=True)  # ผูกกับรายการรับ-จ่าย (ถ้าออกพร้อมกัน)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    account = relationship("FinanceAccount")
    txn = relationship("FinanceTxn")


class Asset(Base):
    """ครุภัณฑ์ 1 รายการ ในทะเบียนคุมทรัพย์สิน (คำนวณค่าเสื่อมแบบเส้นตรง)"""
    __tablename__ = "asset"

    id = Column(Integer, primary_key=True)
    asset_code = Column(String, default="")        # เลขครุภัณฑ์ เช่น 7440-001-0001/2569
    name = Column(String, nullable=False)          # ชื่อครุภัณฑ์
    category = Column(String, default="ครุภัณฑ์สำนักงาน")  # ประเภท (กำหนดอายุใช้งานมาตรฐาน)

    acquired_date = Column(DateTime, nullable=True)  # วันที่ได้มา (เริ่มคิดค่าเสื่อม)
    cost = Column(Float, default=0.0)              # ราคาทุน (บาท)
    useful_life = Column(Integer, default=12)      # อายุการใช้งาน (ปี)
    salvage_value = Column(Float, default=1.0)     # มูลค่าซาก (ปกติ 1 บาท)

    location = Column(String, default="")          # สถานที่ตั้ง/ผู้รับผิดชอบ
    funding_source = Column(String, default="")    # แหล่งเงิน
    vendor_name = Column(String, default="")       # ผู้ขาย/ผู้รับจ้าง
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)  # มาจากเรื่องไหน
    note = Column(String, default="")
    status = Column(String, default="ใช้งาน")      # ใช้งาน / จำหน่ายแล้ว
    created_at = Column(DateTime, default=datetime.now)


class MaterialItem(Base):
    """รายการวัสดุในบัญชีวัสดุ (ยอดคงเหลือคำนวณจากการเคลื่อนไหว)"""
    __tablename__ = "material_item"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # ชื่อวัสดุ
    unit = Column(String, default="หน่วย")         # หน่วยนับ
    min_stock = Column(Float, default=0.0)         # จุดเตือนสั่งซื้อ (0 = ไม่เตือน)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    txns = relationship("MaterialTxn", back_populates="material",
                        cascade="all, delete-orphan", order_by="MaterialTxn.id")


class MaterialTxn(Base):
    """การเคลื่อนไหววัสดุ: รับเข้า (in) / จ่ายออก (out)"""
    __tablename__ = "material_txn"

    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("material_item.id"), nullable=False)
    date = Column(DateTime, default=datetime.now)
    kind = Column(String, default="in")            # in = รับเข้า, out = จ่ายออก
    qty = Column(Float, default=0.0)
    unit_price = Column(Float, default=0.0)        # ใช้กับรับเข้า
    ref = Column(String, default="")               # อ้างอิงเอกสาร/เรื่องจัดซื้อ
    note = Column(String, default="")
    requisition_id = Column(Integer, ForeignKey("requisition.id"), nullable=True)

    material = relationship("MaterialItem", back_populates="txns")


class Requisition(Base):
    """ใบเบิกวัสดุ 1 ใบ (เบิกหลายรายการ)"""
    __tablename__ = "requisition"

    id = Column(Integer, primary_key=True)
    req_no = Column(String, default="")            # เลขที่ใบเบิก
    date = Column(DateTime, default=datetime.now)
    requester = Column(String, default="")         # ผู้ขอเบิก
    department = Column(String, default="")         # ฝ่าย/งาน
    purpose = Column(String, default="")           # เพื่อใช้ในงาน
    status = Column(String, default="ร่าง")        # ร่าง / จ่ายแล้ว
    created_at = Column(DateTime, default=datetime.now)

    items = relationship("RequisitionItem", back_populates="requisition",
                        cascade="all, delete-orphan")


class RequisitionItem(Base):
    """รายการวัสดุที่ขอเบิกในใบเบิก"""
    __tablename__ = "requisition_item"

    id = Column(Integer, primary_key=True)
    requisition_id = Column(Integer, ForeignKey("requisition.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("material_item.id"), nullable=True)
    name = Column(String, default="")              # ชื่อวัสดุ (เก็บไว้เผื่ออ้างอิง)
    unit = Column(String, default="หน่วย")
    qty = Column(Float, default=0.0)

    requisition = relationship("Requisition", back_populates="items")
    material = relationship("MaterialItem")
