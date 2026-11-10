# -*- coding: utf-8 -*-
"""หน้าหลักของครู: งานค้างทุกเรื่องในที่เดียว + สถานะแผนการสอน ใบลา ขอไปราชการ

เจ้าของ: เดิมหน้าหลักมีแต่หนังสือราชการ จะรู้สถานะแผนต้องกดเข้าหน้าแผนการสอนก่อน
งานวิชาการ (คะแนน เช็กชื่อ) เจ้าของสั่งให้เก็บไว้หน้างานวิชาการ ไม่ขึ้นที่นี่
"""
from app.services import lesson_set

PLAN_STATUS = {
    "draft": ("ร่าง ยังไม่ส่ง", "gray"),
    "pending": ("รอวิชาการตรวจ", "amber"),
    "director": ("รอ ผอ. อนุมัติ", "blue"),
    "revise": ("ส่งกลับให้แก้", "red"),
    "approved": ("อนุมัติแล้ว", "green"),
    "reviewed": ("ตรวจแล้ว", "green"),
}
REQ_STATUS = {"pending": ("รอหัวหน้าบุคคล", "amber"), "personnel": ("รอ ผอ. อนุมัติ", "blue"), "approved": ("อนุมัติแล้ว", "green"),
              "rejected": ("ไม่อนุมัติ", "red")}


def build(db, pid, *, year=None, letters=None, letter_tasks=0, letter_late=0, letter_pending=0):
    """คืน {stats, todos, plans, requests} ของครูคนนี้

    letters = แถวหนังสือที่ home_dashboard จัดไว้แล้ว (ต่อเข้ารายการงานค้างตามความด่วน)
    """
    from app.models import LessonPlan, LeaveRequest, TravelRequest
    q = db.query(LessonPlan).filter(LessonPlan.person_id == pid)
    if year:
        q = q.filter(LessonPlan.year == year)
    plans = q.order_by(LessonPlan.id.desc()).all()

    todos, rows = [], []
    waiting_plans = after_left = 0
    for p in plans:
        label, tone = PLAN_STATUS.get(p.status or "", ("รอวิชาการตรวจ", "amber"))
        href = f"/academic/lesson-plans/{p.id}/units"
        done = total = 0
        if p.status == "approved":
            done, total = lesson_set.slot_progress(p)
            if total and done < total:
                after_left += total - done
                todos.append(dict(level=2, title=f"บันทึกหลังสอน {p.title}",
                                  note=f"บันทึกแล้ว {done} จาก {total} แผน", tag="ยังไม่ครบ", href=href, icon="ic-edit"))
        elif p.status == "revise":
            waiting_plans += 1
            why = (p.director_comment or p.comment or "").strip()
            todos.append(dict(level=0, title=f"แผนถูกส่งกลับให้แก้ {p.title}",
                              note=why or "เปิดดูความเห็นแล้วแก้ไขก่อนส่งอีกครั้ง", tag="ต้องแก้", href=href, icon="ic-alert"))
        elif p.status == "draft":
            waiting_plans += 1
            todos.append(dict(level=1, title=f"แผนยังไม่กดส่ง {p.title}",
                              note=lesson_set.ready_to_send(p) or "แนบไฟล์ครบแล้ว กดส่งให้หัวหน้าวิชาการตรวจได้เลย",
                              tag="ร่าง", href=href, icon="ic-file"))
        rows.append(dict(title=p.title, term=p.term, label=label, tone=tone, href=href,
                         done=done, total=total, mode=lesson_set.mode_label(p)))

    for item in letters or []:
        lv = 0 if item["tag"] == "เลยกำหนดรายงาน" else 1
        todos.append(dict(level=lv, title=item["title"] or "หนังสือรับ", note=item.get("note") or "",
                          tag=item["tag"], href=item["href"], icon="ic-file"))
    todos.sort(key=lambda t: t["level"])

    reqs = []
    for r in db.query(LeaveRequest).filter(LeaveRequest.person_id == pid).order_by(LeaveRequest.id.desc()).limit(3):
        label, tone = REQ_STATUS.get(r.status or "", ("รออนุมัติ", "amber"))
        reqs.append(dict(kind="ใบลา", title=r.leave_type or "ลา", date=r.start_date, label=label, tone=tone,
                         href="/me/leave", sort=r.id, pending=r.status in ("pending", "personnel")))
    for r in db.query(TravelRequest).filter(TravelRequest.person_id == pid).order_by(TravelRequest.id.desc()).limit(3):
        label, tone = REQ_STATUS.get(r.status or "", ("รออนุมัติ", "amber"))
        reqs.append(dict(kind="ไปราชการ", title=r.subject or "ขอไปราชการ", date=r.start_date, label=label, tone=tone,
                         href="/me/travel", sort=r.id, pending=r.status in ("pending", "personnel")))
    from datetime import date as _date
    reqs.sort(key=lambda x: (x["date"] is not None, x["date"] or _date.min, x["sort"]), reverse=True)
    pending_req = db.query(LeaveRequest).filter(LeaveRequest.person_id == pid, LeaveRequest.status.in_(("pending", "personnel"))).count() \
        + db.query(TravelRequest).filter(TravelRequest.person_id == pid, TravelRequest.status.in_(("pending", "personnel"))).count()

    stats = [
        dict(label="หนังสือรอรับทราบ", n=letter_pending, href="/me/letters", icon="ic-file", tone="blue"),
        dict(label="แผนรอดำเนินการ", n=waiting_plans, href="/academic/lesson-plans", icon="ic-clipboard", tone="purple"),
        dict(label="บันทึกหลังสอนค้าง", n=after_left, href="/academic/lesson-plans", icon="ic-edit", tone="amber",
             unit="แผน"),
        dict(label="ใบลา/ไปราชการรออนุมัติ", n=pending_req, href="/me/leave", icon="ic-calendar", tone="green"),
    ]
    return dict(stats=stats, todos=todos[:8], plans=rows[:5], requests=reqs[:3], has_plans=bool(plans))
