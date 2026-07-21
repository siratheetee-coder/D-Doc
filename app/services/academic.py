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

# ---- ประเมินละเอียดรายวิชา (ตามโครง ปพ.5 จริง) ----
# คุณลักษณะอันพึงประสงค์ 8 ข้อ ตามหลักสูตรแกนกลาง 2551
CHAR_ITEMS = ["รักชาติ ศาสน์ กษัตริย์", "ซื่อสัตย์สุจริต", "มีวินัย", "ใฝ่เรียนรู้",
              "อยู่อย่างพอเพียง", "มุ่งมั่นในการทำงาน", "รักความเป็นไทย", "มีจิตสาธารณะ"]
CHAR_FIELDS = [f"c{i}" for i in range(1, 9)]
READ_DOMAINS = [("r_read", "การอ่าน"), ("r_think", "การคิดวิเคราะห์"),
                ("r_write", "การเขียนสื่อความ")]
# ปีการศึกษาไทย: พ.ค. -> มี.ค. (เลขเดือนปฏิทิน)
TH_MONTHS = [(5, "พ.ค."), (6, "มิ.ย."), (7, "ก.ค."), (8, "ส.ค."), (9, "ก.ย."), (10, "ต.ค."),
             (11, "พ.ย."), (12, "ธ.ค."), (1, "ม.ค."), (2, "ก.พ."), (3, "มี.ค.")]
TH_MONTH_FULL = {5: "พฤษภาคม", 6: "มิถุนายน", 7: "กรกฎาคม", 8: "สิงหาคม", 9: "กันยายน",
                 10: "ตุลาคม", 11: "พฤศจิกายน", 12: "ธันวาคม", 1: "มกราคม", 2: "กุมภาพันธ์",
                 3: "มีนาคม"}
# ตัวย่อวันในสัปดาห์ เรียงตาม date.weekday() (จันทร์=0 ... อาทิตย์=6)
TH_WEEKDAYS = ["จ", "อ", "พ", "พฤ", "ศ", "ส", "อา"]

# ---- เช็กชื่อรายวัน ----
# marks = สตริง 31 ตัว ตำแหน่ง = วันที่-1 · "." = ไม่ใช่วันเรียน/ยังไม่กรอก
MARK_BLANK = "."
MARK_STATES = [("/", "มา"), ("ป", "ป่วย"), ("ล", "ลา"), ("ข", "ขาด")]
MARK_CHARS = [ch for ch, _ in MARK_STATES]


def academic_ce_year(be_year: int, month: int) -> int:
    """ปี ค.ศ. ของเดือนนั้นในปีการศึกษา พ.ศ. ที่ให้มา
    ปีการศึกษาไทยคร่อม 2 ปีปฏิทิน: พ.ค.-ธ.ค. = ปีเดียวกัน · ม.ค.-เม.ย. = ปีถัดไป
    (ต้องใช้ค่านี้หาว่าวันที่หนึ่ง ๆ ตรงกับวันอะไร ไม่งั้นปฏิทินเพี้ยนทั้งเทอมปลาย)"""
    ce = int(be_year) - 543
    return ce + 1 if int(month) <= 4 else ce


def month_weekdays(be_year: int, month: int) -> dict:
    """{วันที่: ตัวย่อวันไทย} ของทุกวันในเดือนนั้น"""
    import calendar as _cal
    from datetime import date
    ce = academic_ce_year(be_year, month)
    ndays = _cal.monthrange(ce, int(month))[1]
    return {d: TH_WEEKDAYS[date(ce, int(month), d).weekday()] for d in range(1, ndays + 1)}


def default_open_days(be_year: int, month: int) -> list:
    """วันจันทร์-ศุกร์ทั้งหมดของเดือนนั้น (ค่าตั้งต้นของปฏิทิน — วันหยุดราชการให้ครูคลิกปิดเอง)"""
    import calendar as _cal
    from datetime import date
    ce = academic_ce_year(be_year, month)
    ndays = _cal.monthrange(ce, int(month))[1]
    return [d for d in range(1, ndays + 1) if date(ce, int(month), d).weekday() < 5]


def parse_days_csv(s) -> list:
    """"3,4,5" -> [3, 4, 5] · ข้ามค่าที่ไม่ใช่ตัวเลข/นอกช่วง 1-31"""
    out = []
    for part in (s or "").split(","):
        part = part.strip()
        if part.isdigit():
            n = int(part)
            if 1 <= n <= 31:
                out.append(n)
    return sorted(set(out))


def parse_marks(s) -> dict:
    """สตริง marks -> {วันที่: สัญลักษณ์} เฉพาะวันที่มีค่าจริง"""
    s = s or ""
    return {i + 1: ch for i, ch in enumerate(s[:31]) if ch in MARK_CHARS}


def build_marks(day_map) -> str:
    """{วันที่: สัญลักษณ์} -> สตริง 31 ตัว"""
    chars = []
    for d in range(1, 32):
        ch = (day_map or {}).get(d, MARK_BLANK)
        chars.append(ch if ch in MARK_CHARS else MARK_BLANK)
    return "".join(chars)


def count_marks(s) -> dict:
    """นับจำนวนวันแต่ละสถานะ -> {"/": n, "ป": n, "ล": n, "ข": n} · สตริงว่าง = 0 ทุกตัว"""
    s = s or ""
    return {ch: s.count(ch) for ch in MARK_CHARS}


