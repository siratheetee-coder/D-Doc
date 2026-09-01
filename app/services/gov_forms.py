# -*- coding: utf-8 -*-
"""
gov_forms.py - กรอกข้อมูลลงแบบฟอร์มราชการต้นฉบับ (.docx) โดยคงเลย์เอาต์เป๊ะ
วิธีทำ: เปิดไฟล์แม่แบบที่ฝังไว้ (app/data/forms/*) แล้ว "แทรกค่า" ต่อท้าย run ที่รู้ตำแหน่ง
- ใบลา: leave_form.docx (แบบ ก.พ. ป่วย/คลอดบุตร/กิจส่วนตัว)
ครูพิมพ์รายละเอียดในระบบ -> ระบบเติมลงแม่แบบให้ -> ดาวน์โหลดไปพิมพ์/เซ็น
"""
import copy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.database import get_data_dir
from app.thai_utils import _THAI_MONTHS

_FORM_DIR = Path(__file__).resolve().parent.parent / "data" / "forms"
CHK = "✓"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _ins_after(run, text):
    """แทรก run ใหม่ (คัดลอกฟอนต์/ขนาดจาก run เดิม) ต่อท้าย run ที่ให้มา พร้อมข้อความ text"""
    new_r = copy.deepcopy(run._element)
    # ล้างเนื้อหาเดิมใน clone (ข้อความ/แท็บ/สัญลักษณ์/ขึ้นบรรทัด) เหลือแต่ rPr (ฟอนต์)
    for tag in ("w:t", "w:tab", "w:sym", "w:br", "w:cr"):
        for el in new_r.findall(qn(tag)):
            new_r.remove(el)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    new_r.append(t)
    run._element.addnext(new_r)
    return new_r


def _fill(p, pairs):
    """แทรกหลายค่าในย่อหน้าเดียว: pairs = [(run_index, text), ...]
    ต้องแทรกจาก index มาก -> น้อย เพื่อไม่ให้การแทรกก่อนหน้าเลื่อน index ที่เหลือ"""
    for idx, text in sorted(pairs, key=lambda x: -x[0]):
        try:
            _ins_after(p.runs[idx], text)
        except Exception:
            pass


def _dparts(dt):
    """คืน (วัน, ชื่อเดือนไทย, ปีพ.ศ.) จาก datetime หรือ ('','','')"""
    if not dt:
        return "", "", ""
    return str(dt.day), _THAI_MONTHS[dt.month], str(dt.year + 543)


# normalize ชนิดลา รับได้ทั้งคีย์ทะเบียน (sick/personal/maternity) และป้ายไทย (ลาป่วย/ลากิจ...)
_LEAVE_NORM = {
    "sick": "sick", "ป่วย": "sick", "ลาป่วย": "sick",
    "personal": "personal", "กิจ": "personal", "กิจส่วนตัว": "personal",
    "ลากิจ": "personal", "ลากิจส่วนตัว": "personal",
    "maternity": "maternity", "คลอด": "maternity", "คลอดบุตร": "maternity",
    "ลาคลอด": "maternity", "ลาคลอดบุตร": "maternity",
}
# ชนิดลา -> ป่วย=ย่อหน้า9 · กิจส่วนตัว=10 · คลอดบุตร=11 (เช็กบ็อกซ์อยู่ run2)
_LEAVE_PARA = {"sick": 9, "personal": 10, "maternity": 11}
_LEAVE_LABEL = {"sick": "ป่วย", "personal": "กิจส่วนตัว", "maternity": "คลอดบุตร"}


