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

    # ปีของโครงการ/แผน: "budget" = ปีงบประมาณ (ต.ค.) / "academic" = ปีการศึกษา (พ.ค.)
    project_year_mode = Column(String, default="budget")

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
    """โครงการในแผนปฏิบัติการ (รายปี) — งบที่ตั้ง + ติดตามใช้จริง + ประวัติการปรับงบ"""
    __tablename__ = "project"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    budget = Column(Float, default=0.0)            # วงเงินงบประมาณตั้งต้น (ครั้งที่ 1)
    budget_note = Column(String, default="")       # รายละเอียด/แหล่งงบเพิ่มเติม
    plan_year = Column(Integer, nullable=True)     # ปีของแผน (พ.ศ.) — ปีงบ หรือ ปีการศึกษา ตามตั้งค่าโรงเรียน
    responsible = Column(String, default="")       # ฝ่าย/ผู้รับผิดชอบโครงการ
    active = Column(Boolean, default=True)

    revisions = relationship("ProjectBudgetRevision", back_populates="project",
                             cascade="all, delete-orphan", order_by="ProjectBudgetRevision.seq")


class ProjectBudgetRevision(Base):
    """ประวัติการปรับงบของโครงการ (ครั้งที่ 1 แผนต้นปี, ครั้งที่ 2 ปรับกลางปี ...)
    งบปัจจุบัน = amount ของ revision ล่าสุด (ถ้าไม่มี = Project.budget)"""
    __tablename__ = "project_budget_revision"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=False)
    seq = Column(Integer, default=1)               # ครั้งที่
    date = Column(DateTime, default=datetime.now)
    amount = Column(Float, default=0.0)            # วงเงินรวมหลังปรับครั้งนี้
    reason = Column(String, default="")            # เหตุผล/หมายเหตุการปรับ

    project = relationship("Project", back_populates="revisions")


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
    project_name = Column(String, default="")      # ชื่อโครงการ (ข้อความ — คงไว้เพื่อความเข้ากันได้)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=True)  # ผูกกับโครงการในแผน
    department = Column(String, default="")        # ฝ่าย/งานที่ขอ
    purpose = Column(Text, default="")             # เหตุผลความจำเป็น

    proc_type = Column(String, default="ซื้อ")     # ซื้อ / จ้าง
    method = Column(String, default="เฉพาะเจาะจง") # วิธีจัดซื้อจัดจ้าง
    proc_case = Column(String, default="normal")   # รูปแบบ/ชุดเอกสาร: normal/w804/w119t1/w119t2
    case_extra = Column(Text, default="")          # ฟิลด์เสริมเฉพาะรูปแบบ (เก็บเป็น JSON)

    budget_source = Column(String, default="เงินอุดหนุน")  # แหล่งงบประมาณ
    total_amount = Column(Float, default=0.0)      # วงเงินรวม (บาท)
    price_ref_source = Column(String, default="การสืบราคาจากท้องตลาด")  # ที่มาราคากลาง

    delivery_days = Column(Integer, default=7)     # กำหนดส่งมอบภายใน (วัน)
    penalty_rate = Column(Float, default=0.10)     # อัตราค่าปรับ ร้อยละต่อวัน
    overdue_days = Column(Integer, default=0)      # ส่งมอบเกินกำหนด (วัน) -> คำนวณค่าปรับ

    vat_mode = Column(String, default="none")      # none = ไม่คิด VAT, include = ราคารวม VAT 7%
    wht_rate = Column(Float, default=0.0)          # อัตราภาษีหัก ณ ที่จ่าย (% ของมูลค่าก่อน VAT)
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


