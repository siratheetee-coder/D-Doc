"""
thai_utils.py
-------------
ฟังก์ชันช่วยเรื่องภาษาไทยที่ใช้บ่อยในเอกสารราชการ
- bahttext()      : แปลงตัวเลขเงินเป็นข้อความภาษาไทย เช่น 1250.50 -> "หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์"
- thai_date()     : แปลงวันที่เป็นรูปแบบไทย เช่น "5 มิถุนายน 2569"
- SCHOOL_LEVELS   : ลำดับชั้นเรียน (ใช้ร่วมกันทุกงาน - เดิมคัดลอกไว้หลายที่จนเสี่ยงหลุดกัน)
"""
from datetime import datetime

# ลำดับชั้นเรียนมาตรฐาน (เรียงจากเล็กไปใหญ่) - ใช้ทั้งเลื่อนชั้น/จัดกลุ่ม/เรียงรายงาน
# แหล่งความจริงเดียว: pages(เลื่อนชั้น) · lunch(ภาวะโภชนาการ) · textbooks · academic
SCHOOL_LEVELS = ["อ.1", "อ.2", "อ.3", "ป.1", "ป.2", "ป.3", "ป.4", "ป.5", "ป.6",
                 "ม.1", "ม.2", "ม.3"]
GRADUATED = "จบการศึกษา"

_LEVEL_FULL = {"อ": "อนุบาลปีที่", "ป": "ประถมศึกษาปีที่", "ม": "มัธยมศึกษาปีที่"}


def level_full(lv: str) -> str:
    """'ป.6' -> 'ชั้นประถมศึกษาปีที่ 6' (รูปแบบอื่นคืนตามเดิม)"""
    head, _, num = (lv or "").strip().partition(".")
    return f"ชั้น{_LEVEL_FULL[head]} {num}" if head in _LEVEL_FULL and num else (lv or "").strip()


def level_range(levels) -> str:
    """ระดับชั้นสำหรับเอกสาร: 1 ชั้น = ชื่อชั้น · 2 ชั้น = ก และ ข · มากกว่านั้น = ชั้นแรก ถึง ชั้นสุดท้าย
    ไม่ไล่ทุกชั้น (เช่น ป.1 ... ม.3 -> 'ชั้นประถมศึกษาปีที่ 1 ถึงชั้นมัธยมศึกษาปีที่ 3')"""
    def key(lv):
        head, _, num = lv.partition(".")
        try:
            return ({"อ": 0, "ป": 1, "ม": 2}.get(head, 9), int(num))
        except ValueError:
            return (9, 99)
    seen = sorted({(x or "").strip() for x in levels if (x or "").strip()}, key=key)
    if not seen:
        return ""
    if len(seen) == 1:
        return level_full(seen[0])
    if len(seen) == 2:
        return f"{level_full(seen[0])} และ{level_full(seen[1])}"
    return f"{level_full(seen[0])} ถึง{level_full(seen[-1])}"


def is_secondary(level: str) -> bool:
    """ชั้นนี้เป็นมัธยมไหม - มัธยมตัดสินผลการเรียนรายภาค ประถม/อนุบาลตัดสินรายปี
    (ตามหลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน)"""
    return (level or "").strip().startswith("ม.")


def level_rank(level: str) -> int:
    """ลำดับของชั้นสำหรับเรียง - ชั้นที่ไม่อยู่ในลิสต์มาตรฐานไปอยู่ท้ายสุด"""
    try:
        return SCHOOL_LEVELS.index((level or "").strip())
    except ValueError:
        return 99

_THAI_DIGITS = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_THAI_PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]
_THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def _read_integer(num: int) -> str:
    """อ่านจำนวนเต็มเป็นข้อความไทย (รองรับหลักล้านแบบวนซ้ำ)"""
    if num == 0:
        return _THAI_DIGITS[0]

    # ตัดเป็นกลุ่มละ 6 หลัก (หลักล้าน) แล้วต่อด้วย "ล้าน"
    if num >= 1_000_000:
        return _read_integer(num // 1_000_000) + "ล้าน" + (
            _read_integer(num % 1_000_000) if num % 1_000_000 else ""
        )

    digits = [int(d) for d in str(num)]
    length = len(digits)
    result = ""
    for i, d in enumerate(digits):
        place = length - i - 1  # ตำแหน่งหลัก (0=หน่วย,1=สิบ,...)
        if d == 0:
            continue
        if place == 0 and d == 1 and length > 1:
            result += "เอ็ด"            # ...สิบเอ็ด, ...ยี่สิบเอ็ด
        elif place == 1 and d == 1:
            result += "สิบ"             # สิบ (ไม่ใช่ "หนึ่งสิบ")
        elif place == 1 and d == 2:
            result += "ยี่สิบ"          # ยี่สิบ
        else:
            result += _THAI_DIGITS[d] + _THAI_PLACES[place]
    return result


