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

COST_BASIS = {"student": "ต่อนักเรียน", "person": "ต่อคน (รวมครู)", "staff": "ต่อครู", "lump": "เหมาจ่าย"}

_FEMALE_PREFIX = ("นาง", "น.ส.", "ด.ญ.", "เด็กหญิง", "Miss", "Mrs", "Ms")


def is_female_name(name: str) -> bool:
    """เดาเพศจากคำนำหน้าชื่อ (นาง/นางสาว/น.ส.) - ใช้เตือนเรื่องครูสตรีเท่านั้น"""
    return (name or "").strip().startswith(_FEMALE_PREFIX)


def checklist_items(trip) -> list:
    return CHECKLIST + BUS_CHECKLIST + (OVERNIGHT_CHECKLIST if trip.trip_type == "overnight" else [])


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
    heads = {"student": c["students"], "person": c["people"], "staff": c["staff"], "lump": 1}.get(cost.basis, 1)
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
    out += safety_warnings(trip)
    missing = [label for key, label, _ in checklist_items(trip) if key not in checklist_done(trip)]
    if missing:
        out.append(("info", f"ยังไม่ได้ยืนยันการเตรียมการ {len(missing)} ข้อ (ระเบียบฯ ข้อ 7/10/12 และ ว 1057)"))
    return out


# ============================================================
# ความปลอดภัยตาม ว 1057 + ค่าใช้จ่ายตาม ว 2983 + ขั้นตอน
# ============================================================
# หนังสือ สพฐ. ด่วนที่สุด ที่ ศธ 04277/ว 1057 ลว. 3 ต.ค. 2567 กำชับแนวทางปฏิบัติในการพานักเรียนไปนอกสถานศึกษา
W1057 = "หนังสือ สพฐ. ที่ ศธ 04277/ว 1057 ลว. 3 ต.ค. 2567"
BUS_CHECKLIST = [
    ("bus_inspect", "รถผ่านการตรวจสภาพจากกรมการขนส่งทางบก (เอกสารรับรองไม่เกิน 30 วัน)", "ว 1057 ข้อ 2.1"),
    ("bus_no_gas", "ไม่ใช้รถที่ติดตั้งระบบจ่ายพลังงานเชื้อเพลิงด้วยแก๊ส", "ว 1057 ข้อ 2.2"),
    ("bus_safety", "รถมีเข็มขัดนิรภัยทุกที่นั่ง ประตูฉุกเฉิน ถังดับเพลิง ค้อนทุบกระจก", "ว 1057 ข้อ 2.3"),
    ("evac_drill", "มีแผนเผชิญเหตุ และผู้ประกอบการฝึกซ้อมแผนให้นักเรียนและครูก่อนออกเดินทาง", "ว 1057 ข้อ 3"),
    ("licensed_contract", "ทำสัญญาเช่ารถกับผู้ได้รับอนุญาตประกอบการขนส่ง รถจดทะเบียนเป็นรถโดยสารสาธารณะ "
                          "มีประกันภัยตามกฎหมาย", "ว 1057 ข้อ 4, 15"),
    ("driver_rest", "ตรวจบันทึกการเดินรถ: พนักงานขับรถพัก และรถหยุดพัก ไม่น้อยกว่า 24 ชม. ก่อนออกเดินทาง",
     "ว 1057 ข้อ 6"),
    ("two_drivers", "เส้นทางขับเกิน 4 ชม. มีพนักงานขับรถ 2 คนสลับกัน (พักไม่น้อยกว่าครึ่งชั่วโมงทุก 4 ชม.)",
     "ว 1057 ข้อ 9"),
    ("route_check", "ตรวจสอบเส้นทางก่อนเดินทาง · ทางภูเขาลาดชันคดเคี้ยวใช้รถชั้นเดียว", "ว 1057 ข้อ 8, 10"),
    ("driver_watch", "ครูผู้ควบคุมอย่างน้อย 2 คน ผลัดกันกำกับดูแลพนักงานขับรถ · นักเรียนคาดเข็มขัดนิรภัย "
                     "· ไม่บรรทุกเกินที่นั่ง", "ว 1057 ข้อ 12-14"),
]

# วิธีจ่าย -> ต้องทำเอกสารที่ไหน
PAY_METHODS = {
    "procure": "จัดซื้อจัดจ้าง",
    "allowance": "เหมาจ่ายนักเรียน",
    "receipt": "จ่ายตามใบเสร็จ",
    "travel": "เบิกค่าเดินทางครู",
}

