# -*- coding: utf-8 -*-
"""e-Budget ส่วนที่ 1 · จำนวนบุคลากร 16 ประเภท ตามแบบในเว็บ e-Budget

นับให้จากทะเบียนบุคลากร (ตำแหน่ง + ประเภทบุคลากร) แล้วให้ครูแก้ได้ · ค่าที่แก้เก็บแยกตามปีงบ + ครั้งที่รายงาน
"""
import re

ROWS = [
    ("1", "ผู้อำนวยการโรงเรียน"),
    ("2", "รองผู้อำนวยการโรงเรียน"),
    ("3", "ครู"),
    ("4", "ครูมาช่วยราชการ"),
    ("5", "ครูอัตราจ้าง (เงินงบประมาณ)"),
    ("6", "ครูอัตราจ้าง (เงินจากแหล่งอื่น)"),
    ("7", "พนักงานราชการ (ครู)"),
    ("8", "พนักงานราชการ (นอกเหนือครู)"),
    ("9", "ธุรการโครงการคืนครูให้นักเรียน"),
    ("10", "บุคลากรทางการศึกษา 38ค.(2)"),
    ("11", "นักการภารโรง"),
    ("12", "พนักงานขับรถ"),
    ("13", "ช่างไฟฟ้า/ช่างไม้/ช่างครุภัณฑ์/ช่างอื่น ๆ"),
    ("14", "เจ้าหน้าที่ประจำห้องปฏิบัติการ"),
    ("15", "พี่เลี้ยงเด็กพิการ"),
    ("16", "อื่น ๆ"),
]
CODES = [c for c, _ in ROWS]

# ลำดับสำคัญ: คำเฉพาะก่อนคำกว้าง (เช่น "รองผู้อำนวยการ" ก่อน "ผู้อำนวยการ", "พนักงานราชการ" ก่อน "ครู")
_RULES = [
    ("15", r"พี่เลี้ยง"),
    ("12", r"ขับรถ|พนักงานขับ"),
    ("13", r"ช่าง"),
    ("11", r"ภารโรง|นักการ"),
    ("14", r"ห้องปฏิบัติการ|ห้องแล็บ|ห้องวิทย"),
    ("2", r"รอง\s*ผู้อำนวยการ|รอง\s*ผอ"),
    ("1", r"ผู้อำนวยการ|^ผอ\.?|ผู้บริหาร"),
    ("4", r"ช่วยราชการ"),
    ("7", r"พนักงานราชการ.*(ครู|สอน)|ครู.*พนักงานราชการ"),
    ("8", r"พนักงานราชการ"),
    ("5", r"(อัตราจ้าง|ครูจ้าง|จ้างสอน).*(งบประมาณ|สพฐ)"),
    ("6", r"อัตราจ้าง|ครูจ้าง|จ้างสอน|ลูกจ้าง.*ครู"),
    ("9", r"ธุรการ"),
    ("10", r"38\s*ค|บุคลากรทางการศึกษา|บรรณารักษ์|นักวิชาการ"),
    ("3", r"ครู"),
]


def classify(position: str, person_type: str = "") -> str:
    """ตำแหน่ง + ประเภทบุคลากร -> ข้อในส่วนที่ 1 (ตกข้อ 16 อื่น ๆ ถ้าบอกไม่ได้)"""
    pos = (position or "").strip()
    typ = (person_type or "").strip()
    for text in (pos, typ, pos + " " + typ):
        if not text.strip():
            continue
        for code, rx in _RULES:
            if re.search(rx, text):
                return code
    return "16"


def auto_counts(db) -> dict:
    from app.models import Person
    out = {c: 0 for c in CODES}
    for p in db.query(Person).filter(Person.active.is_(True)):
        out[classify(p.position, p.person_type)] += 1
    return out


def rows(db, fiscal_year: int, rnd: int) -> dict:
    """{rows: [{code, label, auto, value, edited}], total, saved}"""
    from app.models import EbudgetStaff
    auto = auto_counts(db)
    saved = {r.code: r.count for r in db.query(EbudgetStaff).filter_by(fiscal_year=fiscal_year, round=rnd)}
    out = []
    for code, label in ROWS:
        val = saved.get(code, auto[code])
        out.append(dict(code=code, label=label, auto=auto[code], value=val,
                        edited=code in saved and saved[code] != auto[code]))
    return dict(rows=out, total=sum(r["value"] for r in out), saved=bool(saved))


def save(db, fiscal_year: int, rnd: int, values: dict) -> None:
    """values {code: int} · ครบทุกข้อ (ช่องว่าง = 0) แทนที่ของเดิมทั้งชุด"""
    from app.models import EbudgetStaff
    db.query(EbudgetStaff).filter_by(fiscal_year=fiscal_year, round=rnd).delete()
    for code in CODES:
        n = max(0, min(int(values.get(code, 0) or 0), 9999))
        db.add(EbudgetStaff(fiscal_year=fiscal_year, round=rnd, code=code, count=n))
    db.commit()


def reset(db, fiscal_year: int, rnd: int) -> None:
    """กลับไปใช้ตัวเลขที่นับจากทะเบียนบุคลากร"""
    from app.models import EbudgetStaff
    db.query(EbudgetStaff).filter_by(fiscal_year=fiscal_year, round=rnd).delete()
    db.commit()