def quality_of_avg(avg):
    """คะแนนเฉลี่ย (0-3) -> (เลขระดับ, ป้าย) ตามเกณฑ์ในไฟล์ ปพ.5 จริง
    >=2.5 ดีเยี่ยม(3) · 1.5-2.49 ดี(2) · 1-1.49 ผ่าน(1) · <1 ไม่ผ่าน(0) · None -> ("","")"""
    if avg is None:
        return "", ""
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return "", ""
    if a >= 2.5:
        return 3, "ดีเยี่ยม"
    if a >= 1.5:
        return 2, "ดี"
    if a >= 1.0:
        return 1, "ผ่าน"
    return 0, "ไม่ผ่าน"


def _avg(values):
    """เฉลี่ยเฉพาะค่าที่ไม่ใช่ None · ไม่มีเลย -> None (ห้ามนับช่องว่างเป็น 0)"""
    xs = [v for v in values if v is not None]
    return (sum(xs) / len(xs)) if xs else None


def char_avg(row):
    return _avg(getattr(row, f) for f in CHAR_FIELDS)


def read_avg(row):
    return _avg(getattr(row, f) for f, _ in READ_DOMAINS)


def effective_eval(student, db) -> dict:
    """ค่าที่เอกสาร/หน้าจอควรใช้จริงของนักเรียน 1 คน — จุดตัดสินใจเดียว
    มีข้อมูลละเอียดรายวิชา -> คำนวณ · ไม่มี -> ใช้ค่า manual ใน AcadEval เดิม
    คืน dict: desired_char/read_think (ป้าย), char_src/read_src ('detail'/'manual'),
              days_open/present/sick/leave/absent, att_src, months {เดือน: มา}"""
    from app.models import AcadCharEval, AcadReadEval, AcadAttendance, AcadClassMonth
    e = student.eval
    out = {"desired_char": (e.desired_char if e else "") or "",
           "read_think": (e.read_think if e else "") or "",
           "char_src": "manual", "read_src": "manual",
           "days_open": e.days_open if e else None,
           "days_present": e.days_present if e else None,
           "days_sick": e.days_sick if e else None,
           "days_leave": e.days_leave if e else None,
           "days_absent": e.days_absent if e else None,
           "att_src": "manual", "months": {}}

    # คุณลักษณะฯ: ผลรายวิชา (เลข 0-3) -> เฉลี่ยข้ามวิชา -> ป้าย (ตามชีตสรุปทั้งปีของไฟล์จริง)
    rows = db.query(AcadCharEval).filter_by(acad_student_id=student.id).all()
    nums = [quality_of_avg(char_avg(r))[0] for r in rows]
    nums = [n for n in nums if n != ""]
    if nums:
        out["desired_char"] = quality_of_avg(_avg(nums))[1]
        out["char_src"] = "detail"

    rows = db.query(AcadReadEval).filter_by(acad_student_id=student.id).all()
    nums = [quality_of_avg(read_avg(r))[0] for r in rows]
    nums = [n for n in nums if n != ""]
    if nums:
        out["read_think"] = quality_of_avg(_avg(nums))[1]
        out["read_src"] = "detail"

    # เวลาเรียน: เช็กชื่อรายวัน > ยอดรายเดือน > ยอดทั้งปีที่กรอกมือ
    att = db.query(AcadAttendance).filter_by(acad_student_id=student.id).all()
    marked = [a for a in att if (a.marks or "").strip(MARK_BLANK)]
    if marked:
        # นับจาก marks: ได้ทั้งวันมาและยอด ป่วย/ลา/ขาด โดยครูไม่ต้องกรอกซ้ำ
        tot = {ch: 0 for ch in MARK_CHARS}
        for a in marked:
            for ch, n in count_marks(a.marks).items():
                tot[ch] += n
        out["months"] = {a.month: count_marks(a.marks)["/"] for a in marked}
        out["days_present"] = tot["/"]
        out["days_sick"], out["days_leave"], out["days_absent"] = tot["ป"], tot["ล"], tot["ข"]
        out["att_src"] = "daily"
    else:
        filled = [a for a in att if a.present is not None]
        if filled:
            out["months"] = {a.month: a.present for a in filled}
            out["days_present"] = sum(a.present for a in filled)
            out["att_src"] = "detail"

    if out["att_src"] != "manual":
        # ตัวหาร: ใช้ปฏิทินการศึกษาถ้าตั้งไว้ ไม่งั้นใช้วันเปิดรายเดือนของห้อง
        total_open = _calendar_days_open(student, db)
        if not total_open:
            opens = db.query(AcadClassMonth).filter_by(class_id=student.class_id).all()
            total_open = sum(m.days_open for m in opens if m.days_open is not None)
        if total_open:
            out["days_open"] = total_open
    return out


def _calendar_days_open(student, db) -> int:
    """รวมวันเปิดเรียนทั้งปีจากปฏิทินการศึกษาของโรงเรียน (0 = ยังไม่ได้ตั้งปฏิทิน)"""
    from app.models import AcadCalendar
    klass = student.klass
    if not klass:
        return 0
    rows = db.query(AcadCalendar).filter_by(year=klass.year).all()
    return sum(len(parse_days_csv(r.days_csv)) for r in rows)


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
