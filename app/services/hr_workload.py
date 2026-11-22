"""ภาระงานบุคลากร: รวมงานที่ระบบรู้อยู่แล้ว + หน้าที่ที่กรอกเพิ่ม แล้วเทียบกับค่าเฉลี่ยของโรงเรียน

ดึงจาก: ตารางเรียน (คาบสอน) จัดครูเข้าสอน (วิชา/ห้อง) ห้องเรียน (ประจำชั้น/คู่ชั้น) สอนแทน
กรรมการจัดซื้อ/ตรวจรับ กรรมการอาหารกลางวัน ผู้ควบคุมทัศนศึกษา + StaffDuty
น้ำหนักเป็นค่ากลางที่ระบบตั้ง (ไม่ได้มาจากระเบียบ) โรงเรียนแก้ได้ ระบบแค่ชี้ให้เห็น ไม่ได้ตัดสินผลงาน
กรรมการจัดซื้อ/อาหารกลางวันเก็บเป็นชื่อ จับคู่กับทะเบียนบุคลากรด้วยชื่อที่ตัดคำนำหน้าแล้ว
"""
import re
from datetime import datetime

from app.models import (Person, AcadClass, AcadTeaching, AcadTimetable, SubstituteAssignment, Committee,
                        CommitteeMember, Procurement, LunchCommittee, LunchHireRound, FieldTrip,
                        FieldTripStaff, StaffDuty, WorkloadSetting, Project, PlanBudget, School)

PREFIXES = ("ว่าที่ร้อยตรีหญิง", "ว่าที่ร้อยตรี", "ว่าที่ ร.ต.", "นางสาว", "นาง", "นาย", "น.ส.", "ดร.", "ด.ร.")


def norm_name(n):
    s = re.sub(r"\s+", "", n or "")
    changed = True
    while changed:
        changed = False
        for p in PREFIXES:
            k = p.replace(" ", "")
            if s.startswith(k) and len(s) > len(k) + 1:
                s, changed = s[len(k):], True
    return s


def setting(db):
    s = db.query(WorkloadSetting).first()
    if not s:
        s = WorkloadSetting()
        db.add(s)
        db.commit()
    return s


def year_range(year):
    """ปีการศึกษา พ.ศ. -> ช่วงวันที่ 16 พ.ค. ถึง 15 พ.ค. ปีถัดไป"""
    ce = year - 543
    return datetime(ce, 5, 16), datetime(ce + 1, 5, 16)


