# -*- coding: utf-8 -*-
"""
lesson_set.py - ชุดแผนการสอน 2 แบบ (แนบทีละแผน / แนบทั้งหน่วย)

ทั้งสองแบบใช้แถว LessonUnit เป็น "ไฟล์ 1 ไฟล์ + บันทึกหลังสอน 1 ใบ" เหมือนกัน ต่างกันที่ความหมาย
  plan  แถว = 1 แผน   seq = แผนที่ (นับต่อกันทั้งชุด) หน่วยที่สังกัดอยู่ที่ unit_no / unit_name
  unit  แถว = 1 หน่วย seq = หน่วยที่ plan_count = จำนวนแผนในไฟล์ (ไม่บังคับ ใช้ไล่เลขแผน)
แผนที่ส่งก่อนมีสองแบบ (mode ว่าง) ถือเป็นแบบทั้งหน่วย เพราะเดิมระบบให้แนบไฟล์ละหน่วย

เจ้าของขอให้บันทึกหลังสอนทุกใบบอกชัดว่าเป็นของแผนไหน หน่วยไหน
พิมพ์รวมเป็นเล่มแล้วจะได้ไม่ปนกัน
"""

EDITABLE = ("draft", "revise")


def is_plan_mode(plan) -> bool:
    return (getattr(plan, "mode", "") or "") == "plan"


def mode_label(plan) -> str:
    return "แนบทีละแผน" if is_plan_mode(plan) else "แนบทั้งหน่วย"


def can_edit(plan) -> bool:
    """ครูแก้ชุดแผนได้เฉพาะตอนยังไม่ส่ง หรือถูกส่งกลับให้แก้"""
    return (getattr(plan, "status", "") or "") in EDITABLE


def rows(plan) -> list:
    return list(getattr(plan, "units_rows", None) or [])


def renumber(plan) -> None:
    """เรียงเลขใหม่หลังเพิ่ม/ลบ: แบบทีละแผนเรียงตามหน่วยแล้วตามลำดับเดิม เลขแผนต่อกันทั้งชุด"""
    rs = rows(plan)
    if is_plan_mode(plan):
        rs.sort(key=lambda r: (r.unit_no or 0, r.seq or 0, r.id or 0))
    else:
        rs.sort(key=lambda r: (r.seq or 0, r.id or 0))
    for i, r in enumerate(rs, 1):
        r.seq = i


def groups(plan) -> list[dict]:
    """แบบทีละแผน: จัดกลุ่มแผนตามหน่วย [{no, name, rows, hours}]"""
    out: dict[int, dict] = {}
    for r in sorted(rows(plan), key=lambda r: (r.unit_no or 0, r.seq or 0)):
        g = out.setdefault(r.unit_no or 0, {"no": r.unit_no or 0, "name": "", "rows": [], "hours": 0.0})
        g["name"] = g["name"] or (r.unit_name or "").strip()
        g["rows"].append(r)
        g["hours"] += float(r.hours or 0)
    return list(out.values())


def unit_ranges(plan) -> dict:
    """แบบทั้งหน่วย: {row.id: (แผนแรก, แผนสุดท้าย)} นับต่อกันข้ามหน่วย

    หน่วยไหนไม่กรอกจำนวนแผน หน่วยนั้นและหน่วยถัดไปไล่เลขไม่ได้ จึงไม่ขึ้นเลขแผน
    ดีกว่าขึ้นเลขที่ผิด
    """
    out, n, broken = {}, 0, False
    for r in sorted(rows(plan), key=lambda r: r.seq or 0):
        c = getattr(r, "plan_count", None) or 0
        if c <= 0:
            broken = True
            continue
        if not broken:
            out[getattr(r, "id", None)] = (n + 1, n + c)
        n += c
    return out


def range_text(rng) -> str:
    if not rng:
        return ""
    a, b = rng
    return f"แผนที่ {a}" if a == b else f"แผนที่ {a} ถึง {b}"


def row_title(plan, row) -> str:
    """หัวบันทึกหลังสอน บอกว่าเป็นของแผนไหน หน่วยไหน"""
    if is_plan_mode(plan):
        head = f"แผนที่ {row.seq}"
        if (row.name or "").strip():
            head += f" เรื่อง {row.name.strip()}"
        if getattr(row, "unit_no", None):
            head += f" หน่วยที่ {row.unit_no}"
            if (getattr(row, "unit_name", "") or "").strip():
                head += f" {row.unit_name.strip()}"
        return head
    head = f"หน่วยที่ {row.seq}"
    if (row.name or "").strip():
        head += f" {row.name.strip()}"
    rt = range_text(unit_ranges(plan).get(getattr(row, "id", None)))
    return head + (f" ({rt})" if rt else "")


def recorded(row) -> bool:
    g = lambda k: getattr(row, k, "") or ""
    return bool(getattr(row, "taught_at", None) or (g("k_text") or g("p_text") or g("a_text")
                                                     or g("problem") or g("suggestion")).strip())


def progress(plan) -> tuple[int, int, str]:
    rs = rows(plan)
    return sum(1 for r in rs if recorded(r)), len(rs), ("แผน" if is_plan_mode(plan) else "หน่วย")


def ready_to_send(plan) -> str:
    """คืนข้อความเหตุผลที่ยังส่งไม่ได้ ว่าง = ส่งได้"""
    rs = rows(plan)
    if not rs:
        return "ยังไม่มี" + ("แผน" if is_plan_mode(plan) else "หน่วย") + " เพิ่มก่อนแล้วค่อยส่ง"
    if any(not r.file_blob for r in rs):
        return "ยังมีรายการที่ไม่ได้แนบไฟล์"
    return ""
