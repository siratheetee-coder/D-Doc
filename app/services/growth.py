"""
ภาวะโภชนาการส่วนกลาง (น้ำหนัก/ส่วนสูง) ผูกทะเบียนนักเรียนกลางโดยตรง
ใช้ร่วมกัน 3 ที่: หน้ากรอกในทะเบียนนักเรียน, หน้าภาวะโภชนาการ (อาหารกลางวัน), สมุดพก ปพ.6
จัดกลุ่มตามเกณฑ์กรมอนามัยผ่าน growth_ref.classify_all (pure function)
"""
from datetime import datetime

from app.models import Student, StudentMeasure
from app.services.growth_ref import classify_all, WH_LABELS, HA_LABELS, WA_LABELS
from app.thai_utils import parse_be_date, SCHOOL_LEVELS

TERMS = (1, 2)

# น้ำหนักตามเกณฑ์ส่วนสูง: สมส่วน (index 2) = ดีที่สุด · ยิ่งห่างยิ่งเสี่ยง
_WH_ORDER = {lbl: i for i, lbl in enumerate(WH_LABELS)}
_WH_RISK = {"ผอม", "ค่อนข้างผอม", "เริ่มอ้วน", "อ้วน"}   # กลุ่มเฝ้าระวัง


def current_academic_year() -> int:
    """ปีการศึกษาปัจจุบัน (พ.ศ.) - เปิดเทอม พ.ค. ถึง มี.ค."""
    now = datetime.now()
    y = now.year + 543
    return y if now.month >= 4 else y - 1


def measure_result(student, m):
    """จัดกลุ่มภาวะโภชนาการของการชั่ง 1 ครั้ง (คืน dict ผล + อายุ · None ถ้าข้อมูลไม่พอ)"""
    if not m or not m.weight or not m.height:
        return None
    return classify_all(student.sex, student.birthdate, m.weight, m.height, m.date)


def wh_trend(res):
    """เทียบน้ำหนัก/ส่วนสูง เทอม 1 -> เทอม 2 : up=ดีขึ้น / down=แย่ลง / same=คงที่ / None=ข้อมูลไม่พอ"""
    r1, r2 = res.get(1), res.get(2)
    if not (r1 and r2 and r1.get("wh") in _WH_ORDER and r2.get("wh") in _WH_ORDER):
        return None
    d1 = abs(_WH_ORDER[r1["wh"]] - 2)
    d2 = abs(_WH_ORDER[r2["wh"]] - 2)
    return "up" if d2 < d1 else "down" if d2 > d1 else "same"


def measures_for(db, student_id, year) -> dict:
    """คืน {term: StudentMeasure} ของนักเรียนคนหนึ่งในปีที่ระบุ"""
    rows = (db.query(StudentMeasure)
            .filter(StudentMeasure.student_id == student_id, StudentMeasure.year == year).all())
    return {m.term: m for m in rows}


def set_measure(db, student_id, year, term, weight, height, date):
    """บันทึก/แก้ไขการชั่ง 1 ครั้ง (upsert ตาม student_id+year+term) - คืน StudentMeasure"""
    m = (db.query(StudentMeasure)
         .filter(StudentMeasure.student_id == student_id,
                 StudentMeasure.year == year, StudentMeasure.term == term).first())
    if not m:
        m = StudentMeasure(student_id=student_id, year=year, term=term)
        db.add(m)
    m.date = date
    m.weight = weight or 0.0
    m.height = height or 0.0
    db.commit()
    return m


def _rows(db, year):
    """สร้างแถวต่อคน: {s: Student, m: {term: measure}, res: {term: result}, trend} จากทะเบียนกลาง"""
    order = {lv: i for i, lv in enumerate(SCHOOL_LEVELS)}
    students = db.query(Student).all()
    # โหลดการชั่งทั้งปีทีเดียว กันคิวรีต่อคน
    measures = (db.query(StudentMeasure).filter(StudentMeasure.year == year).all())
    by_student = {}
    for m in measures:
        by_student.setdefault(m.student_id, {})[m.term] = m
    rows = []
    for s in students:
        ms = by_student.get(s.id, {})
        res = {t: measure_result(s, ms.get(t)) for t in TERMS}
        rows.append({"s": s, "m": ms, "res": res, "trend": wh_trend(res)})
    rows.sort(key=lambda r: (order.get((r["s"].level or "").strip(), 99),
                             (r["s"].level or ""), r["s"].name or ""))
    return rows


