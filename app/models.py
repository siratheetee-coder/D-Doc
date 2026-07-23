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
from sqlalchemy.orm import relationship, backref

from app.database import Base


class School(Base):
    """ข้อมูลโรงเรียน (ตั้งค่าครั้งเดียว ใช้เติมหัวกระดาษเอกสาร)"""
    __tablename__ = "school"

    id = Column(Integer, primary_key=True)
    name = Column(String, default="")              # ชื่อโรงเรียน
    address = Column(Text, default="")             # ที่อยู่ (บรรทัดเดียวสำหรับส่วนราชการ)
    district = Column(String, default="")          # อำเภอ
    province = Column(String, default="")          # จังหวัด
    area_office = Column(String, default="")       # สำนักงานเขตพื้นที่การศึกษาที่สังกัด (ใช้ในหนังสือรับรอง ฯลฯ)

    director_name = Column(String, default="")     # ชื่อผู้อำนวยการ
    director_position = Column(String, default="ผู้อำนวยการโรงเรียน")

    officer_name = Column(String, default="")      # เจ้าหน้าที่ (พัสดุ)
    head_officer_name = Column(String, default="") # หัวหน้าเจ้าหน้าที่ (พัสดุ)

    finance_officer_name = Column(String, default="")  # เจ้าหน้าที่การเงิน
    finance_head_name = Column(String, default="")     # หัวหน้าเจ้าหน้าที่การเงิน
    admin_officer_name = Column(String, default="")    # เจ้าหน้าที่ธุรการ
    academic_head_name = Column(String, default="")    # หัวหน้าฝ่ายวิชาการ (ผู้ลงนามคนที่ 2 บนปก ปพ.5)

    # ปีของโครงการ/แผน: "budget" = ปีงบประมาณ (ต.ค.) / "academic" = ปีการศึกษา (พ.ค.)
    project_year_mode = Column(String, default="budget")

    doc_prefix = Column(String, default="ศธ")      # อักษรนำเลขที่หนังสือ

    # เกณฑ์วงเงิน (บาท) ที่ใช้แบ่ง "ชุดเอกสารแบบย่อ + ผู้ตรวจรับคนเดียว"
    # ออกจาก "ชุดเต็ม + คณะกรรมการตรวจรับ" - ปรับได้ตามแต่ละโรงเรียน
    doc_set_threshold = Column(Float, default=5000.0)

    ai_api_key = Column(String, default="")        # Anthropic API key (สำหรับอ่านไฟล์ด้วย AI ทางเลือก)


class Person(Base):
    """รายชื่อครู/บุคลากร (มาสเตอร์ลิสต์) ใช้เลือกเป็นกรรมการหรือผู้ลงนาม + ข้อมูลงานบุคคล"""
    __tablename__ = "person"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # ชื่อ-นามสกุล (มีคำนำหน้า)
    position = Column(String, default="ครู")       # ตำแหน่ง
    active = Column(Boolean, default=True)
    signature = Column(String, default="")         # ไฟล์ลายเซ็น (PNG โปร่งใส) ใน data/signatures/
    # ---- ข้อมูลงานบุคคล (เพิ่มเติม, ไม่บังคับ) ----
    person_type = Column(String, default="ครู")    # ครู/ผู้บริหาร/ธุรการ/นักการ/อื่นๆ
    rank = Column(String, default="")              # วิทยฐานะ/ระดับ เช่น ครู คศ.1
    id_card = Column(String, default="")           # เลขบัตรประชาชน
    birthdate = Column(DateTime, nullable=True)    # วันเดือนปีเกิด
    start_date = Column(DateTime, nullable=True)   # วันบรรจุ/เริ่มปฏิบัติงาน
    phone = Column(String, default="")
    email = Column(String, default="")
    salary = Column(Float, default=0.0)            # เงินเดือน (สำหรับหนังสือรับรอง)

    leaves = relationship("LeaveRecord", back_populates="person",
                          cascade="all, delete-orphan", order_by="LeaveRecord.start_date")
    travels = relationship("TravelRecord", back_populates="person",
                           cascade="all, delete-orphan", order_by="TravelRecord.start_date")
    decorations = relationship("Decoration", back_populates="person",
                               cascade="all, delete-orphan", order_by="Decoration.year")
    rank_history = relationship("RankHistory", back_populates="person",
                                cascade="all, delete-orphan", order_by="RankHistory.date")


