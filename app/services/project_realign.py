# -*- coding: utf-8 -*-
"""ย้ายเรื่องที่ลงวันที่นอกช่วงปีของแผน ไปผูกกับโครงการชื่อเดียวกันของปีที่ถูกต้อง

ตัวอย่างที่เจอจริง: โรงเรียนทำเรื่องพัสดุตามปีงบ 2569 (ต.ค. 68 ถึง ก.ย. 69) แล้วผูกกับโครงการปีการศึกษา 2569
(พ.ค. 69 ถึง เม.ย. 70) ทั้งหมด เรื่องช่วง ต.ค. 68 ถึง เม.ย. 69 ใช้เงินของแผนปีการศึกษา 2568 จริง ๆ
โครงการปี 2569 เลยดูเหมือนใช้เงินเกินงบ

ทำแค่ "เปลี่ยนว่าเรื่องนี้หักงบโครงการปีไหน" ไม่แตะเรื่องพัสดุ เลขที่ เอกสาร ทะเบียนพัสดุ หรือเงินในทะเบียนคุมเงิน
โครงการปีปลายทางที่ยังไม่มี สร้างให้ชื่อเดิม ฝ่ายเดิม งบ 0 (กรอกงบตามแผนปีนั้นทีหลังได้)
"""
import hashlib
from datetime import timedelta

KIND_LABEL = {"proc": "เรื่องพัสดุ", "memo": "บันทึกขอเบิกจ่าย", "txn": "รายการจ่ายในทะเบียนคุมเงิน"}


def plan_range(db, year):
    """(วันเริ่ม, วันสิ้นสุด) ของแผนปีนั้น · ใช้ช่วงที่บันทึกไว้ในหน้างบที่ใช้จัดทำแผน ถ้าไม่มีใช้ตามตั้งค่าโรงเรียน"""
    from app.services import plan_funding as pf
    from app.models import School
    p = pf.plan(db, year)
    if p:
        return p.start_date, p.end_date
    school = db.query(School).first()
    return pf.defaults(year, getattr(school, "project_year_mode", "budget") or "budget")


def proc_date(pr):
    """วันที่ของเรื่องพัสดุ = วันที่ใบสั่งซื้อ/สั่งจ้าง (ตัวเดียวกับที่แสดงในรายการเรื่องพัสดุ)
    request_date ใช้เป็นตัวสุดท้าย: ค่าเริ่มต้นคือวันที่พิมพ์เรื่องเข้าระบบ เรื่องที่ลงย้อนหลังจะได้วันที่ใหม่
    (เจอจริง: ลงเรื่องปีงบ 2569 ย้อนหลัง request_date เป็นเดือน ต.ค. 69 ทุกเรื่อง ตรวจไม่เจอว่าอยู่ปีก่อน)"""
    return pr.order_date or pr.inspect_date or pr.delivery_date or pr.request_date


def find(db, year) -> list:
    """เรื่องที่ผูกโครงการปีนี้แต่ลงวันที่นอกช่วงปี · [{kind, id, date, no, title, amount, project, target_year}]"""
    from app.models import Project, DisburseMemo, FinanceTxn
    from app.services.budget import project_procurements
    start, end = plan_range(db, year)
    end_excl = end + timedelta(days=1)
    projects = db.query(Project).filter(Project.plan_year == year).all()
    by_id = {p.id: p for p in projects}
    out, seen = [], set()

    def add(kind, obj, date, no, title, amount, project):
        if date is None or (kind, obj.id) in seen:
            return
        if start <= date < end_excl:
            return
        seen.add((kind, obj.id))
        out.append(dict(kind=kind, id=obj.id, date=date, no=no or "", title=title or "", amount=float(amount or 0),
                        project=project, target_year=year - 1 if date < start else year + 1))

    for pj in projects:
        for pr in project_procurements(pj):
            add("proc", pr, proc_date(pr), pr.memo_no, f"{pr.proc_type or ''}{pr.subject or ''}",
                pr.total_amount, pj)
    if by_id:
        for m in db.query(DisburseMemo).filter(DisburseMemo.project_id.in_(by_id), DisburseMemo.procurement_id.is_(None)):
            add("memo", m, m.date, m.memo_no, m.subject, m.amount, by_id[m.project_id])
        for t in db.query(FinanceTxn).filter(FinanceTxn.project_id.in_(by_id), FinanceTxn.kind == "out"):
            add("txn", t, t.date, t.ref, t.note, t.amount, by_id[t.project_id])
    out.sort(key=lambda r: (r["date"], r["kind"], r["id"]))
    return out


def token(rows) -> str:
    return hashlib.sha256("|".join(f"{r['kind']}:{r['id']}:{r['project'].id}" for r in rows).encode()).hexdigest()[:20]


def targets(db, rows) -> dict:
    """{(ชื่อโครงการ, ปี): โครงการปลายทางที่มีอยู่แล้ว หรือ None = จะสร้างใหม่}"""
    from app.models import Project
    need = {((r["project"].name or "").strip(), r["target_year"]) for r in rows}
    found = {}
    for name, y in need:
        found[(name, y)] = db.query(Project).filter(Project.plan_year == y, Project.name == name).first()
    return found


def apply(db, year, expected) -> dict:
    """ย้ายตามรายการปัจจุบัน (คำนวณใหม่ ไม่เชื่อฟอร์ม) · รายการเปลี่ยนตั้งแต่เปิดหน้า = ไม่ทำ"""
    from app.models import Project, Procurement, DisburseMemo, FinanceTxn
    rows = find(db, year)
    if not rows:
        return dict(moved=0, created=0)
    if token(rows) != expected:
        raise ValueError("รายการเปลี่ยนไปแล้ว กรุณาเปิดหน้านี้ใหม่แล้วตรวจอีกครั้ง")
    have = targets(db, rows)
    created = 0
    for key, pj in list(have.items()):
        if pj is None:
            name, y = key
            src = next(r["project"] for r in rows if ((r["project"].name or "").strip(), r["target_year"]) == key)
            pj = Project(name=name, budget=0.0, plan_year=y, responsible=src.responsible or "", active=True)
            db.add(pj)
            db.flush()
            have[key] = pj
            created += 1
    model = {"proc": Procurement, "memo": DisburseMemo, "txn": FinanceTxn}
    for r in rows:
        obj = db.get(model[r["kind"]], r["id"])
        tgt = have[((r["project"].name or "").strip(), r["target_year"])]
        obj.project_id = tgt.id           # เรื่องเก่าที่ผูกด้วยชื่อ+ปี ได้ project_id แล้ว จะไม่กลับไปจับคู่ปีเดิมอีก
    db.commit()
    return dict(moved=len(rows), created=created)
