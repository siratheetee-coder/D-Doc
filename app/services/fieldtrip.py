# -*- coding: utf-8 -*-
"""
fieldtrip.py - กติกาการพานักเรียนไปนอกสถานศึกษา (ทัศนศึกษา)

ยึดตาม ระเบียบกระทรวงศึกษาธิการ ว่าด้วยการพานักเรียน และนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562
(ราชกิจจานุเบกษา เล่ม 137 ตอนพิเศษ 120 ง 22 พฤษภาคม 2563) ซึ่งยกเลิกฉบับ พ.ศ. 2548
"""
import json
import math
from datetime import datetime

REG_NAME = "ระเบียบกระทรวงศึกษาธิการ ว่าด้วยการพานักเรียน และนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562"

# ข้อ 5 ประเภท + ข้อ 8 ผู้มีอำนาจอนุญาต
TRIP_TYPES = {
    "day": {"label": "ไปนอกสถานศึกษาไม่พักแรม", "approver": "หัวหน้าสถานศึกษา"},
    "overnight": {"label": "ไปนอกสถานศึกษาพักแรม", "approver": "ผู้อำนวยการสำนักงานเขตพื้นที่การศึกษา"},
    "abroad": {"label": "ไปนอกราชอาณาจักร", "approver": "หัวหน้าส่วนราชการหรือผู้ได้รับมอบหมาย"},
}

STATUS = {
    "draft": "ร่าง",
    "requested": "ยื่นขออนุญาตแล้ว",
    "approved": "ได้รับอนุญาต",
    "done": "เดินทางกลับแล้ว",
    "reported": "รายงานผลแล้ว",
}

MAX_PER_ASSISTANT = 30      # ข้อ 7(3) ผู้ช่วยผู้ควบคุม 1 คน ต่อนักเรียนไม่เกิน 30 คน
MIN_DAYS_BEFORE = 15        # ข้อ 9 ยื่นก่อนวันเดินทางไม่น้อยกว่า 15 วัน

# ข้อที่ต้องจัดให้มีก่อนเดินทาง (ข้อ 7) - ให้ติ๊กยืนยัน
CHECKLIST = [
    ("route_vehicle", "เลือกเส้นทาง ยานพาหนะมั่นคงแข็งแรง และพนักงานขับรถมีความรู้ความชำนาญ", "ข้อ 7(4)"),
    ("signage", "ป้ายระบุโครงการ กิจกรรม และสถานศึกษา ติดด้านข้างรถ + หมายเลขรถด้านหน้าและด้านหลัง", "ข้อ 7(5)"),
    ("cooperation", "ขอความร่วมมือ/คำแนะนำจากหน่วยงานที่เกี่ยวข้องเท่าที่จำเป็น", "ข้อ 7(5)"),
    ("first_aid", "อุปกรณ์ปฐมพยาบาลเบื้องต้นประจำรถ และดูแลนักเรียนที่มีโรคประจำตัวเป็นพิเศษ", "ข้อ 7(6)"),
    ("insurance", "ประกันภัยการเดินทางแก่นักเรียน (เว้นแต่มีประกันที่คุ้มครองอยู่แล้ว)", "ข้อ 7(7)"),
    ("contact", "ช่องทางติดต่อสื่อสารและหมายเลขโทรศัพท์หน่วยงานที่เกี่ยวข้อง", "ข้อ 10(3)"),
]
OVERNIGHT_CHECKLIST = [
    ("orientation", "ปฐมนิเทศเมื่อถึงสถานที่จัดกิจกรรม", "ข้อ 12(1)"),
    ("separate_rooms", "สถานที่พักแยกชาย - หญิง เป็นส่วนสัด", "ข้อ 12(2)"),
    ("security", "ระบบดูแลรักษาความปลอดภัยตลอดช่วงเวลาจัดกิจกรรม", "ข้อ 12(3)"),
    ("medic", "ผู้มีความรู้ด้านการรักษาพยาบาล และรถรับ-ส่งกรณีฉุกเฉิน", "ข้อ 12(4)"),
]

COST_BASIS = {"student": "ต่อนักเรียน", "person": "ต่อคน (นักเรียน+ครู)", "lump": "เหมาจ่าย"}

_FEMALE_PREFIX = ("นาง", "น.ส.", "ด.ญ.", "เด็กหญิง", "Miss", "Mrs", "Ms")


def is_female_name(name: str) -> bool:
    """เดาเพศจากคำนำหน้าชื่อ (นาง/นางสาว/น.ส.) - ใช้เตือนเรื่องครูสตรีเท่านั้น"""
    return (name or "").strip().startswith(_FEMALE_PREFIX)


def checklist_items(trip) -> list:
    return CHECKLIST + (OVERNIGHT_CHECKLIST if trip.trip_type == "overnight" else [])