# ชนิดรายการ + ค่าเริ่มต้น + เพดานตามหนังสือ สพฐ. ที่ ศธ 04002/ว 2983 ลว. 23 พ.ย. 2555
# (แนวทางเงินอุดหนุน ปี 2569 ของ สพฐ. ยังยกหนังสือนี้เป็นหลักเกณฑ์ปัจจุบัน)
# cap = อัตราสูงสุดของช่อง "อัตรา" · proc = ประเภทเรื่องในงานพัสดุ
W2983 = "หนังสือ สพฐ. ที่ ศธ 04002/ว 2983 ลว. 23 พ.ย. 2555"
COST_KINDS = {
    "bus": {"label": "ค่าจ้างเหมาพาหนะรับ-ส่ง", "basis": "lump", "pay": "procure", "proc": "จ้าง",
            "cap": None, "ref": "ว 2983 ข้อ 13 เบิกเท่าที่จ่ายจริง", "hint": "อัตรา = ต่อคัน · ครั้ง = จำนวนคัน"},
    "meal": {"label": "ค่าอาหาร (โรงเรียนจัดให้)", "basis": "person", "pay": "procure", "proc": "จ้าง",
             "cap": 80, "ref": "ว 2983 ข้อ 10 มื้อละไม่เกิน 80 บาท (จำเป็นต้องจัดในสถานที่เอกชน ไม่เกิน 150 บาท)",
             "hint": "อัตรา = ต่อคนต่อมื้อ · ครั้ง = จำนวนมื้อ"},
    "snack": {"label": "ค่าอาหารว่างและเครื่องดื่ม", "basis": "person", "pay": "procure", "proc": "จ้าง",
              "cap": 50, "ref": "ว 2983 ข้อ 6 ไม่เกินมื้อละ 50 บาทต่อคน", "hint": "ครั้ง = จำนวนมื้อ"},
    "allowance": {"label": "ค่าอาหารเหมาจ่ายนักเรียน", "basis": "student", "pay": "allowance",
                  "cap": 240, "ref": "ว 2983 ข้อ 11.2 จัด 2 มื้อ ≤80 · จัด 1 มื้อ ≤160 · ไม่จัด ≤240 บาท/คน/วัน",
                  "hint": "อัตรา = ต่อคนต่อวัน · ครั้ง = จำนวนวัน"},
    "entry": {"label": "ค่าเข้าชมสถานที่แหล่งเรียนรู้", "basis": "student", "pay": "receipt",
              "cap": None, "ref": "ว 2983 ข้อ 7 เบิกเท่าที่จ่ายจริง (ใบเสร็จ)"},
    "lodging": {"label": "ค่าเช่าที่พัก", "basis": "person", "pay": "procure", "proc": "จ้าง",
                "cap": 1200, "ref": "ว 2983 ข้อ 12 ห้องคู่ ≤600 · ห้องเดี่ยว ≤1,200 บาท/คน/วัน",
                "hint": "อัตรา = ต่อคนต่อคืน · ครั้ง = จำนวนคืน"},
    "insurance": {"label": "ค่าประกันภัยการเดินทาง", "basis": "student", "pay": "procure", "proc": "จ้าง",
                  "cap": None, "ref": "ระเบียบฯ 2562 ข้อ 7(7) · ว 2983 ข้อ 17 ค่าใช้จ่ายอื่นที่จำเป็น"},
    "perdiem": {"label": "ค่าเบี้ยเลี้ยงเดินทาง (ครูผู้ควบคุม)", "basis": "staff", "pay": "travel",
                "cap": None, "ref": "ระเบียบฯ 2562 ข้อ 14 · ว 2983 ข้อ 11.1 (หักค่าอาหารที่จัดให้มื้อละ 1 ใน 3)",
                "hint": "อัตรา = ต่อคนต่อวันตามสิทธิ (หักค่าอาหารที่จัดให้แล้ว) · ครั้ง = จำนวนวัน"},
    "other": {"label": "อื่น ๆ (ระบุ)", "basis": "lump", "pay": "procure", "proc": "ซื้อ", "cap": None, "ref": ""},
}


def kind_of(cost) -> dict:
    return COST_KINDS.get(cost.kind or "other", COST_KINDS["other"])