def compute(db, year):
    st = setting(db)
    lo, hi = year_range(year)
    people = [p for p in db.query(Person).filter(Person.active == True).all()  # noqa: E712
              if (p.person_type or "ครู") not in ("นักการ",)]
    rows = {p.id: {"p": p, "periods": 0, "subjects": set(), "classes": set(), "homeroom": [], "cohome": [],
                   "sub": 0, "proc": [], "lunch": [], "trip": [], "project": [], "duties": []} for p in people}
    by_name = {}
    for p in people:
        by_name.setdefault(norm_name(p.name), p.id)
    classes = {c.id: c for c in db.query(AcadClass).filter_by(year=year).all()}
    # สอน: คู่ห้อง-วิชา -> ครู ; คาบ/สัปดาห์จากตารางเรียน
    teach = {}
    for t in db.query(AcadTeaching).all():
        if t.class_id in classes and t.teacher_id in rows:
            teach.setdefault((t.class_id, t.subject_id), set()).add(t.teacher_id)
            rows[t.teacher_id]["subjects"].add(t.subject_id)
            rows[t.teacher_id]["classes"].add(t.class_id)
    for r in db.query(AcadTimetable).filter(AcadTimetable.class_id.in_(list(classes) or [0])).all():
        for pid in teach.get((r.class_id, r.subject_id), ()):
            rows[pid]["periods"] += 1
    for c in classes.values():
        if c.homeroom_id in rows:
            rows[c.homeroom_id]["homeroom"].append(c)
        if c.co_homeroom_id in rows:
            rows[c.co_homeroom_id]["cohome"].append(c)
    for s in db.query(SubstituteAssignment).filter_by(year=year).all():
        if s.substitute_person_id in rows:
            rows[s.substitute_person_id]["sub"] += 1
    unmatched = {}

    def match(name, label, key):
        pid = by_name.get(norm_name(name))
        if pid:
            rows[pid][key].append(label)
        elif (name or "").strip():
            unmatched.setdefault(name.strip(), []).append(label)
    kinds = {"spec": "กำหนดคุณลักษณะ", "inspect": "ตรวจรับ", "purchase": "ซื้อหรือจ้าง"}
    q = (db.query(CommitteeMember, Committee, Procurement)
         .join(Committee, CommitteeMember.committee_id == Committee.id)
         .join(Procurement, Committee.procurement_id == Procurement.id)
         .filter(Procurement.request_date >= lo, Procurement.request_date < hi))
    for m, c, pr in q.all():
        match(m.name, f"กรรมการ{kinds.get(c.kind, '')}: {pr.subject}", "proc")
    lk = {"tor": "จัดทำ TOR", "control": "ควบคุมงาน", "inspect": "ตรวจรับ"}
    q = (db.query(LunchCommittee, LunchHireRound).join(LunchHireRound, LunchCommittee.round_id == LunchHireRound.id)
         .filter(LunchHireRound.start_date >= lo, LunchHireRound.start_date < hi))
    for m, r in q.all():
        match(m.name, f"กรรมการอาหารกลางวัน ({lk.get(m.kind, m.kind)})", "lunch")
    for s, t in db.query(FieldTripStaff, FieldTrip).join(FieldTrip, FieldTripStaff.trip_id == FieldTrip.id).filter(FieldTrip.year == year).all():
        label = f"ควบคุมทัศนศึกษา: {t.title or t.place or ''}".strip()
        if s.person_id in rows:
            rows[s.person_id]["trip"].append(label)
        else:
            match(s.name, label, "trip")
    # ผู้รับผิดชอบโครงการ: ช่องเป็นข้อความอิสระ (อาจมีหลายชื่อหรือชื่อฝ่าย) หาชื่อบุคลากรที่อยู่ในข้อความ
    # ปีของแผนเป็นปีงบหรือปีการศึกษาตามตั้งค่า: ปีการศึกษา Y (พ.ค.) ตรงกับปีงบ Y+1 (ต.ค.) เกือบทั้งปี
    # ชื่อที่หาไม่เจอไม่นับเป็นชื่อตกหล่น (มักเป็นชื่อฝ่าย)
    names = sorted(((k, pid) for k, pid in by_name.items() if len(k) >= 4), key=lambda x: -len(x[0]))
    for pj in project_list(db, year):
        txt = norm_name(pj.responsible)
        hit = set()
        for k, pid in names:
            if k in txt and pid not in hit:
                hit.add(pid)
                rows[pid]["project"].append(f"ผู้รับผิดชอบโครงการ: {pj.name}")
    for d in db.query(StaffDuty).filter_by(year=year).all():
        if d.person_id in rows:
            rows[d.person_id]["duties"].append(d)
    out = []
    for r in rows.values():
        parts = [("คาบสอน", r["periods"] * st.w_period), ("ประจำชั้น", len(r["homeroom"]) * st.w_homeroom),
                 ("คู่ชั้น", len(r["cohome"]) * st.w_cohome), ("สอนแทน", r["sub"] * st.w_sub),
                 ("กรรมการจัดซื้อ", len(r["proc"]) * st.w_proc), ("กรรมการอาหาร", len(r["lunch"]) * st.w_lunch),
                 ("ทัศนศึกษา", len(r["trip"]) * st.w_trip),
                 ("โครงการ", len(r["project"]) * (st.w_project if st.w_project is not None else 1.0)), ("หน้าที่อื่น", sum(d.weight or 0 for d in r["duties"]))]
        r["parts"] = parts
        r["score"] = round(sum(v for _, v in parts), 1)
        out.append(r)
    counted = [r for r in out if r["score"] > 0]
    avg = round(sum(r["score"] for r in counted) / len(counted), 1) if counted else 0
    for r in out:
        pct = (r["score"] / avg * 100) if avg else 0
        r["pct"] = round(pct)
        r["level"] = "high" if avg and pct >= st.high_pct else ("low" if avg and pct <= st.low_pct else "ok")
    out.sort(key=lambda r: (-r["score"], r["p"].name or ""))
    return {"rows": out, "avg": avg, "setting": st, "unmatched": unmatched,
            "n_high": sum(1 for r in out if r["level"] == "high"), "n_low": sum(1 for r in out if r["level"] == "low"),
            "avg_periods": round(sum(r["periods"] for r in counted) / len(counted), 1) if counted else 0}


def project_list(db, year):
    sc = db.query(School).first()
    default = (getattr(sc, "project_year_mode", None) or "budget") if sc else "budget"
    saved = {p.year: p.mode for p in db.query(PlanBudget).filter(PlanBudget.year.in_([year, year + 1])).all()}
    want = [y for y, m in ((year, "academic"), (year + 1, "budget")) if saved.get(y, default) == m]
    return db.query(Project).filter(Project.plan_year.in_(want or [0])).all()


def person_row(db, year, pid):
    data = compute(db, year)
    return next((r for r in data["rows"] if r["p"].id == pid), None), data
