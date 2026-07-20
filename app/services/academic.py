# -*- coding: utf-8 -*-
"""
academic.py — ตรรกะกลางของงานวิชาการ (ใช้ร่วมกันระหว่าง router และตัวสร้างเอกสาร)

- grade_of()        : แปลงคะแนนเป็นระดับผลการเรียน
- subject_preset()  : รายวิชาพื้นฐาน 8 กลุ่มสาระ + รหัสวิชาตามหลักสูตรแกนกลาง 2551
- term_choices()    : ประถมตัดสินรายปี · มัธยมตัดสินรายภาค
"""
from app.thai_utils import SCHOOL_LEVELS, is_secondary

# ---- ระดับผลการเรียน ----
# เกณฑ์ที่โรงเรียนส่วนใหญ่ใช้ (ปรับได้ที่นี่ที่เดียวถ้าโรงเรียนใช้เกณฑ์อื่น)
GRADE_CUTS = [(80, "4"), (75, "3.5"), (70, "3"), (65, "2.5"),
              (60, "2"), (55, "1.5"), (50, "1"), (0, "0")]
# ผลการเรียนที่กรอกเองได้ (นอกเหนือจากที่คำนวณจากคะแนน)
SPECIAL_GRADES = ["ร", "มส", "ผ", "มผ"]
GRADE_CHOICES = [g for _, g in GRADE_CUTS] + SPECIAL_GRADES

PASS_FAIL = ["ผ", "มผ"]                       # กิจกรรมพัฒนาผู้เรียน
QUALITY_LEVELS = ["ดีเยี่ยม", "ดี", "ผ่าน", "ไม่ผ่าน"]   # อ่านคิดวิเคราะห์ฯ / คุณลักษณะฯ
SUBJECT_KINDS = ["พื้นฐาน", "เพิ่มเติม"]


def grade_of(score) -> str:
    """คะแนน (0-100) -> ระดับผลการเรียน · คืน "" ถ้าไม่มีคะแนน"""
    if score is None or score == "":
        return ""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    for cut, g in GRADE_CUTS:
        if s >= cut:
            return g
    return "0"


def grade_point(grade) -> float | None:
    """ระดับผลการเรียน (str) -> ตัวเลขสำหรับคิดเฉลี่ย
    "ร"/"มส"/"ผ"/"มผ" และช่องว่าง -> None (ห้ามนับเป็น 0 — จะกดเฉลี่ยเด็กโดยไม่เป็นธรรม)"""
    g = (str(grade) if grade is not None else "").strip()
    if not g or g in SPECIAL_GRADES:
        return None
    try:
        return float(g)
    except ValueError:
        return None


def weighted_avg(pairs) -> float | None:
    """ผลการเรียนเฉลี่ยถ่วงน้ำหนัก · pairs = [(grade_str, weight), ...]
    - เกรดที่แปลงเป็นตัวเลขไม่ได้ (ร/มส/ผ/มผ/ว่าง) ถูกข้าม
    - weight <= 0 หรือไม่มี -> ใช้ 1 (เฉลี่ยตรง) เพื่อไม่ให้วิชาหายจากเฉลี่ยเงียบ ๆ
    - ไม่มีเกรดนับได้เลย -> None (แสดงเป็นช่องว่าง ไม่ใช่ 0)"""
    total_w, total = 0.0, 0.0
    for grade, weight in pairs:
        p = grade_point(grade)
        if p is None:
            continue
        try:
            w = float(weight) if weight else 0.0
        except (TypeError, ValueError):
            w = 0.0
        if w <= 0:
            w = 1.0
        total += p * w
        total_w += w
    return (total / total_w) if total_w > 0 else None


def term_choices(level: str) -> list:
    """ภาคเรียนที่ต้องกรอกของชั้นนี้
    ประถม/อนุบาล -> [0] (ตัดสินรายปี) · มัธยม -> [1, 2] (ตัดสินรายภาค)"""
    return [1, 2] if is_secondary(level) else [0]