class Department(Base):
    """ฝ่าย/งานที่ขอจัดซื้อ (มาสเตอร์ลิสต์)"""
    __tablename__ = "department"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # เช่น ฝ่ายบริหารงานวิชาการ


class Project(Base):
    """โครงการในแผนปฏิบัติการ (รายปี) - งบที่ตั้ง + ติดตามใช้จริง + ประวัติการปรับงบ"""
    __tablename__ = "project"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    budget = Column(Float, default=0.0)            # วงเงินงบประมาณตั้งต้น (ครั้งที่ 1)
    budget_note = Column(String, default="")       # รายละเอียด/แหล่งงบเพิ่มเติม
    plan_year = Column(Integer, nullable=True)     # ปีของแผน (พ.ศ.) - ปีงบ หรือ ปีการศึกษา ตามตั้งค่าโรงเรียน
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
    project_name = Column(String, default="")      # ชื่อโครงการ (ข้อความ - คงไว้เพื่อความเข้ากันได้)
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

    # เลขเอกสารแต่ละชนิด (เสนออัตโนมัติ แก้เองได้) - เก็บเป็นข้อความ เช่น "68/2569"
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
    quotation_date = Column(DateTime, nullable=True)       # วันที่ใบเสนอราคา
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


class Contract(Base):
    """ทะเบียนคุมสัญญา/ใบสั่งซื้อ-สั่งจ้าง/ข้อตกลง - ติดตามวันครบกำหนดและแจ้งเตือน"""
    __tablename__ = "contract"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)   # ปีงบประมาณ พ.ศ.
    contract_no = Column(String, default="")        # เลขที่สัญญา/ใบสั่ง
    ctype = Column(String, default="ใบสั่งจ้าง")     # สัญญาจ้าง/สัญญาซื้อ/ใบสั่งจ้าง/ใบสั่งซื้อ/ข้อตกลง
    party = Column(String, default="")              # คู่สัญญา (ผู้ขาย/ผู้รับจ้าง)
    subject = Column(String, default="")            # เรื่อง/งาน
    amount = Column(Float, default=0.0)             # วงเงิน
    sign_date = Column(DateTime, nullable=True)     # วันที่ทำสัญญา/ใบสั่ง
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)      # วันสิ้นสุด/ครบกำหนดส่งมอบ (ใช้แจ้งเตือน)
    warranty_end = Column(DateTime, nullable=True)  # สิ้นสุดประกัน (ถ้ามี)
    status = Column(String, default="ระหว่างดำเนินการ")  # ระหว่างดำเนินการ/ส่งมอบแล้ว/ตรวจรับแล้ว/สิ้นสุด
    source = Column(String, default="manual")       # manual / procurement / lunch
    ref_id = Column(Integer, nullable=True)         # id ต้นทาง (procurement/lunch round)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class ProcurementPlan(Base):
    """แผนการจัดซื้อจัดจ้างประจำปีงบประมาณ (ต้องประกาศเผยแพร่ต้นปีงบตามระเบียบ ม.11)"""
    __tablename__ = "procurement_plan"

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)   # ปีงบประมาณ พ.ศ.
    seq = Column(Integer, default=0)                # ลำดับ
    name = Column(String, nullable=False)           # รายการ/โครงการที่จะจัดซื้อจัดจ้าง
    budget = Column(Float, default=0.0)             # งบประมาณโดยประมาณ (บาท)
    method = Column(String, default="เฉพาะเจาะจง")  # วิธีที่คาดว่าจะใช้
    expected_period = Column(String, default="")    # เดือน/ปีที่คาดว่าจะประกาศจัดซื้อ เช่น "ตุลาคม 2568"
    source = Column(String, default="เงินอุดหนุน")  # แหล่งเงิน
    project_id = Column(Integer, ForeignKey("project.id"), nullable=True)  # ผูกโครงการในแผน (ถ้าดึงมา)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class Student(Base):
    """ทะเบียนนักเรียนกลางของโรงเรียน (ใช้ซ้ำทุกปี) - ข้อมูลหลักเหมือนบุคลากร/ผู้ขาย
    งานภาวะโภชนาการดึงรายชื่อจากที่นี่เข้าโครงการรายปีเพื่อบันทึกน้ำหนัก/ส่วนสูง"""
    __tablename__ = "student"

    id = Column(Integer, primary_key=True)
    student_no = Column(String, default="")         # เลขประจำตัวนักเรียน (ไม่บังคับ)
    name = Column(String, nullable=False)           # ชื่อ-นามสกุล
    sex = Column(String, default="")                # M/F
    birthdate = Column(DateTime, nullable=True)     # วันเกิด
    level = Column(String, default="")              # ระดับชั้น เช่น ป.1
    room = Column(String, default="")               # ห้อง เช่น 1 (คู่กับ level -> "ป.1/1") ว่างได้ถ้าชั้นละห้อง
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class ItemCatalog(Base):
    """คลังรายการพัสดุมาตรฐาน (ใช้ซ้ำ) - พิมพ์ชื่อครั้งเดียว เลือกใช้ในเรื่องจัดซื้อทุกครั้ง
    ระบบเติมให้อัตโนมัติจากรายการที่เคยกรอก (dedupe ตามชื่อ)"""
    __tablename__ = "item_catalog"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)              # ชื่อพัสดุ
    unit = Column(String, default="ชิ้น")             # หน่วยนับ
    unit_price = Column(Float, default=0.0)            # ราคาต่อหน่วยล่าสุด
    category = Column(String, default="")             # กลุ่ม/ประเภท (ไม่บังคับ)
    created_at = Column(DateTime, default=datetime.now)


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
    ตัวรันเลขทะเบียน - แยกตาม (ชนิดเอกสาร + ปีงบประมาณ)
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
    """ทะเบียนเลขหนังสือกลาง - บันทึกทุกเลขที่ถูกใช้จริง (ทุกงาน) ต่อชนิด/ปีงบ
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
    fund_type = Column(String, default="เงินนอกงบประมาณ")  # ประเภทเงินตามงบ (สมุดเงินสด): เงินงบประมาณ/เงินรายได้แผ่นดิน/เงินนอกงบประมาณ
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
    parent_id = Column(Integer, ForeignKey("account_item.id"), nullable=True)  # หมวดแม่ (ซ้อนได้ 2 ชั้น) None=หมวดหลัก
    fiscal_year = Column(Integer, nullable=False)
    name = Column(String, nullable=False)            # ชื่อหมวด/รายการ
    budget = Column(Float, default=0.0)              # งบที่ตั้งไว้/ได้รับจัดสรร
    deposit_type = Column(String, default="bank")    # เก็บเงินไว้ที่: cash/bank/agency
    note = Column(String, default="")

    account = relationship("FinanceAccount", back_populates="items")
    children = relationship("AccountItem", cascade="all, delete-orphan",
                            backref=backref("parent", remote_side=[id]))


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
    pool = Column(Integer, default=0)               # 1 = โปรแกรมพิเศษเก็บทะเบียนภาวะโภชนาการรวมของโรงเรียน (ซ่อนจากรายการโครงการ)
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
    finance_txn_id = Column(Integer, ForeignKey("finance_txn.id"), nullable=True)  # รายการคู่ในบัญชีการเงินหลัก
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
    order_no = Column(String, default="")            # เลขที่ใบสั่งจ้าง เช่น 27/2568
    order_date = Column(DateTime, nullable=True)     # วันที่ใบสั่งจ้าง
    status = Column(String, default="ร่าง")          # ร่าง / จ้างแล้ว / จ่ายแล้ว
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="rounds")
    vendor = relationship("Vendor")
    installments = relationship("LunchInstallment", back_populates="round",
                               cascade="all, delete-orphan", order_by="LunchInstallment.seq")
    committees = relationship("LunchCommittee", back_populates="round",
                             cascade="all, delete-orphan",
                             order_by="LunchCommittee.kind, LunchCommittee.seq")


class LunchCommittee(Base):
    """กรรมการในสัญญาจ้างเหมาอาหารกลางวัน 3 ชุด: จัดทำ TOR / ควบคุมงาน / ตรวจรับ"""
    __tablename__ = "lunch_committee"

    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("lunch_hire_round.id"), nullable=False)
    kind = Column(String, default="inspect")        # tor / control / inspect
    seq = Column(Integer, default=1)
    name = Column(String, default="")
    position = Column(String, default="ครู")        # ตำแหน่ง
    role = Column(String, default="กรรมการ")        # ประธานกรรมการ / กรรมการ / กรรมการและเลขานุการ

    round = relationship("LunchHireRound", back_populates="committees")


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
    groups = Column(String, default="")     # หมู่อาหารที่ครบ (1-5 คั่นจุลภาค) ตามหลักโภชนาการ 5 หมู่
    created_at = Column(DateTime, default=datetime.now)

    program = relationship("LunchProgram", back_populates="menus")


class LunchStudent(Base):
    """นักเรียนในโครงการอาหารกลางวัน (สำหรับติดตามภาวะโภชนาการ)"""
    __tablename__ = "lunch_student"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("lunch_program.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=True)  # มาจากทะเบียนกลาง (ถ้าดึงเข้ามา)
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


# ============================================================
# บัญชีหนังสือเรียน / แบบฝึกหัด (เงินอุดหนุนค่าหนังสือเรียน)
# ============================================================
class TextBook(Base):
    """ทะเบียนหนังสือเรียน/แบบฝึกหัด 1 รายการ (ต่อปีการศึกษา)
    คงเหลือ = รับเข้า - เบิกออก (คำนวณจากใบเบิก)"""
    __tablename__ = "textbook"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปีการศึกษา พ.ศ.
    level = Column(String, default="")              # ระดับชั้น เช่น ป.1
    subject = Column(String, default="")            # กลุ่มสาระ/วิชา
    title = Column(String, nullable=False)          # ชื่อหนังสือ
    publisher = Column(String, default="")          # สำนักพิมพ์
    unit_price = Column(Float, default=0.0)         # ราคาต่อเล่ม
    qty_received = Column(Integer, default=0)       # จำนวนรับเข้า (เล่ม)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    @property
    def amount(self) -> float:
        return (self.qty_received or 0) * (self.unit_price or 0)


class TextbookBerk(Base):
    """ใบเบิกหนังสือเรียน/แบบฝึกหัด (จ่ายหนังสือให้ชั้นเรียน/ครูผู้รับ)"""
    __tablename__ = "textbook_berk"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปีการศึกษา พ.ศ.
    berk_no = Column(String, default="")            # เลขที่ใบเบิก
    date = Column(DateTime, nullable=True)
    recipient = Column(String, default="")          # ผู้รับ/ชั้นเรียน
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    items = relationship("TextbookBerkItem", back_populates="berk",
                         cascade="all, delete-orphan")


class TextbookBerkItem(Base):
    """รายการหนังสือในใบเบิก 1 ใบ"""
    __tablename__ = "textbook_berk_item"

    id = Column(Integer, primary_key=True)
    berk_id = Column(Integer, ForeignKey("textbook_berk.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("textbook.id"), nullable=True)
    qty = Column(Integer, default=0)

    berk = relationship("TextbookBerk", back_populates="items")
    book = relationship("TextBook")


class LeaveEntitlement(Base):
    """สิทธิ์วันลาต่อปี (ตั้งเองหรือกดตามระเบียบราชการ) ระดับโรงเรียน แยกตามปี+ประเภทลา"""
    __tablename__ = "leave_entitlement"
    __table_args__ = (UniqueConstraint("year", "leave_type", name="uq_leave_ent_year_type"),)

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปี พ.ศ.
    leave_type = Column(String, nullable=False)     # sick/personal/vacation/maternity/ordain
    days = Column(Float, default=0.0)               # สิทธิ์ (วันทำการ) ต่อปี


class LeaveRecord(Base):
    """รายการลาของบุคลากร (คำนวณวันลาคงเหลือ + ออกใบลา)"""
    __tablename__ = "leave_record"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.id"), nullable=False)
    year = Column(Integer, nullable=False)          # ปี พ.ศ. ที่นับสิทธิ์
    leave_type = Column(String, default="sick")     # sick/personal/vacation/maternity/ordain
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    days = Column(Float, default=0.0)               # จำนวนวันลา (วันทำการ)
    reason = Column(String, default="")             # เหตุผล/รายละเอียด
    contact = Column(String, default="")            # ที่อยู่/เบอร์ติดต่อระหว่างลา
    doc_no = Column(String, default="")             # เลขที่ใบลา (ถ้ามี)
    created_at = Column(DateTime, default=datetime.now)

    person = relationship("Person", back_populates="leaves")


class TravelRecord(Base):
    """ทะเบียนไปราชการของบุคลากร + ออกคำสั่งไปราชการ"""
    __tablename__ = "travel_record"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.id"), nullable=False)
    year = Column(Integer, nullable=False)          # ปี พ.ศ.
    subject = Column(String, default="")            # เรื่อง/ภารกิจ (เช่น อบรมหลักสูตร...)
    place = Column(String, default="")              # สถานที่/จังหวัด
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    days = Column(Float, default=0.0)
    budget = Column(Float, default=0.0)             # ค่าใช้จ่าย/งบประมาณ
    doc_no = Column(String, default="")             # เลขที่คำสั่ง
    doc_date = Column(DateTime, nullable=True)      # วันที่คำสั่ง
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    person = relationship("Person", back_populates="travels")


class Decoration(Base):
    """เครื่องราชอิสริยาภรณ์ที่บุคลากรได้รับ (สำหรับ ก.พ.7)"""
    __tablename__ = "decoration"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.id"), nullable=False)
    name = Column(String, default="")       # ชั้นตรา เช่น เบญจมดิเรกคุณาภรณ์ (บ.ภ.)
    year = Column(Integer, nullable=True)   # ปี พ.ศ. ที่ได้รับ
    ref = Column(String, default="")        # เลขที่ประกาศ/ราชกิจจานุเบกษา
    person = relationship("Person", back_populates="decorations")


class RankHistory(Base):
    """ประวัติการดำรงตำแหน่ง/เลื่อนวิทยฐานะ (สำหรับ ก.พ.7)"""
    __tablename__ = "rank_history"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.id"), nullable=False)
    date = Column(DateTime, nullable=True)  # วันที่มีผล
    position = Column(String, default="")   # ตำแหน่ง
    rank = Column(String, default="")       # วิทยฐานะ/ระดับ
    doc_no = Column(String, default="")     # เลขที่คำสั่ง
    note = Column(String, default="")
    person = relationship("Person", back_populates="rank_history")


# ===================== งานวิชาการ (ผลการเรียน · ปพ.5 / ปพ.6) =====================
# หลักคิด: ทะเบียนนักเรียนกลาง (Student) คือมาสเตอร์ที่ "ใช้ซ้ำทุกปี" และเลื่อนชั้นได้
# งานวิชาการจึง "คัดลอกตอนดึง" เข้ามาเก็บเป็นสำเนารายปี (AcadStudent) เหมือนที่งาน
# ภาวะโภชนาการทำ - เพื่อให้ผลการเรียนปี 2567 ไม่ขยับตามเมื่อเด็กเลื่อนชั้นไป ป.2

class AcadClass(Base):
    """ห้องเรียนของปีการศึกษาหนึ่ง (ปี × ชั้น × ห้อง)"""
    __tablename__ = "acad_class"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปีการศึกษา (พ.ศ.)
    level = Column(String, default="")              # ระดับชั้น เช่น ป.1
    room = Column(String, default="")               # ห้อง เช่น 1
    # ครูประจำชั้นเป็นความสัมพันธ์ "ปี×ชั้น×ห้อง -> ครู" ไม่ใช่คุณสมบัติของครู
    # (ถ้าเก็บไว้ที่ Person ปีหน้าครูย้ายห้อง ปพ.6 ของปีเก่าจะเปลี่ยนชื่อตามไปด้วย)
    homeroom_id = Column(Integer, ForeignKey("person.id"), nullable=True)     # ครูประจำชั้น
    co_homeroom_id = Column(Integer, ForeignKey("person.id"), nullable=True)  # ครูคู่ชั้น (ไม่บังคับ)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)

    homeroom = relationship("Person", foreign_keys=[homeroom_id])
    co_homeroom = relationship("Person", foreign_keys=[co_homeroom_id])
    students = relationship("AcadStudent", back_populates="klass",
                            cascade="all, delete-orphan")
    teachings = relationship("AcadTeaching", back_populates="klass",
                             cascade="all, delete-orphan")


class AcadStudent(Base):
    """สำเนานักเรียนในห้องนั้นของปีนั้น (ดึงจากทะเบียนกลาง แล้วเก็บสำเนาไว้)"""
    __tablename__ = "acad_student"

    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, ForeignKey("acad_class.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=True)  # ย้อนไปทะเบียนกลาง (ถ้าดึงมา)
    seq = Column(Integer, default=0)                # เลขที่ในห้อง
    student_no = Column(String, default="")         # เลขประจำตัวนักเรียน (สำเนา)
    name = Column(String, nullable=False)
    sex = Column(String, default="")                # M/F

    klass = relationship("AcadClass", back_populates="students")
    scores = relationship("AcadScore", back_populates="student",
                          cascade="all, delete-orphan")
    eval = relationship("AcadEval", back_populates="student", uselist=False,
                        cascade="all, delete-orphan")


class AcadSubject(Base):
    """รายวิชาของระดับชั้นในปีนั้น (ไม่ผูกห้อง - ครูผู้สอนอยู่ที่ AcadTeaching)"""
    __tablename__ = "acad_subject"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)          # ปีการศึกษา (พ.ศ.)
    level = Column(String, default="")              # ระดับชั้น เช่น ป.1
    code = Column(String, default="")               # รหัสวิชา เช่น ท11101
    name = Column(String, nullable=False)           # ชื่อรายวิชา
    learn_group = Column(String, default="")        # กลุ่มสาระการเรียนรู้
    kind = Column(String, default="พื้นฐาน")        # พื้นฐาน / เพิ่มเติม
    hours = Column(Integer, default=0)              # เวลาเรียน (ชม./ปี หรือ ชม./ภาค)
    credit = Column(Float, default=0.0)             # หน่วยกิต (มัธยม)
    mid_max = Column(Integer, default=70)           # คะแนนเก็บเต็ม (สัดส่วนต่างกันได้รายวิชา)
    final_max = Column(Integer, default=30)         # คะแนนปลายภาคเต็ม
    term = Column(Integer, default=0)               # 0 = ทั้งปี (ประถม) · 1/2 = ภาคเรียน (มัธยม)
    seq = Column(Integer, default=0)                # ลำดับแสดงผล
    created_at = Column(DateTime, default=datetime.now)

    teachings = relationship("AcadTeaching", back_populates="subject",
                             cascade="all, delete-orphan")
    scores = relationship("AcadScore", back_populates="subject",
                          cascade="all, delete-orphan")


class AcadTeaching(Base):
    """ครูผู้สอน = รายวิชา × ห้อง (วิชาเดียวกันคนละห้อง คนละครูได้)"""
    __tablename__ = "acad_teaching"

    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, ForeignKey("acad_class.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("acad_subject.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("person.id"), nullable=True)

    klass = relationship("AcadClass", back_populates="teachings")
    subject = relationship("AcadSubject", back_populates="teachings")
    teacher = relationship("Person")


class AcadScore(Base):
    """ผลการเรียนรายวิชาของนักเรียน 1 คน"""
    __tablename__ = "acad_score"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("acad_subject.id"), nullable=False)
    term = Column(Integer, default=0)               # 0 = ทั้งปี · 1/2 = ภาคเรียน
    score_mid = Column(Float, nullable=True)        # คะแนนเก็บ/ระหว่างภาค
    score_final = Column(Float, nullable=True)      # คะแนนปลายภาค
    score = Column(Float, nullable=True)            # คะแนนรวม (0-100)
    grade = Column(String, default="")              # 4/3.5/.../0 หรือ ร/มส (แก้มือทับได้)

    student = relationship("AcadStudent", back_populates="scores")
    subject = relationship("AcadSubject", back_populates="scores")


class AcadEval(Base):
    """ผลการประเมินรายคน/ปี ที่ ปพ.6 (สมุดพก) ต้องใช้"""
    __tablename__ = "acad_eval"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    read_think = Column(String, default="")         # อ่าน คิดวิเคราะห์ และเขียน
    desired_char = Column(String, default="")       # คุณลักษณะอันพึงประสงค์
    # DEPRECATED: กิจกรรมพัฒนาผู้เรียนย้ายไป AcadActivity/AcadActivityResult (ตั้งค่าเองได้)
    # เก็บคอลัมน์ไว้เฉย ๆ ไม่ลบ (ลบใน SQLite ยุ่งยากและไม่ได้อะไรกลับมา) แต่เลิกใช้แล้ว
    act_guidance = Column(String, default="")       # (เลิกใช้)
    act_scout = Column(String, default="")          # (เลิกใช้)
    act_club = Column(String, default="")           # (เลิกใช้)
    act_social = Column(String, default="")         # (เลิกใช้)
    days_open = Column(Integer, nullable=True)      # จำนวนวันเปิดเรียน
    days_present = Column(Integer, nullable=True)   # จำนวนวันมาเรียน
    days_sick = Column(Integer, nullable=True)      # ป่วย (วัน) - สรุปเวลาเรียนใน ปพ.5
    days_leave = Column(Integer, nullable=True)     # ลา (วัน)
    days_absent = Column(Integer, nullable=True)    # ขาด (วัน)
    weight = Column(Float, nullable=True)           # น้ำหนัก (กก.)
    height = Column(Float, nullable=True)           # ส่วนสูง (ซม.)
    comment = Column(Text, default="")              # ความเห็นครูประจำชั้น

    student = relationship("AcadStudent", back_populates="eval")


class AcadCharEval(Base):
    """คุณลักษณะอันพึงประสงค์ 8 ข้อ รายวิชา (แถวละ นักเรียน x วิชา · คะแนน 0-3 ต่อข้อ)
    เฉลี่ย -> ผล (ดีเยี่ยม/ดี/ผ่าน/ไม่ผ่าน) คำนวณตอนใช้ ไม่เก็บซ้ำ"""
    __tablename__ = "acad_char_eval"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("acad_subject.id"), nullable=False)
    c1 = Column(Integer, nullable=True)
    c2 = Column(Integer, nullable=True)
    c3 = Column(Integer, nullable=True)
    c4 = Column(Integer, nullable=True)
    c5 = Column(Integer, nullable=True)
    c6 = Column(Integer, nullable=True)
    c7 = Column(Integer, nullable=True)
    c8 = Column(Integer, nullable=True)


class AcadReadEval(Base):
    """อ่าน คิดวิเคราะห์ เขียนสื่อความ รายวิชา (0-3 ต่อด้าน)"""
    __tablename__ = "acad_read_eval"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("acad_subject.id"), nullable=False)
    r_read = Column(Integer, nullable=True)     # การอ่าน
    r_think = Column(Integer, nullable=True)    # การคิดวิเคราะห์
    r_write = Column(Integer, nullable=True)    # การเขียนสื่อความ


class AcadAttendance(Base):
    """วันมาเรียนรายเดือน รายคน (เดือน 1-12 ปฏิทิน · ปีการศึกษาไทย พ.ค.->มี.ค.)"""
    __tablename__ = "acad_attendance"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    month = Column(Integer, nullable=False)     # 5..12, 1..3
    present = Column(Integer, nullable=True)    # วันมาเรียนของเดือนนั้น (= จำนวน "/" ใน marks)
    # ผลเช็กชื่อรายวัน: สตริง 31 ตัว ตำแหน่ง = วันที่-1
    # "." ไม่ใช่วันเรียน/ยังไม่กรอก · "/" มา · "ป" ป่วย · "ล" ลา · "ข" ขาด
    marks = Column(String, default="")


class AcadCalendar(Base):
    """ปฏิทินการศึกษาของโรงเรียน - เดือนไหนเปิดเรียนวันไหนบ้าง (ระดับโรงเรียน ไม่แยกห้อง)
    ใช้เป็นทั้งตัวหารร้อยละเวลาเรียน และคอลัมน์ของตารางเช็กชื่อรายวัน"""
    __tablename__ = "acad_calendar"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)      # ปีการศึกษา พ.ศ.
    month = Column(Integer, nullable=False)     # 5..12, 1..3
    days_csv = Column(String, default="")       # "3,4,5,6,7,10,11" = วันที่เปิดเรียน


class AcadHoliday(Base):
    """วันหยุดของปีการศึกษานั้น - แก้/ลบได้ทุกแถว
    kind: fixed = วันหยุดราชการที่วันที่ตายตัว (ระบบใส่ให้ได้)
          lunar = วันพระ เลื่อนทุกปีตามจันทรคติ (โรงเรียนกรอกเอง ระบบไม่เดา)
          other = วันหยุดชดเชย/วันหยุดพิเศษตามประกาศ"""
    __tablename__ = "acad_holiday"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)      # ปีการศึกษา พ.ศ.
    month = Column(Integer, nullable=True)      # เว้นว่างได้ = ยังไม่กรอกวันที่
    day = Column(Integer, nullable=True)
    name = Column(String, default="")
    kind = Column(String, default="other")


class AcadYearSetting(Base):
    """วันเปิด-ปิดภาคเรียนของปีการศึกษา (ใช้ตัดวันนอกเทอมออกตอนเติมปฏิทินอัตโนมัติ)"""
    __tablename__ = "acad_year_setting"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    t1_start = Column(DateTime, nullable=True)
    t1_end = Column(DateTime, nullable=True)
    t2_start = Column(DateTime, nullable=True)
    t2_end = Column(DateTime, nullable=True)


class AcadClassMonth(Base):
    """วันเปิดเรียนรายเดือนของห้อง (ตัวหารของร้อยละเวลาเรียน)"""
    __tablename__ = "acad_class_month"

    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, ForeignKey("acad_class.id"), nullable=False)
    month = Column(Integer, nullable=False)
    days_open = Column(Integer, nullable=True)


class AcadActivity(Base):
    """กิจกรรมพัฒนาผู้เรียนของชั้นนั้นในปีนั้น - ตั้งค่าเองได้ (ขนานกับ AcadSubject)
    แต่ละโรงเรียนจัดกิจกรรมต่างกัน จึงไม่ฝังตายตัว"""
    __tablename__ = "acad_activity"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    level = Column(String, default="")
    code = Column(String, default="")       # ก16901
    name = Column(String, nullable=False)   # แนะแนว / ลูกเสือ-เนตรนารี / ...
    hours = Column(Integer, nullable=True)  # เวลาเรียน (ชม./ปี)
    seq = Column(Integer, default=0)


class AcadActivityResult(Base):
    """ผลประเมินกิจกรรมพัฒนาผู้เรียน รายคน x รายกิจกรรม (ผ/มผ)"""
    __tablename__ = "acad_activity_result"

    id = Column(Integer, primary_key=True)
    acad_student_id = Column(Integer, ForeignKey("acad_student.id"), nullable=False)
    activity_id = Column(Integer, ForeignKey("acad_activity.id"), nullable=False)
    result = Column(String, default="")     # "ผ" / "มผ"
