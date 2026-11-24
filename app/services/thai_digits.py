"""แปลงตัวเลขในไฟล์ Word เป็นเลขไทย ตอนส่งไฟล์ให้ผู้ใช้ (ตั้งค่า School.thai_digits)

แก้เฉพาะข้อความใน <w:t> ของเนื้อหา หัว/ท้ายกระดาษ ไม่แตะค่าโครงสร้าง (ขนาด ระยะ รหัสสไตล์)
"""
import io
import re
import zipfile

_TH = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")
_WT = re.compile(rb"(<w:t(?:\s[^>]*)?>)([^<]*)(</w:t>)")
_PARTS = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def to_thai(text: str) -> str:
    return (text or "").translate(_TH)


def convert_docx(data: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for it in src.infolist():
            raw = src.read(it.filename)
            if _PARTS.match(it.filename):
                raw = _WT.sub(lambda m: m.group(1) + m.group(2).decode("utf8").translate(_TH).encode("utf8")
                              + m.group(3), raw)
            dst.writestr(it, raw)
    return out.getvalue()


def maybe_thai_digits(data: bytes) -> bytes:
    """แปลงเมื่อโรงเรียนที่ล็อกอินเปิดตัวเลือกเลขไทยไว้ อ่านไม่ได้ก็ส่งไฟล์เดิม"""
    try:
        from app.tenancy import current_school_id, session_for
        from app import models as m
        sid = current_school_id.get()
        if not sid:
            return data
        with session_for(sid) as s:
            sc = s.query(m.School).first()
            on = bool(sc and getattr(sc, "thai_digits", False))
        return convert_docx(data) if on else data
    except Exception:
        return data