def term_label(term) -> str:
    return {0: "ทั้งปี", 1: "ภาคเรียนที่ 1", 2: "ภาคเรียนที่ 2"}.get(int(term or 0), "ทั้งปี")


# ---- รายวิชาพื้นฐาน 8 กลุ่มสาระ (หลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน 2551) ----
# (อักษรนำรหัส, กลุ่มสาระ, ชื่อรายวิชา, เวลาเรียนเริ่มต้น ชม./ปี)
# หมายเหตุ: เวลาเรียนเป็น "ค่าเริ่มต้นให้แก้" — แต่ละโรงเรียนจัดโครงสร้างเวลาเรียนเอง
_BASE_SUBJECTS = [
    ("ท", "ภาษาไทย", "ภาษาไทย", 200),
    ("ค", "คณิตศาสตร์", "คณิตศาสตร์", 200),
    ("ว", "วิทยาศาสตร์และเทคโนโลยี", "วิทยาศาสตร์และเทคโนโลยี", 80),
    ("ส", "สังคมศึกษา ศาสนา และวัฒนธรรม", "สังคมศึกษา ศาสนา และวัฒนธรรม", 80),
    ("ส", "สังคมศึกษา ศาสนา และวัฒนธรรม", "ประวัติศาสตร์", 40),
    ("พ", "สุขศึกษาและพลศึกษา", "สุขศึกษาและพลศึกษา", 80),
    ("ศ", "ศิลปะ", "ศิลปะ", 80),
    ("ง", "การงานอาชีพ", "การงานอาชีพ", 40),
    ("อ", "ภาษาต่างประเทศ", "ภาษาอังกฤษ", 200),
]


def _code_parts(level: str):
    """แปลงชั้นเป็นส่วนของรหัสวิชา -> (เลขระดับ, เลขปีในระดับ)
    ป.1-6 -> (1, 1..6) · ม.1-3 -> (2, 1..3) · อนุบาลไม่มีรหัสวิชา -> None"""
    lv = (level or "").strip()
    if lv.startswith("ป."):
        try:
            return 1, int(lv[2:])
        except ValueError:
            return None
    if lv.startswith("ม."):
        try:
            return 2, int(lv[2:])
        except ValueError:
            return None
    return None


def subject_code(prefix: str, level: str, seq: int, kind: str = "พื้นฐาน") -> str:
    """ประกอบรหัสวิชาตามแบบหลักสูตรแกนกลาง เช่น ป.1 ภาษาไทย -> ท11101
    รูปแบบ: [อักษรกลุ่มสาระ][ระดับ][ปีในระดับ][ประเภท 1=พื้นฐาน 2=เพิ่มเติม][ลำดับ 2 หลัก]"""
    parts = _code_parts(level)
    if not parts:
        return ""
    band, yr = parts
    kind_digit = 1 if kind == "พื้นฐาน" else 2
    return f"{prefix}{band}{yr}{kind_digit}{seq:02d}"


def subject_preset(level: str) -> list:
    """รายวิชาพื้นฐานครบชุดของชั้นนี้ (สำหรับปุ่มสร้างสำเร็จรูป)
    คืน list ของ dict พร้อมใช้สร้าง AcadSubject — เวลาเรียนเป็นค่าเริ่มต้นที่แก้ได้"""
    if not _code_parts(level):
        return []                      # อนุบาล/ชั้นนอกระบบ: ไม่มีรหัสวิชามาตรฐาน
    out, n = [], 0
    for prefix, group, name, hours in _BASE_SUBJECTS:
        n += 1
        out.append({
            "code": subject_code(prefix, level, 1 if name != "ประวัติศาสตร์" else 2),
            "name": name,
            "learn_group": group,
            "kind": "พื้นฐาน",
            "hours": hours,
            "seq": n,
        })
    return out