class OfficialLetter(Base):
    """หนังสือราชการภายนอก (เลขที่ใช้ชุด 'outgoing' ร่วมกับทะเบียนหนังสือส่ง)"""
    __tablename__ = "official_letter"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    doc_no = Column(String, default="")             # เลขที่หนังสือ เช่น ศธ 04123/45
    seq = Column(Integer, default=0)
    date = Column(DateTime, nullable=True)          # ลงวันที่
    subject = Column(String, default="")            # เรื่อง
    to = Column(String, default="")                 # เรียน (ผู้รับ)
    ref = Column(String, default="")                # อ้างถึง
    enclosure = Column(String, default="")          # สิ่งที่ส่งมาด้วย
    body = Column(Text, default="")                 # เนื้อความ (หลายย่อหน้า)
    closing = Column(String, default="ขอแสดงความนับถือ")  # คำลงท้าย
    signer_name = Column(String, default="")        # ผู้ลงนาม
    signer_position = Column(String, default="")    # ตำแหน่งผู้ลงนาม
    preset = Column(String, default="")             # แม่แบบที่ใช้ (อ้างอิง)
    file_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class CertificateBatch(Base):
    """ชุดเกียรติบัตร (อัปโหลดพื้นหลัง + พิมพ์ชื่อทับ ออกหลายใบจากรายชื่อ)"""
    __tablename__ = "certificate_batch"

    id = Column(Integer, primary_key=True)
    title = Column(String, default="")              # ชื่อชุด/หัวเรื่อง (อ้างอิง)
    sub_text = Column(Text, default="")             # ข้อความเสริมใต้ชื่อ (ไม่บังคับ)
    date = Column(DateTime, nullable=True)
    bg_image = Column(String, default="")           # ไฟล์รูปพื้นหลังใน uploads
    name_x = Column(Float, default=50.0)            # ตำแหน่งชื่อ (% ของความกว้าง)
    name_y = Column(Float, default=45.0)            # ตำแหน่งชื่อ (% ของความสูง)
    name_size = Column(Integer, default=48)         # ขนาดฟอนต์ชื่อ (px เทียบความกว้างรูป)
    name_color = Column(String, default="#1a1a1a")
    names = Column(Text, default="")                # รายชื่อ (1 ชื่อ/บรรทัด)
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
    item_id = Column(Integer, ForeignKey("account_item.id"), nullable=True)  # หมวด/รายการย่อยที่หักงบ
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=True)  # ผูกกับโครงการในแผน
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

    location = Column(String, default="")          # สถานที่ใช้งาน/หน่วยงานรับผิดชอบ
    funding_source = Column(String, default="")    # แหล่งเงิน (ข้อความอิสระ เดิม)
    vendor_name = Column(String, default="")       # ชื่อผู้ขาย/ผู้รับจ้าง/ผู้บริจาค
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)  # มาจากเรื่องไหน
    note = Column(String, default="")
    status = Column(String, default="ใช้งาน")      # ใช้งาน / จำหน่ายแล้ว

    # การจำหน่ายพัสดุ (เมื่อชำรุด/เสื่อมสภาพ/หมดความจำเป็น)
    disposed_date = Column(DateTime, nullable=True)   # วันที่จำหน่าย/อนุมัติจำหน่าย
    dispose_method = Column(String, default="")       # ขาย/บริจาค/แลกเปลี่ยน/โอน/ทำลาย/ตัดจำหน่าย
    dispose_reason = Column(String, default="")       # ชำรุด/เสื่อมสภาพ/หมดความจำเป็น/สูญหาย
    dispose_value = Column(Float, default=0.0)        # มูลค่าที่ได้จากการจำหน่าย (กรณีขาย)
    dispose_doc_ref = Column(String, default="")      # เลขที่หนังสือ/คำสั่งอนุมัติจำหน่าย

    # ฟิลด์ตามแบบฟอร์มทะเบียนคุมทรัพย์สิน (แบบ 2)
    brand_model = Column(String, default="")       # ยี่ห้อ/รุ่น/ลักษณะเฉพาะ
    vendor_address = Column(String, default="")    # ที่อยู่ผู้ขาย/ผู้บริจาค
    fund_type = Column(String, default="เงินงบประมาณ")  # ประเภทเงิน
    acquire_method = Column(String, default="วิธีเฉพาะเจาะจง")  # วิธีการได้มา
    doc_ref = Column(String, default="")           # ที่เอกสาร (หลักฐานการได้มา)
    quantity = Column(Float, default=1)            # จำนวน
    unit = Column(String, default="หน่วย")         # หน่วย
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