def build_ctx(db, year):
    """บริบทสำหรับ growth.html (สรุป + เฝ้าระวัง + ตารางแยกชั้น) จากทะเบียนกลาง ปีที่ระบุ"""
    order = {lv: i for i, lv in enumerate(SCHOOL_LEVELS)}
    rows = _rows(db, year)
    wh_count = {k: 0 for k in WH_LABELS}
    ha_count = {k: 0 for k in HA_LABELS}
    wa_count = {k: 0 for k in WA_LABELS}
    watch = []
    for r in rows:
        latest = r["res"].get(2) or r["res"].get(1)
        if not latest:
            continue
        if latest.get("wh") in wh_count:
            wh_count[latest["wh"]] += 1
        if latest.get("ha") in ha_count:
            ha_count[latest["ha"]] += 1
        if latest.get("wa") in wa_count:
            wa_count[latest["wa"]] += 1
        if latest.get("wh") in _WH_RISK:
            r1w = (r["res"].get(1) or {}).get("wh")
            r2w = (r["res"].get(2) or {}).get("wh")
            watch.append({"s": r["s"], "wh": latest["wh"], "trend": r["trend"],
                          "repeat": (r1w in _WH_RISK and r2w in _WH_RISK)})
    assessed = sum(wh_count.values())
    by_class = []
    for r in rows:
        lv = (r["s"].level or "").strip() or "ไม่ระบุชั้น"
        if not by_class or by_class[-1]["level"] != lv:
            by_class.append({"level": lv, "rows": []})
        by_class[-1]["rows"].append(r)
    watch.sort(key=lambda w: (not w["repeat"], order.get((w["s"].level or "").strip(), 99)))
    return {
        "year": year, "rows": rows, "by_class": by_class, "watch": watch,
        "wh_labels": WH_LABELS, "ha_labels": HA_LABELS, "wa_labels": WA_LABELS,
        "wh_count": wh_count, "ha_count": ha_count, "wa_count": wa_count, "assessed": assessed,
    }


def report_data(db, year):
    """นับภาวะโภชนาการ (น้ำหนักตามเกณฑ์ส่วนสูง) จากผลเทอมล่าสุด แยกตามชั้นและเพศ (สำหรับรายงาน Word)"""
    cats = WH_LABELS
    rows = _rows(db, year)
    totals = {c: 0 for c in cats}
    sex_counts = {"ชาย": {c: 0 for c in cats}, "หญิง": {c: 0 for c in cats}}
    class_counts, cur, assessed = [], None, 0
    for r in rows:
        s = r["s"]
        res = r["res"].get(2) or r["res"].get(1)
        if not res or res.get("wh") not in totals:
            continue
        cat = res["wh"]
        lv = (s.level or "").strip() or "ไม่ระบุชั้น"
        if cur is None or cur["level"] != lv:
            cur = {"level": lv, "counts": {c: 0 for c in cats}, "total": 0}
            class_counts.append(cur)
        cur["counts"][cat] += 1
        cur["total"] += 1
        totals[cat] += 1
        assessed += 1
        sx = "ชาย" if s.sex == "M" else "หญิง" if s.sex == "F" else None
        if sx:
            sex_counts[sx][cat] += 1
    return cats, class_counts, sex_counts, totals, assessed


def available_years(db):
    """ปีที่มีข้อมูลการชั่ง + ปีปัจจุบัน (ใหม่->เก่า) สำหรับตัวเลือกปี"""
    ys = {y for (y,) in db.query(StudentMeasure.year).distinct().all() if y}
    ys.add(current_academic_year())
    return sorted(ys, reverse=True)
