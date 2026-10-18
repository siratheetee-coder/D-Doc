# -*- coding: utf-8 -*-
"""
academic_setup.py - รายการเริ่มต้นงานวิชาการ (หน้าหลักวิชาการ ผู้ดูแลเห็น ครูไม่เห็น)

แบบเดียวกับงานการเงิน/พัสดุ (_setup_checklist.html): ติ๊กจากข้อมูลจริง ขั้นถัดไปขั้นเดียว ครบแล้วหายเอง
ลำดับตามที่งานต่อไปต้องใช้: ปฏิทิน (แยกภาคเรียน/วันหยุด) > ห้องและนักเรียน > ครูประจำชั้น
> รายวิชา > ครูผู้สอน (ครูเห็นแค่วิชาที่สอน) > บัญชีครู > ตารางเรียน
แทนกล่อง "เริ่มใช้งานงานวิชาการ" เดิมที่เป็นข้อความตายตัว ไม่รู้ว่าทำไปถึงไหนแล้ว
"""
from app.models import (AcadClass, AcadSubject, AcadTeaching, AcadTimetable, AcadYearSetting)


def _names(items, n=3):
    head = ", ".join(items[:n])
    return head + (f" และอีก {len(items) - n}" if len(items) > n else "")


def setup_steps(db, year, *, tenant_id=None, is_owner=False) -> dict:
    from app.routers.academic import _class_label, _sorted_classes
    classes = _sorted_classes(db.query(AcadClass).filter_by(year=year).all())
    setting = db.query(AcadYearSetting).filter_by(year=year).first()
    terms_set = bool(setting and setting.t1_start and setting.t1_end and setting.t2_start and setting.t2_end)
    empty = [_class_label(c) for c in classes if not c.students]
    no_home = [_class_label(c) for c in classes if not c.homeroom_id]
    subjects = db.query(AcadSubject).filter_by(year=year).all()
    by_level = {}
    for s in subjects:
        by_level.setdefault(s.level, []).append(s)
    levels = sorted({c.level for c in classes})
    no_subj = [lv for lv in levels if not by_level.get(lv)]
    # ครูผู้สอน: ทุกคู่ (ห้อง, วิชาของชั้นนั้น) ต้องมีครู
    taught = {(t.class_id, t.subject_id) for t in db.query(AcadTeaching)
              .filter(AcadTeaching.teacher_id.isnot(None),
                      AcadTeaching.class_id.in_([c.id for c in classes] or [0]))}
    pairs = [(c, s) for c in classes for s in by_level.get(c.level, [])]
    missing = [(c, s) for c, s in pairs if (c.id, s.id) not in taught]
    no_tt = [_class_label(c) for c in classes
             if not db.query(AcadTimetable.id).filter_by(class_id=c.id).first()]

    steps = [
        dict(title="ตั้งปฏิทินปีการศึกษา", done=terms_set,
             detail=("ตั้งวันเปิด-ปิดภาคเรียนแล้ว" if terms_set
                     else "กรอกวันเปิด-ปิดภาคเรียนทั้ง 2 ภาค และวันหยุด ระบบใช้แยกภาคเรียน "
                          "นับวันเปิดเรียน และบอกวันหยุดตอนเลือกวันสอน"),
             href=f"/academic/calendar?year={year}", cta="ตั้งค่าปฏิทิน"),
        dict(title="สร้างห้องเรียนและดึงนักเรียน", done=bool(classes) and not empty,
             detail=(f"{len(classes)} ห้อง นักเรียน {sum(len(c.students) for c in classes)} คน" if classes and not empty
                     else (f"ยังไม่มีนักเรียน: {_names(empty)} · กด \"ดึงนักเรียนจากทะเบียนกลาง\" ในหน้าห้องเรียน"
                           if empty else "ตั้งชั้น/ห้องให้นักเรียนในทะเบียนนักเรียนก่อน แล้วสร้างห้องเรียน "
                                         "เช่น ป.1/1 แล้วดึงนักเรียนเข้าห้อง")),
             href=f"/academic/classes?year={year}", cta="ไปที่ห้องเรียน",
             extra=[("ทะเบียนนักเรียน", "/students")]),
        dict(title="เลือกครูประจำชั้น", done=bool(classes) and not no_home,
             detail=("ทุกห้องมีครูประจำชั้นแล้ว" if classes and not no_home
                     else (f"ยังไม่เลือก: {_names(no_home)} · ครูประจำชั้นเช็กชื่อและประเมินห้องตัวเองได้"
                           if no_home else "สร้างห้องเรียนก่อน")),
             href=f"/academic/classes?year={year}", cta="เลือกครูประจำชั้น"),
        dict(title="สร้างรายวิชา", done=bool(levels) and not no_subj,
             detail=(f"{len(subjects)} รายวิชา" if levels and not no_subj
                     else (f"ชั้นที่ยังไม่มีรายวิชา: {_names(no_subj)} · เลือกชั้นแล้วกดสร้าง 8 กลุ่มสาระได้ทีเดียว"
                           if no_subj else "สร้างห้องเรียนก่อน")),
             href=f"/academic/subjects?year={year}", cta="ไปที่รายวิชา"),
        dict(title="กำหนดครูผู้สอน", done=bool(pairs) and not missing,
             detail=("ทุกวิชาทุกห้องมีครูผู้สอนแล้ว" if pairs and not missing
                     else (f"ยังไม่มีครูผู้สอน {len(missing)} จาก {len(pairs)} วิชา-ห้อง "
                           f"เช่น {missing[0][1].name} ห้อง {_class_label(missing[0][0])} · "
                           "เลือกครู 1 คนแล้วติ๊กวิชาที่สอนได้ทีเดียว" if missing else "สร้างรายวิชาก่อน")),
             href=f"/academic/assign-teachers?year={year}", cta="กำหนดครูผู้สอน"),
    ]
    if is_owner:
        n_acc = 0
        try:
            from app.accounts import list_teacher_accounts
            n_acc = len(list_teacher_accounts(tenant_id) or [])
        except Exception:
            pass
        steps.append(dict(title="สร้างบัญชีครู", done=n_acc > 0,
                          detail=(f"มีบัญชีครู {n_acc} บัญชี" if n_acc
                                  else "ครูเข้าระบบด้วยบัญชีของตัวเอง กรอกคะแนนและเช็กชื่อได้เฉพาะวิชาและห้องที่สอน"),
                          href="/academic/teacher-accounts", cta="สร้างบัญชีครู"))
    steps.append(dict(title="ตั้งตารางเรียน (ข้ามได้ถ้ากรอกวันสอนเอง)", done=bool(classes) and not no_tt,
                      detail=("ทุกห้องมีตารางเรียนแล้ว" if classes and not no_tt
                              else (f"ยังไม่มีตารางเรียน: {_names(no_tt)} · ใช้ดึงวันสอนเข้าเวลาเรียนรายคาบ "
                                    "และพิมพ์ตารางรายห้อง/รายครู" if no_tt else "สร้างห้องเรียนก่อน")),
                      href=f"/academic/timetable?year={year}", cta="ไปที่ตารางเรียน"))
    for n, s in enumerate(steps, 1):
        s["n"] = n
        s.setdefault("extra", [])
    nxt = next((s for s in steps if not s["done"]), None)
    done = sum(1 for s in steps if s["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)
