# -*- coding: utf-8 -*-
"""ด่านสิทธิ์ของหน้าส่วนกลาง (หน้าที่ไม่ได้อยู่ในงานใดงานหนึ่ง)

เจ้าของเจอ: ไอดีครูเปิดหน้าผู้ขาย ทะเบียนเลขหนังสือ โครงการ ข้อมูลนักเรียน ตั้งค่าโรงเรียน
และสำรองข้อมูลได้ เพราะการกันสิทธิ์เดิมดูแค่ "งาน 6 งาน" หน้าที่ไม่อยู่ในงานไหนจึงเปิดได้ทุกคน
ที่นี่กำหนดว่าหน้าส่วนกลางแต่ละหน้า ต้องมีสิทธิ์งานไหนถึงจะเข้าได้ ใช้ทั้ง GET และ POST

ไอดีหลักและ ผอ. ไม่ผ่านด่านนี้ (ไอดีหลักเห็นทุกอย่าง ผอ. ดูได้ทุกงานแบบอ่านอย่างเดียว)
"""

# เฉพาะไอดีหลัก: ตั้งค่า สำรอง/นำเข้าข้อมูล ผู้ใช้ ซื้อแพ็กเกจ
OWNER_ONLY = ("/settings", "/backup", "/users", "/checkout", "/trial-limit", "/summary.xlsx")

# หน้าส่วนกลาง -> งานที่มีสิทธิ์อย่างใดอย่างหนึ่งแล้วเข้าได้
SHARED = {
    # ปฏิทินโรงเรียนใช้ร่วมกันระหว่างงานอาหารกลางวันกับงานวิชาการ (นับวันทำการ)
    "/settings/calendar": {"lunch", "academic"},
    "/vendors": {"procurement", "finance", "lunch"},
    "/docnos": {"admin", "procurement", "finance", "hr", "lunch"},
    "/projects": {"finance", "procurement"},
    "/project-reports": {"finance", "procurement"},
    "/masters": {"procurement", "finance", "hr"},
    "/students": {"lunch", "finance", "hr"},
    "/general": {"admin", "procurement", "finance", "hr", "lunch"},
    "/materials-cards.docx": {"procurement"},
    "/textbooks": {"procurement"},
    "/catalog": {"procurement"},
}

# ไอดีครู (ผูกกับรายชื่อบุคลากร) เข้าได้เฉพาะหน้าเหล่านี้ + งานที่ได้รับสิทธิ์
TEACHER_OK = ("/", "/me", "/home", "/account", "/notices", "/system-updates", "/support", "/guide",
              "/knowledge", "/search", "/ai", "/logout", "/approvals/doc", "/approvals/result",
              "/approvals/preview", "/email/stop", "/privacy", "/landing", "/login")


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + "/") or (prefix.endswith((".docx", ".xlsx")) and path == prefix)


def denied(path, acc) -> str:
    """คืนเหตุผลที่ปฏิเสธ (ข้อความสั้น) หรือ '' ถ้าเข้าได้

    acc = ข้อมูลบัญชีจาก get_account_access (is_owner, is_director, modules, person_id)
    """
    if acc.get("is_owner") or acc.get("is_director"):
        return ""
    from app.modules import module_for_path, parse_modules
    p = (path or "/").rstrip("/") or "/"
    mine = set(parse_modules(acc.get("modules") or ""))
    # ไอดีครู: สิทธิ์งานวิชาการใช้กับหน้าของวิชาการเท่านั้น ไม่เปิดหน้าส่วนกลางให้
    shared_mine = mine - {"academic"} if acc.get("person_id") else mine
    if _under(p, "/general/assembly"):
        return ""   # ครูประจำชั้นเช็คเข้าแถว: route กันเองให้เห็นเฉพาะห้องที่ประจำชั้น
    for pre, need in SHARED.items():
        if _under(p, pre):
            has = mine if pre == "/settings/calendar" else shared_mine   # ครูดูปฏิทินได้ (บันทึกไม่ได้ กันที่ route)
            return "" if has & need else "บัญชีนี้ยังไม่ได้รับสิทธิ์งานที่ใช้หน้านี้"
    if any(_under(p, x) for x in OWNER_ONLY):
        return "หน้านี้สำหรับไอดีหลักของโรงเรียนเท่านั้น"
    if acc.get("person_id"):
        # ไอดีครู: นอกจากงานที่ได้รับสิทธิ์ (ด่านงานใน main.py ตรวจแล้ว) เปิดได้เฉพาะหน้าส่วนตัว
        if module_for_path(p):
            return ""
        if p == "/" or any(_under(p, x) for x in TEACHER_OK if x != "/"):
            return ""
        return "ไอดีครูเข้าได้เฉพาะงานที่ได้รับสิทธิ์และหน้าส่วนตัว"
    return ""