def checklist_done(trip) -> set:
    try:
        return set(json.loads(trip.checklist or "[]"))
    except (ValueError, TypeError):
        return set()


def counts(trip) -> dict:
    n_stu = len(trip.students)
    n_staff = len(trip.staff) + (1 if trip.controller_id else 0)
    return {"students": n_stu, "assistants": len(trip.staff), "staff": n_staff,
            "people": n_stu + n_staff,
            "female_students": sum(1 for s in trip.students if s.sex == "F"),
            "consent_yes": sum(1 for s in trip.students if s.consent == "yes"),
            "consent_no": sum(1 for s in trip.students if s.consent == "no"),
            "consent_wait": sum(1 for s in trip.students if not s.consent)}


def cost_amount(cost, c: dict) -> float:
    heads = {"student": c["students"], "person": c["people"], "lump": 1}.get(cost.basis, 1)
    return round((cost.rate or 0) * heads * (cost.times or 0), 2)


def total_cost(trip) -> float:
    c = counts(trip)
    return round(sum(cost_amount(x, c) for x in trip.costs), 2)


def approver_title(trip, school) -> str:
    """เรียน ... ในแบบขออนุญาต/แบบรายงาน (ข้อ 8)"""
    if (trip.request_to or "").strip():
        return trip.request_to.strip()
    if trip.trip_type == "day":
        name = (school.name or "").strip()
        return "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else "ผู้อำนวยการโรงเรียน"
    if trip.trip_type == "overnight":
        area = (school.area_office or "").strip()
        return "ผู้อำนวยการ" + area if area else "ผู้อำนวยการสำนักงานเขตพื้นที่การศึกษา"
    return ""


def warnings(trip, today: datetime | None = None) -> list:
    """ข้อที่ยังไม่ครบตามระเบียบ -> [(ระดับ, ข้อความ)]"""
    out = []
    c = counts(trip)
    today = today or datetime.now()
    if not trip.controller_id:
        out.append(("error", "ยังไม่ได้เลือกผู้ควบคุม (ข้อ 7(3) ให้หัวหน้าสถานศึกษาหรือผู้ได้รับมอบหมาย 1 คน เป็นผู้ควบคุม)"))
    need = math.ceil(c["students"] / MAX_PER_ASSISTANT) if c["students"] else 0
    if c["assistants"] < need:
        out.append(("error", f"ผู้ช่วยผู้ควบคุมไม่พอ: นักเรียน {c['students']} คน ต้องมีอย่างน้อย {need} คน "
                             f"(ข้อ 7(3) 1 คน ต่อนักเรียนไม่เกิน {MAX_PER_ASSISTANT} คน) ตอนนี้มี {c['assistants']} คน"))
    if c["female_students"]:
        staff_names = [s.name for s in trip.staff] + ([trip.controller.name] if trip.controller else [])
        if not any(is_female_name(n) for n in staff_names):
            out.append(("warn", f"มีนักเรียนหญิง {c['female_students']} คน แต่ยังไม่มีครูสตรีควบคุมไปด้วย "
                                "(ข้อ 7(3) ให้มีครูสตรีควบคุมไปด้วยตามความเหมาะสม)"))
    if trip.depart_at:
        ref = trip.request_date or today
        days = (trip.depart_at.date() - ref.date()).days
        if days < MIN_DAYS_BEFORE and trip.status in ("draft", "requested"):
            out.append(("warn", f"ยื่นขออนุญาตก่อนเดินทาง {days} วัน ไม่ถึง {MIN_DAYS_BEFORE} วัน "
                                "(ข้อ 9 ต้องชี้แจงเหตุผลความจำเป็นในหนังสือขออนุญาต)"))
    if trip.depart_at and trip.return_at and trip.return_at < trip.depart_at:
        out.append(("error", "วันกลับถึงสถานศึกษาอยู่ก่อนวันออกเดินทาง"))
    if trip.trip_type == "overnight" and not (trip.lodging or "").strip():
        out.append(("warn", "พักแรมแต่ยังไม่ได้ระบุสถานที่พักค้าง"))
    if c["consent_no"]:
        out.append(("warn", f"ผู้ปกครองไม่อนุญาต {c['consent_no']} คน - ต้องไม่พานักเรียนกลุ่มนี้ไป (ข้อ 6) "
                            "ลบออกจากรายชื่อก่อนยื่นขออนุญาต"))
    missing = [label for key, label, _ in checklist_items(trip) if key not in checklist_done(trip)]
    if missing:
        out.append(("info", f"ยังไม่ได้ยืนยันการเตรียมการ {len(missing)} ข้อ (ข้อ 7/10/12)"))
    return out