def cost_label(cost) -> str:
    """ชื่อรายการในเอกสาร: ชนิด 'อื่น ๆ' ใช้ข้อความที่ผู้ใช้พิมพ์"""
    k = cost.kind or "other"
    if k == "other" or k not in COST_KINDS:
        return (cost.item or "").strip()
    return COST_KINDS[k]["label"]


def cost_warnings(cost) -> list:
    k = kind_of(cost)
    out = []
    if k.get("cap") and (cost.rate or 0) > k["cap"]:
        out.append(f"อัตรา {cost.rate:,.2f} บาท เกินเพดาน {k['cap']:,} บาท ({k['ref']})")
    if cost.pay_method == "procure" and not cost.vendor_id:
        out.append("ยังไม่ได้เลือกผู้ขาย/ผู้รับจ้าง")
    return out


def procure_groups(trip) -> list:
    """รายการที่ต้องจัดซื้อจัดจ้าง จัดกลุ่มตามผู้ขาย (1 ผู้ขาย = 1 เรื่อง) + เรื่องที่สร้างแล้ว"""
    c = counts(trip)
    groups = {}
    for x in trip.costs:
        if x.pay_method != "procure" or not x.vendor_id:
            continue
        g = groups.setdefault(x.vendor_id, {"vendor_id": x.vendor_id, "vendor": x.vendor, "costs": [],
                                            "total": 0.0, "proc": None})
        g["costs"].append(x)
        g["total"] += cost_amount(x, c)
        if x.procurement_id and x.procurement is not None:
            g["proc"] = x.procurement
    for g in groups.values():
        kinds = {kind_of(x).get("proc", "ซื้อ") for x in g["costs"]}
        g["proc_type"] = "จ้าง" if "จ้าง" in kinds else "ซื้อ"
        g["total"] = round(g["total"], 2)
    return list(groups.values())


def cash_costs(trip) -> list:
    """รายการที่จ่ายเป็นเงินสดระหว่างทาง (ใช้ยืมเงิน): เหมาจ่ายนักเรียน + จ่ายตามใบเสร็จ"""
    return [x for x in trip.costs if x.pay_method in ("allowance", "receipt")]


def safety_warnings(trip) -> list:
    out = []
    c = counts(trip)
    for when, label in ((trip.depart_at, "ออกเดินทาง"), (trip.return_at, "กลับถึง")):
        if when and (when.hour or when.minute) and (when.hour >= 19 or when.hour < 5):
            out.append(("error", f"เวลา{label} {when:%H.%M} น. อยู่ในช่วงกลางคืน "
                                 f"({W1057} ข้อ 11 ห้ามนำนักเรียนออกเดินทางในเวลากลางคืน)"))
    levels = {s.level or "" for s in trip.students}
    if any(lv.startswith("อ.") for lv in levels):
        out.append(("warn", "มีนักเรียนปฐมวัย ต้องมีผู้ปกครองร่วมคณะไปด้วย ห้ามไปคละกับช่วงชั้นอื่น "
                            f"และเลือกสถานที่ใกล้เคียงสถานศึกษา ({W1057} ข้อ 1.1)"))
    elif levels & {"ป.1", "ป.2", "ป.3"}:
        out.append(("info", f"มีนักเรียน ป.1-3 ควรมีผู้ปกครองร่วมคณะ และเลือกสถานที่ใกล้เคียงสถานศึกษา ({W1057} ข้อ 1.2)"))
    if c["students"] and c["staff"] < 2:
        out.append(("warn", f"ครูผู้ควบคุมต้องมีอย่างน้อย 2 คน ผลัดกันกำกับดูแลพนักงานขับรถ ({W1057} ข้อ 12)"))
    for x in trip.costs:
        for w in cost_warnings(x):
            out.append(("warn", f"{cost_label(x) or 'รายการค่าใช้จ่าย'}: {w}"))
    return out