# ==================== โครงการอาหารกลางวัน ====================
class LunchProgram(Base):
    """โครงการอาหารกลางวันต่อปีการศึกษา (คำนวณงบ + บัญชีรับ-จ่าย)
    งบ = จำนวนนักเรียนรวม x อัตราต่อหัวต่อวัน x จำนวนวัน"""
    __tablename__ = "lunch_program"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปีการศึกษา พ.ศ. เช่น 2568
    days = Column(Integer, default=200)             # จำนวนวันทำการ
    rate_per_head = Column(Float, default=0.0)      # อัตราต่อหัว/วัน (เลือกอัตโนมัติตามขนาด แก้ได้)
    operate_mode = Column(String, default="hire")   # hire=จ้างเหมาปรุงสำเร็จ / ingredient=ซื้อวัตถุดิบ+แม่ครัว / self=ทำเอง
    funding_org = Column(String, default="")        # อปท.ผู้จัดสรร (เทศบาล/อบต.)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)

    classes = relationship("LunchClass", back_populates="program",
                           cascade="all, delete-orphan", order_by="LunchClass.seq")
    ledger = relationship("LunchLedger", back_populates="program",
                          cascade="all, delete-orphan")
    rounds = relationship("LunchHireRound", back_populates="program",
                          cascade="all, delete-orphan", order_by="LunchHireRound.seq")
    menus = relationship("LunchMenu", back_populates="program",
                         cascade="all, delete-orphan", order_by="LunchMenu.date")
    students = relationship("LunchStudent", back_populates="program",
                            cascade="all, delete-orphan", order_by="LunchStudent.name")

    @property
    def total_students(self) -> int:
        return sum(c.num_students or 0 for c in self.classes)

    @property
    def budget(self) -> float:
        return (self.total_students) * (self.rate_per_head or 0) * (self.days or 0)


class LunchClass(Base):
    """จำนวนนักเรียนแยกระดับชั้นในโครงการอาหารกลางวัน"""
    __tablename__ = "lunch_class"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    seq = Column(Integer, default=0)                # ลำดับการแสดง
    level = Column(String, default="")              # ระดับชั้น เช่น อ.1 / ป.1 / ม.1
    num_students = Column(Integer, default=0)

    program = relationship("LunchProgram", back_populates="classes")


class LunchLedger(Base):
    """บัญชีรับ-จ่ายเงินอาหารกลางวัน (รับเงินอุดหนุนเป็นงวด / จ่าย)"""
    __tablename__ = "lunch_ledger"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    date = Column(DateTime, nullable=True)
    kind = Column(String, default="in")             # in=รับ / out=จ่าย
    detail = Column(String, default="")             # รายละเอียด
    amount = Column(Float, default=0.0)
    ref = Column(String, default="")                # เลขที่งวด/ใบเสร็จ
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)  # ผูกเรื่องจ้างเหมา (ถ้ามี)
    round_id = Column(Integer, ForeignKey("lunch_hire_round.id"), nullable=True)   # มาจากรอบจ้างเหมา (ถ้าใช่)
    installment_id = Column(Integer, ForeignKey("lunch_installment.id"), nullable=True)  # มาจากงวด (ถ้าใช่)
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="ledger")