def render_leave_official(school, person, record, approver=None, write_date=None) -> str:
    """กรอกใบลา (แบบ ก.พ.) จากไฟล์แม่แบบ คืน path .docx
    approver: Person ผอ. (มี .name) ถ้าอนุมัติแล้ว -> ติ๊ก 'อนุญาต' + ใส่ชื่อ/ตำแหน่ง/วันที่ ผอ."""
    doc = Document(str(_FORM_DIR / "leave_form.docx"))
    P = doc.paragraphs

    name = (person.name if person else "") or ""
    position = (getattr(person, "position", "") or "ครู")
    sch = school.name or ""
    addressee = ("ผู้อำนวยการ" + sch) if sch else (
        getattr(school, "director_position", "") or "ผู้อำนวยการโรงเรียน")

    typ_norm = _LEAVE_NORM.get((record.leave_type or "").strip(), "personal")
    typ_label = _LEAVE_LABEL[typ_norm]

    wd = write_date or getattr(record, "created_at", None) or getattr(record, "submitted_at", None)
    wdd, wmon, wyy = _dparts(wd)
    sd_d, sd_m, sd_y = _dparts(record.start_date)
    ed_d, ed_m, ed_y = _dparts(record.end_date)
    days = f"{(record.days or 0):g}"
    reason = (record.reason or "").strip()
    contact = (record.contact or "").strip()

    wmon_num = str(wd.month) if wd else ""

    # ---- หัวเอกสาร ----
    _fill(P[2], [(2, "  " + sch)])                              # เขียนที่
    _fill(P[3], [(1, " " + wdd), (4, " " + wmon), (9, " " + wyy)])  # วันที่ เดือน พ.ศ.
    _fill(P[4], [(1, "ขอลา" + typ_label)])                     # เรื่อง
    _fill(P[5], [(1, addressee)])                              # เรียน
    _fill(P[7], [(2, name), (5, position)])                    # ข้าพเจ้า/ตำแหน่ง
    _fill(P[8], [(5, sch)])                                    # สังกัด

    # ---- ชนิดการลา (ติ๊กในกล่อง run2) + เหตุผล (run5, เฉพาะป่วย/กิจ) ----
    # ติ๊กโดย "แทนที่อักขระกล่องเดิม" ด้วยเครื่องหมายถูก ไม่แทรก run ใหม่
    # (การแทรกจะเพิ่มความกว้าง ดันคำว่า 'เนื่องจาก' ไปชิดขอบ เหตุผลเลยล้นหน้า)
    sel_para = _LEAVE_PARA[typ_norm]
    try:
        box_run = P[sel_para].runs[2]
        for sym in box_run._element.findall(qn("w:sym")):   # ล้างกล่อง Wingdings เดิม
            box_run._element.remove(sym)
        box_run.text = CHK
    except Exception:
        pass
    if reason and sel_para in (9, 10):
        _fill(P[sel_para], [(5, " " + reason)])

    # ---- ช่วงวันลา + จำนวนวัน ----
    _fill(P[12], [(1, " " + sd_d), (3, " " + sd_m), (5, " " + sd_y),
                  (8, " " + ed_d), (10, " " + ed_m), (12, " " + ed_y), (16, days)])
    # ---- ที่อยู่ติดต่อระหว่างลา ----
    _fill(P[14], [(15, " " + contact)])

    # ---- ลงชื่อผู้ลา ----
    _fill(P[19], [(1, " " + name + " ")])                      # ( ชื่อ )
    _fill(P[20], [(3, " " + position)])                        # ตำแหน่ง
    _fill(P[21], [(3, " " + wdd), (5, " " + wmon_num), (7, " " + wyy)])  # วันที่ __/__/__

    # ---- คำสั่งอนุญาต + ลงนาม ผอ. (เมื่ออนุมัติแล้ว) ----
    if approver is not None:
        dname = (getattr(approver, "name", "") or "").strip()
        # ติ๊ก 'อนุญาต' (p27: box run ก่อนคำว่า 'อนุญาต') - หา run 'อนุญาต' ตัวแรก
        try:
            rr = P[27].runs
            for k, r in enumerate(rr):
                if r.text == "อนุญาต":
                    _ins_after(rr[k - 1], CHK) if k >= 1 else None
                    break
        except Exception:
            pass
        # ชื่อ ผอ. ในวงเล็บ (คอลัมน์ขวาล่าง p29)
        try:
            rr = P[29].runs
            for k, r in enumerate(rr):
                if r.text == "(":
                    _ins_after(rr[k], " " + dname + " ")
                    break
        except Exception:
            pass
        # ตำแหน่ง ผอ. (p30)
        try:
            rr = P[30].runs
            for k, r in enumerate(rr):
                if r.text == "ตำแหน่ง":
                    _ins_after(rr[k], " " + (getattr(school, "director_position", "") or "ผู้อำนวยการโรงเรียน"))
                    break
        except Exception:
            pass

    # ตัดย่อหน้าว่างท้ายเอกสาร (แม่แบบเว้นไว้เต็มหน้าพอดี) กันข้อความที่เติมดันตกหน้า 2
    for p in reversed(doc.paragraphs):
        if p.text.strip() == "":
            p._element.getparent().remove(p._element)
        else:
            break

    out = get_data_dir() / "documents"; out.mkdir(exist_ok=True)
    path = out / (_safe(f"ใบลา_{name}_{getattr(record,'id','')}") + ".docx")
    doc.save(str(path))
    return str(path)