def steps(trip) -> list:
    """แถบขั้นตอน: [(ชื่อ, done/doing/todo, คำอธิบายสั้น, anchor)]"""
    c = counts(trip)
    groups = procure_groups(trip)
    info_ok = bool(trip.title and trip.place and trip.depart_at and trip.return_at)
    people_ok = bool(trip.controller_id and c["students"])
    cost_ok = bool(trip.costs) and not any(cost_warnings(x) for x in trip.costs)
    approved = trip.status in ("approved", "done", "reported")
    made = sum(1 for g in groups if g["proc"])
    need_loan = bool(cash_costs(trip))
    buy_ok = bool(groups or need_loan) and made == len(groups) and (bool(trip.loan_id) or not need_loan)

    def st(done, started=False):
        return "done" if done else ("doing" if started else "todo")
    return [
        ("ข้อมูลการไป", st(info_ok, bool(trip.place)), trip.place or "", "#sec-info"),
        ("คนที่ไป", st(people_ok, bool(c["students"] or trip.controller_id)),
         f"นักเรียน {c['students']} · ครู {c['staff']}", "#sec-people"),
        ("ค่าใช้จ่าย", st(cost_ok, bool(trip.costs)), f"{total_cost(trip):,.0f} บาท", "#sec-cost"),
        ("ขออนุญาต", st(approved, trip.status == "requested"), STATUS.get(trip.status, ""), "#sec-docs"),
        ("จัดจ้าง/ยืมเงิน", st(buy_ok, made > 0 or bool(trip.loan_id)),
         (f"{made}/{len(groups)} เรื่อง" if groups else "") + (" · ยืมเงินแล้ว" if trip.loan_id else ""), "#sec-buy"),
        ("หลังกลับ", st(trip.status == "reported", trip.status == "done"), "", "#sec-report"),
    ]


def next_actions(trip) -> list:
    """สิ่งที่ต้องทำต่อ (สูงสุด 3 ข้อ): [(ข้อความ, ลิงก์)]"""
    c = counts(trip)
    out = []
    if not (trip.place and trip.depart_at):
        out.append(("กรอกสถานที่และวันเดินทาง", "#sec-info"))
    if not trip.controller_id or not c["students"]:
        out.append(("เลือกผู้ควบคุมและนักเรียนที่ไป", "#sec-people"))
    bad = [x for x in trip.costs if cost_warnings(x)]
    if bad:
        out.append((f"แก้รายการค่าใช้จ่ายที่ยังไม่ครบ {len(bad)} รายการ (เพดานอัตรา/ผู้ขาย)", "#sec-cost"))
    if trip.status == "draft" and trip.place and c["students"]:
        out.append(("ดาวน์โหลดแบบขออนุญาต + หนังสือผู้ปกครอง แล้วเปลี่ยนสถานะเป็น \"ยื่นขออนุญาตแล้ว\"", "#sec-docs"))
    for g in procure_groups(trip):
        if not g["proc"]:
            out.append((f"สร้างเรื่อง{g['proc_type']}กับ {g['vendor'].name} ({g['total']:,.2f} บาท)", "#sec-buy"))
        elif g["proc"].status == "ร่าง":
            out.append((f"เติมเลขเอกสาร/ราคาในเรื่อง{g['proc_type']}กับ {g['vendor'].name}",
                        f"/procurement/{g['proc'].id}"))
    if cash_costs(trip) and not trip.loan_id:
        out.append(("สร้างสัญญายืมเงินสำหรับรายการที่จ่ายเป็นเงินสด", "#sec-buy"))
    if trip.status == "done":
        out.append(("กรอกผลการเดินทาง แล้วดาวน์โหลดแบบรายงานผล", "#sec-report"))
    return out[:3]



def travel_costs(trip) -> list:
    """รายการที่เบิกผ่านใบเบิกค่าใช้จ่ายในการเดินทางไปราชการ (แบบ 8708)"""
    return [x for x in trip.costs if x.pay_method == "travel"]


def staff_people(trip) -> list:
    """[(ชื่อ, ตำแหน่ง, หน้าที่)] ผู้ควบคุมก่อน แล้วผู้ช่วย"""
    out = []
    if trip.controller:
        out.append((trip.controller.name, trip.controller.position or "ครู", "ผู้ควบคุม"))
    out += [(s.name, s.position or "ครู", "ผู้ช่วยผู้ควบคุม") for s in trip.staff]
    return out


def proc_mismatch(trip, group) -> list:
    """เรื่องจัดจ้างที่สร้างแล้ว ข้อมูลไม่ตรงกับทัศนศึกษา (หลังแก้หน้าทัศนศึกษา) -> รายการที่ต่าง"""
    proc = group.get("proc")
    if not proc:
        return []
    out = []
    if trip.depart_at and proc.delivery_due_date and proc.delivery_due_date.date() != trip.depart_at.date():
        out.append("วันเดินทาง/วันส่งมอบ")
    if proc.status == "ร่าง" and round(proc.total_amount or 0, 2) != round(group["total"], 2):
        out.append("ยอดเงิน")
    if (proc.project_id or None) != (trip.project_id or None):
        out.append("โครงการ")
    return out