def bahttext(amount: float) -> str:
    """
    แปลงจำนวนเงินเป็นข้อความภาษาไทย
    เช่น 1250.50 -> "หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์"
         1000    -> "หนึ่งพันบาทถ้วน"
    """
    amount = round(float(amount), 2)
    baht = int(amount)
    satang = int(round((amount - baht) * 100))

    text = _read_integer(baht) + "บาท"
    if satang == 0:
        text += "ถ้วน"
    else:
        text += _read_integer(satang) + "สตางค์"
    return text


def thai_date(dt: datetime | None = None) -> str:
    """แปลงวันที่เป็นรูปแบบไทยสั้น เช่น '5 มิถุนายน 2569' (ใช้ในช่องลงนาม)"""
    if dt is None:
        dt = datetime.now()
    return f"{dt.day} {_THAI_MONTHS[dt.month]} {dt.year + 543}"


def thai_date_official(dt: datetime | None = None) -> str:
    """
    แปลงวันที่เป็นรูปแบบหัวบันทึกข้อความราชการ
    เช่น '28 เดือน พฤษภาคม พ.ศ. 2569'
    """
    if dt is None:
        dt = datetime.now()
    return f"{dt.day} เดือน {_THAI_MONTHS[dt.month]} พ.ศ. {dt.year + 543}"


def be_date_input(dt) -> str:
    """ฟอร์แมตวันที่เป็น พ.ศ. สำหรับช่องกรอก เช่น '06/06/2569' (ว่างถ้าไม่มี)
    รับได้ทั้ง datetime และสตริง (เช่นค่าที่ AI คืนมาเป็น 'วว/ดด/ปปปป' อยู่แล้ว)"""
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt.strip()
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}"


def parse_be_date(s: str):
    """
    แปลงข้อความวันที่ที่ผู้ใช้กรอกเป็น datetime
    รองรับรูปแบบ:
      'วว/ดด/ปปปป' หรือ 'วว-ดด-ปปปป' (พ.ศ.) เช่น 06/06/2569
      'DDMMYYYY' หรือ 'DMMYYYY' (8/7 ตัวเลขติดกัน ไม่มี slash) เช่น 09062569
      'yyyy-mm-dd' (ค.ศ.) เช่น 2026-06-09
    คืน None ถ้าว่าง/ผิดรูปแบบ
    """
    import re
    s = (s or "").strip()
    if not s:
        return None

    # รูปแบบที่มี separator (วว/ดด/ปปปป หรือ วว-ดด-ปปปป)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{3,4})$", s)
    if m:
        d, mo, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr > 2400:
            yr -= 543
        try:
            return datetime(yr, mo, d)
        except ValueError:
            return None

    # รูปแบบตัวเลขติดกัน 7-8 หลัก (DDMMYYYY หรือ DMMYYYY)
    if re.match(r"^\d{7,8}$", s):
        padded = s.zfill(8)   # เติม 0 นำหน้าให้ครบ 8 หลัก
        d, mo, yr = int(padded[0:2]), int(padded[2:4]), int(padded[4:8])
        if yr > 2400:
            yr -= 543
        try:
            return datetime(yr, mo, d)
        except ValueError:
            return None

    # รูปแบบ ค.ศ. yyyy-mm-dd (จาก input type=date เดิม)
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def current_fiscal_year(dt: datetime | None = None) -> int:
    """
    หาปีงบประมาณ พ.ศ. ปัจจุบัน
    ปีงบประมาณไทยเริ่ม 1 ตุลาคม ดังนั้น ต.ค.-ธ.ค. ให้นับเป็นปีงบถัดไป
    """
    if dt is None:
        dt = datetime.now()
    be_year = dt.year + 543
    if dt.month >= 10:          # ตั้งแต่ตุลาคม = ปีงบประมาณถัดไป
        return be_year + 1
    return be_year


def current_academic_year(dt: datetime | None = None) -> int:
    """หาปีการศึกษา พ.ศ. ปัจจุบัน
    ปีการศึกษาไทยเริ่มราวพฤษภาคม ดังนั้น ม.ค.-เม.ย. ยังนับเป็นปีการศึกษาก่อนหน้า"""
    if dt is None:
        dt = datetime.now()
    be_year = dt.year + 543
    if dt.month <= 4:           # ม.ค.-เม.ย. = ยังเป็นปีการศึกษาก่อนหน้า
        return be_year - 1
    return be_year


def current_term(dt: datetime | None = None) -> int:
    """หาภาคเรียนปัจจุบันจากเดือน · ภาค 1 = พ.ค.-ต.ค. · ภาค 2 = พ.ย.-เม.ย."""
    if dt is None:
        dt = datetime.now()
    return 1 if 5 <= dt.month <= 10 else 2
