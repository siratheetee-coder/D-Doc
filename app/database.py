"""
database.py
-----------
จุดเชื่อมต่อฐานข้อมูล SQLite ด้วย SQLAlchemy

โหมด multi-tenant: **1 โรงเรียน = 1 ไฟล์ฐานข้อมูล** (data/schools/<id>/school.db)
- ตัวเลือก engine/session ต่อโรงเรียนอยู่ใน app/tenancy.py
- get_db() เลือกฐานข้อมูลตามโรงเรียนที่ล็อกอิน (current_school_id)
- ฐานข้อมูลกลาง (บัญชีผู้ใช้/โรงเรียน) อยู่ใน app/accounts.py

โมเดลและ migration เดิมใช้ต่อได้ทั้งหมด เพราะภายในแต่ละ DB ยังเป็น "โรงเรียนเดียว"
"""
from pathlib import Path
import sys
import shutil
from datetime import datetime

from sqlalchemy.orm import declarative_base


def get_data_dir() -> Path:
    """โฟลเดอร์เก็บข้อมูล (data/) - รากโปรเจกต์ หรือข้าง ๆ .exe เมื่อแพ็กแล้ว"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


# Base = คลาสแม่ของทุกตารางในไฟล์ models.py (ใช้ร่วมทุกโรงเรียน)
Base = declarative_base()


# รายการเพิ่มคอลัมน์ใหม่บน DB เก่า (ปลอดภัย: ข้ามถ้ามีอยู่แล้ว)
MIGRATIONS = [
    ("certificate_batch", "cert_no_on",     "INTEGER DEFAULT 0"),
    ("certificate_batch", "cert_no_prefix", "VARCHAR DEFAULT ''"),
    ("certificate_batch", "cert_no_x",      "FLOAT DEFAULT 50.0"),
    ("certificate_batch", "cert_no_y",      "FLOAT DEFAULT 85.0"),
    ("certificate_batch", "cert_no_size",   "INTEGER DEFAULT 26"),
    ("vendor",      "owner_name",       "VARCHAR DEFAULT ''"),
    ("procurement", "spec_memo_date",   "DATETIME"),
    ("procurement", "result_memo_date", "DATETIME"),
    ("procurement", "command_date",     "DATETIME"),
    ("procurement", "delivery_date",    "DATETIME"),
    ("project",     "budget",           "FLOAT DEFAULT 0"),
    ("project",     "budget_note",      "VARCHAR DEFAULT ''"),
    ("incoming_letter", "file_path",    "VARCHAR DEFAULT ''"),
    ("procurement",     "file_path",    "VARCHAR DEFAULT ''"),
    ("school",          "ai_api_key",   "VARCHAR DEFAULT ''"),
    ("finance_txn",     "item_id",      "INTEGER"),
    ("receipt",         "txn_id",       "INTEGER"),
    ("finance_account", "deposit_type", "VARCHAR DEFAULT 'bank'"),
    ("account_item",    "deposit_type", "VARCHAR DEFAULT 'bank'"),
    ("disburse_memo",   "vat",          "FLOAT DEFAULT 0"),
    ("disburse_memo",   "wht",          "FLOAT DEFAULT 0"),
    ("disburse_memo",   "fine",         "FLOAT DEFAULT 0"),
    ("disburse_memo",   "proc_kind",    "VARCHAR DEFAULT 'จัดซื้อ'"),
    ("school", "finance_officer_name",  "VARCHAR DEFAULT ''"),
    ("school", "finance_head_name",     "VARCHAR DEFAULT ''"),
    ("school", "admin_officer_name",    "VARCHAR DEFAULT ''"),
    ("asset", "brand_model",     "VARCHAR DEFAULT ''"),
    ("asset", "vendor_address",  "VARCHAR DEFAULT ''"),
    ("asset", "fund_type",       "VARCHAR DEFAULT 'เงินงบประมาณ'"),
    ("asset", "acquire_method",  "VARCHAR DEFAULT 'วิธีเฉพาะเจาะจง'"),
    ("asset", "doc_ref",         "VARCHAR DEFAULT ''"),
    ("asset", "quantity",        "FLOAT DEFAULT 1"),
    ("asset", "unit",            "VARCHAR DEFAULT 'หน่วย'"),
    ("project", "plan_year",     "INTEGER"),
    ("project", "responsible",   "VARCHAR DEFAULT ''"),
    ("project", "active",        "BOOLEAN DEFAULT 1"),
    ("procurement", "project_id", "INTEGER"),
    ("procurement", "proc_case", "VARCHAR DEFAULT 'normal'"),
    ("procurement", "case_extra", "TEXT DEFAULT ''"),
    ("procurement", "wht_rate", "FLOAT DEFAULT 0"),
    ("disburse_memo", "project_id", "INTEGER"),
    ("disburse_memo", "item_id", "INTEGER"),
    ("school", "project_year_mode", "VARCHAR DEFAULT 'budget'"),
    ("asset", "disposed_date",   "DATETIME"),
    ("asset", "dispose_method",  "VARCHAR DEFAULT ''"),
    ("asset", "dispose_reason",  "VARCHAR DEFAULT ''"),
    ("asset", "dispose_value",   "FLOAT DEFAULT 0"),
    ("asset", "dispose_doc_ref", "VARCHAR DEFAULT ''"),
    ("lunch_ledger", "round_id", "INTEGER"),
    ("lunch_ledger", "installment_id", "INTEGER"),
    ("lunch_hire_round", "order_no", "VARCHAR DEFAULT ''"),
    ("lunch_hire_round", "order_date", "DATETIME"),
    ("lunch_hire_round", "memo_no", "VARCHAR DEFAULT ''"),
    ("lunch_hire_round", "memo_date", "DATETIME"),
    ("lunch_hire_round", "command_no", "VARCHAR DEFAULT ''"),
    ("lunch_hire_round", "command_date", "DATETIME"),
    ("lunch_hire_round", "doc_nos", "TEXT DEFAULT ''"),
    ("procurement", "quotation_date", "DATETIME"),
    ("lunch_ledger", "finance_txn_id", "INTEGER"),   # ผูกกับรายการในบัญชีการเงินหลัก
    ("lunch_student", "student_id", "INTEGER"),       # ดึงมาจากทะเบียนนักเรียนกลาง
    ("person", "signature", "VARCHAR DEFAULT ''"),    # ไฟล์ลายเซ็นบุคลากร (PNG โปร่งใส)
    ("finance_account", "fund_type", "VARCHAR DEFAULT 'เงินนอกงบประมาณ'"),  # ประเภทเงินตามงบ (สมุดเงินสด)
    ("account_item", "parent_id", "INTEGER"),         # หมวดแม่ (ซ้อนหมวดย่อย 2 ชั้น)
    ("lunch_program", "pool", "INTEGER DEFAULT 0"),   # 1 = ทะเบียนภาวะโภชนาการรวมของโรงเรียน (ซ่อนจากรายการโครงการ)
    ("lunch_program", "lunch_officer", "VARCHAR DEFAULT ''"),   # เจ้าหน้าที่โครงการอาหารกลางวัน (คนละคนกับ จนท.พัสดุได้)
    ("lunch_menu", "groups", "VARCHAR DEFAULT ''"),   # หมู่อาหารครบ 5 หมู่ (1-5 คั่นจุลภาค)
    # ---- งานบุคคล: ข้อมูลเพิ่มใน Person ----
    ("person", "person_type", "VARCHAR DEFAULT 'ครู'"),
    ("person", "rank", "VARCHAR DEFAULT ''"),
    ("person", "id_card", "VARCHAR DEFAULT ''"),
    ("person", "birthdate", "DATETIME"),
    ("person", "start_date", "DATETIME"),
    ("person", "phone", "VARCHAR DEFAULT ''"),
    ("person", "email", "VARCHAR DEFAULT ''"),
    ("person", "salary", "FLOAT DEFAULT 0"),
    ("school", "area_office", "VARCHAR DEFAULT ''"),   # สำนักงานเขตพื้นที่การศึกษาที่สังกัด
    ("student", "room", "VARCHAR DEFAULT ''"),         # ห้องเรียน (งานวิชาการ: ปพ.5 เป็นเอกสารรายห้อง)
    ("acad_subject", "mid_max", "INTEGER DEFAULT 70"),   # สัดส่วนคะแนนเก็บ (ต่างกันได้รายวิชา)
    ("acad_subject", "final_max", "INTEGER DEFAULT 30"), # สัดส่วนคะแนนปลายภาค
    ("school", "academic_head_name", "VARCHAR DEFAULT ''"),  # หัวหน้าฝ่ายวิชาการ (ปก ปพ.5)
    ("acad_eval", "days_sick", "INTEGER"),               # สรุปเวลาเรียน ปพ.5: ป่วย/ลา/ขาด (วัน)
    ("acad_eval", "days_leave", "INTEGER"),
    ("acad_eval", "days_absent", "INTEGER"),
    ("acad_attendance", "marks", "VARCHAR DEFAULT ''"),  # เช็กชื่อรายวัน (31 ตัวอักษร)
    # ---- ข้อมูลส่วนตัวนักเรียน (สมุดพก ปพ.6 หน้าข้อมูลส่วนตัว) ----
    ("student", "id_card", "VARCHAR DEFAULT ''"),
    ("student", "father_name", "VARCHAR DEFAULT ''"),
    ("student", "mother_name", "VARCHAR DEFAULT ''"),
    ("student", "race", "VARCHAR DEFAULT ''"),
    ("student", "nationality", "VARCHAR DEFAULT ''"),
    ("student", "religion", "VARCHAR DEFAULT ''"),
    ("student", "blood_group", "VARCHAR DEFAULT ''"),
    ("student", "congenital_disease", "VARCHAR DEFAULT ''"),
    ("student", "addr_no", "VARCHAR DEFAULT ''"),
    ("student", "addr_moo", "VARCHAR DEFAULT ''"),
    ("student", "addr_soi", "VARCHAR DEFAULT ''"),
    ("student", "addr_road", "VARCHAR DEFAULT ''"),
    ("student", "addr_tambon", "VARCHAR DEFAULT ''"),
    ("student", "addr_amphoe", "VARCHAR DEFAULT ''"),
    ("student", "addr_province", "VARCHAR DEFAULT ''"),
    ("student", "addr_zip", "VARCHAR DEFAULT ''"),
    ("student", "phone", "VARCHAR DEFAULT ''"),
    ("student", "enroll_date", "DATETIME"),
    ("student", "prev_school", "VARCHAR DEFAULT ''"),
    ("student", "photo", "BLOB"),
    ("student", "photo_ext", "VARCHAR DEFAULT ''"),
    ("school", "logo", "BLOB"),
    ("school", "logo_ext", "VARCHAR DEFAULT ''"),
    ("acad_indicator_result", "score", "INTEGER"),
    ("acad_subject", "indicator_codes", "TEXT DEFAULT ''"),
    ("student", "father_job", "VARCHAR DEFAULT ''"),
    ("student", "mother_job", "VARCHAR DEFAULT ''"),
    ("student", "guardian_name", "VARCHAR DEFAULT ''"),
    ("student", "guardian_relation", "VARCHAR DEFAULT ''"),
    ("student", "guardian_job", "VARCHAR DEFAULT ''"),
    # ---- ตารางกลาง StudentMeasure สร้างอัตโนมัติผ่าน create_all (ไม่ต้อง migrate คอลัมน์) ----
]


def run_migrations(engine) -> None:
    """เพิ่มคอลัมน์ใหม่บน DB ของโรงเรียนที่ระบุ"""
    conn = engine.raw_connection()
    cursor = conn.cursor()
    for table, col, coltype in MIGRATIONS:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def init_school_db(engine) -> None:
    """สร้างตารางทั้งหมด + เพิ่มคอลัมน์ใหม่ บน DB ของโรงเรียนที่ระบุ"""
    from app import models  # noqa: F401  (ลงทะเบียนตารางทั้งหมด)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    _migrate_lunch_measures(engine)
    _backfill_memo_subjects(engine)


def _backfill_memo_subjects(engine) -> None:
    """เติมชื่อรายงานนำหน้าให้บันทึกข้อความเก่าในทะเบียนเลขหนังสือ (พัสดุ/การเงิน) ครั้งเดียว
    idempotent: อัปเดตเฉพาะแถวที่ subject ยังไม่ตรงกับที่คำนวณได้ (รันซ้ำแล้วไม่เขียนเพิ่ม)"""
    from sqlalchemy.orm import Session
    from app.models import IssuedDocNo, Procurement, DisburseMemo
    from app.services.doc_number import parse_seq

    def _pt(p, base):
        pt = p.proc_type or ""
        return {
            parse_seq(p.memo_no): f"รายงานขอ{pt}{base}",
            parse_seq(p.result_memo_no): f"รายงานผลการพิจารณาและขออนุมัติสั่ง{pt} {base}".strip(),
            parse_seq(p.spec_memo_no): f"ขออนุมัติแต่งตั้งคณะกรรมการกำหนดคุณลักษณะเฉพาะและราคากลาง {base}".strip(),
            parse_seq(p.inspect_memo_no): f"รายงานผลการตรวจรับพัสดุและอนุมัติเบิกจ่ายเงิน {base}".strip(),
        }

    with Session(bind=engine) as db:
        try:
            rows = (db.query(IssuedDocNo)
                    .filter(IssuedDocNo.doc_type == "memo",
                            IssuedDocNo.ref_id.isnot(None),
                            IssuedDocNo.source.in_(("procurement", "finance"))).all())
            changed = 0
            for r in rows:
                new = None
                if r.source == "procurement":
                    p = db.get(Procurement, r.ref_id)
                    if p:
                        new = _pt(p, (p.subject or "").strip()).get(r.seq)
                elif r.source == "finance":
                    m = db.get(DisburseMemo, r.ref_id)
                    if m:
                        s = (m.subject or "").strip()
                        new = s if s.startswith("ขออนุมัติเบิกจ่าย") else f"ขออนุมัติเบิกจ่าย {s}".strip()
                if new and (r.subject or "") != new:
                    r.subject = new
                    changed += 1
            if changed:
                db.commit()
        except Exception:
            db.rollback()


def _migrate_lunch_measures(engine) -> None:
    """ย้ายข้อมูลชั่งน้ำหนัก/ส่วนสูงเดิม (LunchMeasure -> StudentMeasure ส่วนกลาง) ครั้งเดียว
    เฉพาะแถวที่ผูกทะเบียนกลาง (LunchStudent.student_id) · idempotent (ข้ามถ้ามีอยู่แล้ว)"""
    from sqlalchemy.orm import Session
    from app.models import Student, StudentMeasure, LunchStudent, LunchMeasure, LunchProgram
    now = __import__("datetime").datetime.now()
    cur_year = (now.year + 543) if now.month >= 4 else (now.year + 543 - 1)
    with Session(bind=engine) as db:
        try:
            valid_ids = {sid for (sid,) in db.query(Student.id).all()}
            prog_year = {p.id: (p.year or cur_year) for p in db.query(LunchProgram).all()}
            existing = {(sm.student_id, sm.year, sm.term)
                        for sm in db.query(StudentMeasure).all()}
            ls_map = {ls.id: ls for ls in db.query(LunchStudent).all()}
            added = 0
            for lm in db.query(LunchMeasure).all():
                ls = ls_map.get(lm.student_id)
                if not ls or not ls.student_id or ls.student_id not in valid_ids:
                    continue
                if not lm.weight and not lm.height:
                    continue
                year = prog_year.get(ls.program_id, cur_year)
                key = (ls.student_id, year, lm.term or 1)
                if key in existing:
                    continue
                db.add(StudentMeasure(student_id=ls.student_id, year=year, term=lm.term or 1,
                                      date=lm.date, weight=lm.weight or 0.0, height=lm.height or 0.0))
                existing.add(key)
                added += 1
            if added:
                db.commit()
        except Exception:
            db.rollback()


def get_db():
    """ส่งเซสชันของ DB โรงเรียนที่ล็อกอินอยู่ (current_school_id) ให้แต่ละคำขอ"""
    from app.tenancy import current_school_id, session_for
    sid = current_school_id.get()
    db = session_for(sid)
    try:
        yield db
    finally:
        db.close()


# ===================== สำรอง / กู้คืน (ของโรงเรียนปัจจุบัน) =====================
def backups_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(exist_ok=True)
    return d


def _current_engine_path():
    from app.tenancy import current_school_id, engine_for, school_db_path
    sid = current_school_id.get()
    return engine_for(sid), school_db_path(sid)


def _checkpoint() -> None:
    """บังคับเขียนข้อมูลค้าง (WAL) ลงไฟล์ก่อนสำรอง"""
    try:
        engine, _ = _current_engine_path()
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass


def make_backup_copy(label: str = "auto") -> Path:
    """ก๊อปไฟล์ DB ของโรงเรียนปัจจุบันเก็บใน data/backups/"""
    _checkpoint()
    _, db_path = _current_engine_path()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir() / f"school-{label}-{ts}.db"
    shutil.copy2(db_path, dest)
    return dest


def restore_db(data: bytes) -> None:
    """กู้คืน DB ของโรงเรียนปัจจุบันจากไฟล์ที่อัปโหลด (สำรองไฟล์ปัจจุบันก่อนเสมอ)"""
    from app.tenancy import current_school_id, dispose_engine, school_db_path
    make_backup_copy("before-restore")
    sid = current_school_id.get()
    db_path = school_db_path(sid)
    dispose_engine(sid)          # ปิด+ลบ engine ที่แคชไว้ ก่อนเขียนทับ
    with open(db_path, "wb") as f:
        f.write(data)


def current_db_path() -> Path:
    """ที่อยู่ไฟล์ DB ของโรงเรียนปัจจุบัน (ใช้ดาวน์โหลดสำรอง)"""
    _, db_path = _current_engine_path()
    return db_path