class LunchHireRound(Base):
    """รอบการจ้างเหมาประกอบอาหารกลางวัน (รายวัน/สัปดาห์/เดือน)
    แต่ละรอบ = 1 ช่วงเวลา + วงเงิน ผูกเรื่องจัดจ้าง 1 เรื่อง และเมื่อจ่ายแล้วลงบัญชีอัตโนมัติ"""
    __tablename__ = "lunch_hire_round"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    seq = Column(Integer, default=1)                 # รอบที่
    period_type = Column(String, default="month")    # day=รายวัน / week=รายสัปดาห์ / month=รายเดือน
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    days = Column(Integer, default=0)                # จำนวนวันทำการในรอบ (หักวันหยุดแล้ว)
    vendor_id = Column(Integer, ForeignKey("vendor.id"), nullable=True)  # ผู้รับจ้าง
    amount = Column(Float, default=0.0)              # วงเงินรอบนี้
    procurement_id = Column(Integer, ForeignKey("procurement.id"), nullable=True)  # เรื่องจัดจ้างที่ผูก
    status = Column(String, default="ร่าง")          # ร่าง / จ้างแล้ว / จ่ายแล้ว
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="rounds")
    vendor = relationship("Vendor")
    installments = relationship("LunchInstallment", back_populates="round",
                               cascade="all, delete-orphan", order_by="LunchInstallment.seq")


class LunchInstallment(Base):
    """งวดงานย่อยในสัญญาจ้างเหมา 1 รอบ (แต่ละงวด: ส่งมอบ -> ตรวจรับ -> เบิกจ่าย)
    1 สัญญา (LunchHireRound) มักแบ่งเป็นหลายงวด เช่น 5 งวด งวดละ 10 วัน"""
    __tablename__ = "lunch_installment"

    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("lunch_hire_round.id"), nullable=False)
    seq = Column(Integer, default=1)                 # งวดที่
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    days = Column(Integer, default=0)                # จำนวนวันในงวด
    amount = Column(Float, default=0.0)              # เงินงวดนี้
    deliver_date = Column(DateTime, nullable=True)   # วันที่ส่งมอบงาน
    inspect_date = Column(DateTime, nullable=True)   # วันที่ตรวจรับ
    status = Column(String, default="ร่าง")          # ร่าง / ส่งมอบแล้ว / ตรวจรับแล้ว / จ่ายแล้ว
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    round = relationship("LunchHireRound", back_populates="installments")


class LunchMenu(Base):
    """เมนู/สำรับอาหารกลางวันรายวัน (อาหารคาว + ของหวาน/ผลไม้) ใช้พิมพ์ตารางเมนูประจำเดือน"""
    __tablename__ = "lunch_menu"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    date = Column(DateTime, nullable=True)
    main = Column(String, default="")       # อาหารคาว (จานหลัก)
    dessert = Column(String, default="")    # ของหวาน/ผลไม้
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="menus")


class LunchStudent(Base):
    """นักเรียนในโครงการอาหารกลางวัน (สำหรับติดตามภาวะโภชนาการ)"""
    __tablename__ = "lunch_student"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    name = Column(String, nullable=False)           # ชื่อ-นามสกุล
    sex = Column(String, default="")                # M=ชาย / F=หญิง
    birthdate = Column(DateTime, nullable=True)     # วันเกิด (คำนวณอายุตอนชั่ง)
    level = Column(String, default="")              # ระดับชั้น เช่น ป.1
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="students")
    measures = relationship("LunchMeasure", back_populates="student",
                            cascade="all, delete-orphan", order_by="LunchMeasure.term")


class LunchMeasure(Base):
    """การชั่งน้ำหนัก/วัดส่วนสูง 1 ครั้ง (ต่อเทอม) -> ใช้จัดกลุ่มภาวะโภชนาการ"""
    __tablename__ = "lunch_measure"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("lunch_student.id"), nullable=False)
    term = Column(Integer, default=1)               # เทอม 1 / 2
    date = Column(DateTime, nullable=True)          # วันที่ชั่ง
    weight = Column(Float, default=0.0)             # กก.
    height = Column(Float, default=0.0)             # ซม.
    created_at = Column(DateTime, default=datetime.now)

    student = relationship("LunchStudent", back_populates="measures")
