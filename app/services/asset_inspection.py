# -*- coding: utf-8 -*-
"""
asset_inspection.py - ภาพรวมงานตรวจสอบพัสดุทั้งปี (หน้า /assets/inspection)

ลำดับงานตามระเบียบกระทรวงการคลังฯ พ.ศ. 2560 หมวด 9 (ตามที่หน้าตรวจสอบ/สำนวนจำหน่ายอ้างอยู่แล้ว)
  1 ตรวจสอบพัสดุประจำปี (ข้อ 213)  สถานะจากเลขเอกสารที่ออกจากหน้าตรวจสอบ (IssuedDocNo source=asset_audit ref=ปีงบ)
  2 พัสดุชำรุด/เสื่อมสภาพ/สูญไป/ไม่ใช้  ที่ยังไม่อยู่ในสำนวนจำหน่าย
  3 จำหน่ายพัสดุ (ข้อ 214-217)       สำนวนที่ยังไม่ลงจ่าย
  4 ลงจ่ายและรายงาน (ข้อ 218)        ลงจ่ายแล้ว ต้องแจ้ง สพท. + สตง. ภายใน 30 วัน (+ กค. ถ้าจำหน่ายเป็นสูญ, นำส่งเงินถ้าขายได้ ข้อ 216)
ไม่เก็บอะไรเพิ่ม คิดจากข้อมูลที่มีอยู่ทั้งหมด
"""
from datetime import datetime, timedelta

REPORT_DAYS = 30
STAGE_LABEL = {"fact": "สอบหาข้อเท็จจริง", "approve": "ขออนุมัติจำหน่าย", "sell": "ดำเนินการขาย",
               "closed": "ปิดเรื่องแล้ว"}


def report_state(dp) -> dict:
    """หนังสือรายงานหลังลงจ่ายของสำนวนหนึ่ง: ขาดอะไร ครบกำหนดเมื่อไร"""
    items = [it for it in dp.items]
    need = [("area", "แจ้ง สพท.", dp.area_no), ("sao", "แจ้ง สตง.", dp.sao_no)]
    if any((it.action or "") == "จำหน่ายเป็นสูญ" for it in items):
        need.append(("mof", "แจ้งกระทรวงการคลัง", dp.mof_no))
    sold = float(dp.sale_total or 0) or sum(float(it.sold_price or 0) for it in items)
    if sold > 0:
        need.append(("remit", "นำส่งเงินที่ขายได้", dp.remit_no))
    missing = [label for _k, label, no in need if not (no or "").strip()]
    due = dp.written_off_date + timedelta(days=REPORT_DAYS) if dp.written_off_date else None
    return {"need": [label for _k, label, _no in need], "missing": missing, "done": not missing, "due": due,
            "overdue": bool(due and missing and due < datetime.now()), "sold": sold}


def overview(db, fy: int) -> dict:
    from app.models import Asset, AssetDisposal, AssetDisposalItem, IssuedDocNo
    from app.services.asset_utils import ASSET_BAD_STATUSES

    audit_docs = (db.query(IssuedDocNo).filter_by(source="asset_audit", ref_id=fy)
                  .order_by(IssuedDocNo.id).all())
    bad = (db.query(Asset).filter(Asset.status.in_(ASSET_BAD_STATUSES))
           .order_by(Asset.asset_code, Asset.id).all())
    busy = {}
    for aid, did in (db.query(AssetDisposalItem.asset_id, AssetDisposal.id).join(AssetDisposal)
                     .filter(AssetDisposal.written_off_date.is_(None))):
        busy[aid] = did
    waiting = [a for a in bad if a.id not in busy]
    in_case = [(a, busy[a.id]) for a in bad if a.id in busy]

    cases = db.query(AssetDisposal).order_by(AssetDisposal.year.desc(), AssetDisposal.id.desc()).all()
    open_cases = [d for d in cases if not d.written_off_date]
    closed = [(d, report_state(d)) for d in cases if d.written_off_date]
    report_todo = [(d, s) for d, s in closed if not s["done"]]
    overdue = [(d, s) for d, s in report_todo if s["overdue"]]

    audit_done = bool(audit_docs)
    stages = [
        dict(key="audit", title="ตรวจสอบพัสดุประจำปี", rule="ข้อ 213", done=audit_done,
             status=("ออกเอกสารแล้ว" if audit_done else "ยังไม่ได้ตรวจ"),
             detail=(", ".join((x.subject or x.doc_type) + " " + (x.full_no or "") for x in audit_docs[:3])
                     if audit_done else "เริ่มตรวจวันเปิดทำการวันแรกของเดือนตุลาคม ออกคำสั่งและรายงานผลได้ในหน้าเดียว"),
             href="/assets/audit", cta="ไปตรวจสอบพัสดุ"),
        dict(key="damaged", title="พัสดุชำรุด/เสื่อมสภาพ", rule="ผลการตรวจ", done=not waiting,
             status=(f"รอเปิดสำนวน {len(waiting)} รายการ" if waiting
                     else ("อยู่ในสำนวนแล้วทั้งหมด" if bad else "ไม่มีรายการ")),
             detail=("เลือกรายการแล้วเปิดสำนวนจำหน่ายได้เลย" if waiting
                     else "ตั้งสถานะครุภัณฑ์ที่ตรวจพบว่าชำรุด เสื่อมสภาพ สูญไป หรือไม่ใช้ ในทะเบียนครุภัณฑ์"),
             href="/assets/inspection/damaged", cta="ดูรายการ"),
        dict(key="dispose", title="จำหน่ายพัสดุ", rule="ข้อ 214-217", done=not open_cases,
             status=(f"กำลังดำเนินการ {len(open_cases)} สำนวน" if open_cases else "ไม่มีสำนวนค้าง"),
             detail=(", ".join(f"ปี {d.year} {STAGE_LABEL.get(d.stage or 'fact', d.stage)}" for d in open_cases[:3])
                     if open_cases else "สอบหาข้อเท็จจริง ขออนุมัติ ขาย/ทำลาย/จำหน่ายเป็นสูญ"),
             href="/assets/disposal", cta="ไปที่สำนวน"),
        dict(key="report", title="ลงจ่ายและแจ้ง สตง.", rule="ข้อ 218", done=bool(closed) and not report_todo,
             status=(f"เลยกำหนด {len(overdue)} สำนวน" if overdue
                     else (f"รอรายงาน {len(report_todo)} สำนวน" if report_todo
                           else ("รายงานครบแล้ว" if closed else "ยังไม่มีสำนวนที่ลงจ่าย"))),
             detail="ลงจ่ายแล้วต้องแจ้ง สพท. และ สตง. ภายใน 30 วันนับแต่วันลงจ่าย",
             href="/assets/inspection/report", cta="ดูการรายงาน"),
    ]
    return {"fy": fy, "stages": stages, "audit_docs": audit_docs, "bad": bad, "waiting": waiting,
            "in_case": in_case, "open_cases": open_cases, "closed": closed, "report_todo": report_todo,
            "overdue": overdue, "n_done": sum(1 for s in stages if s["done"])}
