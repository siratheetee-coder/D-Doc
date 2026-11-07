# -*- coding: utf-8 -*-
"""ส่ง ผอ. อนุมัติ งานอาหารกลางวัน (services/approval.py ระยะ 3)

แบ่ง 3 ชนิด
  lunch_round  เปิดเรื่องของรอบ  (จ้างเหมา: รายงานขอจ้าง คำสั่งกรรมการ ผลพิจารณา ประกาศ ใบสั่งจ้าง
                                 แม่ครัว: รายงานขอจ้าง ผลพิจารณา ประกาศ ใบสั่งจ้าง
                                 ซื้อวัตถุดิบ: รายงานขอซื้อ บันทึกขอยืมเงิน สัญญายืมเงิน บันทึกตรวจรับ)
  lunch_pay    จ่ายเงินระดับรอบ   (ซื้อวัตถุดิบ: รายงานผู้ควบคุม ขอเบิกส่งใช้เงินยืม ใบสรุปเบิก
                                 แม่ครัว: ส่งมอบตรวจรับ ขอเบิก  จ้างเหมาที่จ่ายครั้งเดียวทั้งรอบ: ขอเบิกทั้งรอบ)
  lunch_inst   งวดงาน            (ส่งมอบตรวจรับงวด + ขอเบิกงวด ถ้าจ่ายทุกงวด)

render(db, key, obj) = จุดเดียวที่สร้างไฟล์ ทั้งปุ่มดาวน์โหลดในหน้ารอบและหน้าดูตัวอย่างของ ผอ. ใช้ร่วมกัน
แปะลายเซ็นตามชนิดที่ key สังกัด (KIND_OF) ไฟล์รวมทั้งชุด (bundle) ไม่แปะ เพราะมีเอกสารหลายชนิดปนกัน
"""
from types import SimpleNamespace

_MODE_DOCS = {
    "hire": [("hire-report", "รายงานขอจ้าง"), ("committee", "คำสั่งแต่งตั้งคณะกรรมการ"),
             ("result", "รายงานผลการพิจารณา"), ("winner", "ประกาศผู้ชนะ"), ("order", "ใบสั่งจ้าง")],
    "person": [("p:hire-report", "รายงานขอจ้าง"), ("p:result", "รายงานผลการพิจารณา"),
               ("p:winner", "ประกาศผู้ชนะ"), ("p:order", "ใบสั่งจ้าง")],
    "ingredient": [("i:report", "รายงานขอซื้อวัตถุดิบ"), ("i:borrow", "บันทึกขออนุมัติยืมเงิน"),
                   ("i:loan", "สัญญายืมเงิน"), ("i:inspect-notify", "บันทึกการตรวจรับพัสดุ")],
}
_PAY_DOCS = {
    "ingredient": [("i:control", "รายงานผู้ควบคุมและกรรมการตรวจ"), ("i:repay", "บันทึกขอเบิกส่งใช้เงินยืม"),
                   ("i:reimburse", "ใบสรุปเบิกเงินชดเชยเงินยืม")],
    "person": [("p:deliver", "ส่งมอบและตรวจรับงาน"), ("p:disburse", "บันทึกขอเบิกจ่าย")],
}
_INST_DOCS = [("inst", "ส่งมอบและตรวจรับงวด"), ("inst-disburse", "บันทึกขอเบิกจ่ายงวด")]

KIND_OF = {k: "lunch_round" for docs in _MODE_DOCS.values() for k, _ in docs}
KIND_OF.update({k: "lunch_pay" for docs in _PAY_DOCS.values() for k, _ in docs})
KIND_OF.update({"round-disburse": "lunch_pay", "inst": "lunch_inst", "inst-disburse": "lunch_inst"})


def _mode(rnd) -> str:
    m = (rnd.program.operate_mode if rnd and rnd.program else "") or "hire"
    return m if m in _MODE_DOCS else "hire"


def round_docs(rnd) -> list:
    return list(_MODE_DOCS[_mode(rnd)])


def pay_docs(rnd) -> list:
    m = _mode(rnd)
    if m in _PAY_DOCS:
        return list(_PAY_DOCS[m])
    if (rnd.pay_mode or "installment") == "round" and rnd.installments:
        return [("round-disburse", "บันทึกขอเบิกจ่ายทั้งรอบ")]
    return []


def inst_docs(inst) -> list:
    if (inst.round.pay_mode or "installment") == "round":
        return _INST_DOCS[:1]
    return list(_INST_DOCS)


# ---------------------------------------------------------------- ลายนิ้วมือ (แก้หลังอนุมัติ = ลายเซ็นหลุด)
def _d(x):
    return x.strftime("%Y-%m-%d") if x else ""


def fp_round(r) -> str:
    com = ";".join(f"{c.kind}:{c.name}:{c.role}" for c in sorted(r.committees or [], key=lambda c: (c.kind, c.seq)))
    base = "|".join([str(r.vendor_id or ""), f"{float(r.amount or 0):.2f}", _d(r.start_date), _d(r.end_date),
                     str(r.days or 0), f"{float(r.fuel_cost or 0):.2f}", f"{float(r.cook_wage or 0):.2f}", com])
    return base + ('|calendar:'+r.calendar_dates if getattr(r,'calendar_dates',None) is not None else '')


def fp_pay(r) -> str:
    insts = ";".join(f"{i.seq}:{float(i.amount or 0):.2f}:{i.penalty_days or 0}" for i in r.installments or [])
    return fp_round(r) + "|" + (r.pay_mode or "") + "|" + insts + ("|calendar:"+";".join(i.calendar_dates or '' for i in (r.installments or [])) if any(getattr(i,'calendar_dates',None) is not None for i in (r.installments or [])) else '')


def fp_inst(i) -> str:
    base = "|".join([str(i.seq), f"{float(i.amount or 0):.2f}", str(i.days or 0), _d(i.start_date), _d(i.end_date),
                     _d(i.deliver_date), _d(i.inspect_date), str(i.penalty_days or 0)])
    return base + ('|calendar:'+i.calendar_dates if getattr(i,'calendar_dates',None) is not None else '')


def title_round(r) -> str:
    p = r.program
    return f"อาหารกลางวัน รอบที่ {r.seq}" + (f" ปีการศึกษา {p.year}" if p and p.year else "")


def title_inst(i) -> str:
    return f"{title_round(i.round)} งวดที่ {i.seq}"


# ---------------------------------------------------------------- สร้างไฟล์
def _menus(prog, start, end):
    return sorted([m for m in prog.menus if m.date and start and end and start <= m.date <= end],
                  key=lambda m: m.date)


def render_inst(db, inst, school):
    prog = inst.round.program
    menus = _menus(prog, inst.start_date, inst.end_date)
    if prog.operate_mode == "person":
        from app.services.lunch_person_doc import render_p_installment
        return render_p_installment(inst, school, menus)
    from app.services.lunch_doc import render_installment_doc
    meals = None
    if prog.operate_mode == "hire":
        from app.services.lunch_meals import summary as _ms
        meals = {"classes": list(prog.classes), "summary": _ms(db, inst)}
    return render_installment_doc(inst, school, menus, meals)


def render_inst_disburse(db, inst, school):
    if inst.round.program.operate_mode == "person":
        from app.services.lunch_person_doc import render_p_disburse
        return render_p_disburse(inst, school)
    from app.services.lunch_doc import render_disburse_lunch_doc
    from app.services.lunch_meals import summary as _ms
    return render_disburse_lunch_doc(inst, school, penalty=_ms(db, inst)["penalty"])


def render_round_disburse(db, rnd, school):
    from app.services.lunch_doc import render_disburse_lunch_doc
    from app.services.lunch_meals import round_pay
    insts = sorted(rnd.installments, key=lambda i: i.seq)
    rp = round_pay(db, rnd)
    whole = SimpleNamespace(
        round=rnd, seq=f"1-{insts[-1].seq}" if len(insts) > 1 else str(insts[0].seq),
        start_date=insts[0].start_date or rnd.start_date, end_date=insts[-1].end_date or rnd.end_date,
        days=sum(i.days or 0 for i in insts), amount=rp["amount"],
        inspect_date=max((i.inspect_date for i in insts if i.inspect_date), default=None))
    return render_disburse_lunch_doc(whole, school, penalty=rp["penalty"],
                                     period_label=f"รอบที่ {rnd.seq} (งวดที่ {whole.seq})")


def render_person_round(db, rnd, school, kind):
    import app.services.lunch_person_doc as pd
    menus = _menus(rnd.program, rnd.start_date, rnd.end_date)
    period = pd._round_period(rnd)
    if kind == "deliver":
        return pd.render_p_installment(period, school, menus)
    return pd.render_p_disburse(period, school)


_HIRE_FN = {"hire-report": "render_hire_report_doc", "committee": "render_committee_order_doc",
            "result": "render_result_doc", "winner": "render_winner_doc", "order": "render_order_doc"}


def render(db, key, obj, school):
    """สร้างไฟล์ของเอกสาร key (obj = รอบ หรือ งวด) คืน path (ยังไม่แปะลายเซ็น)"""
    if key == "inst":
        return render_inst(db, obj, school)
    if key == "inst-disburse":
        return render_inst_disburse(db, obj, school)
    if key == "round-disburse":
        return render_round_disburse(db, obj, school)
    if key in _HIRE_FN:
        import app.services.lunch_doc as ld
        return getattr(ld, _HIRE_FN[key])(obj, school)
    if key.startswith("p:"):
        k = key[2:]
        if k in ("deliver", "disburse"):
            return render_person_round(db, obj, school, k)
        import app.services.lunch_person_doc as pd
        return getattr(pd, "render_p_" + k.replace("-", "_"))(obj, school)
    if key.startswith("i:"):
        from app.routers.lunch import _INGREDIENT_DOCS
        import app.services.lunch_ingredient_doc as ig
        return getattr(ig, _INGREDIENT_DOCS[key[2:]])(obj, school)
    raise KeyError(key)


def stamp(kind, ref_id, path, school):
    """แปะลายเซ็น/ติ๊กอนุมัติ ถ้าเรื่องนี้ ผอ. อนุมัติแล้ว"""
    from app.services.approval import stamp_current
    stamp_current(kind, ref_id, path, (school.director_name or "") if school else "",
                  tick=("อนุมัติ", "เห็นชอบ"))
    return path


def render_stamped(db, key, obj, school):
    """ปุ่มดาวน์โหลดในหน้ารอบ: สร้างไฟล์ + แปะลายเซ็นตามชนิดของเอกสาร"""
    path = render(db, key, obj, school)
    kind = KIND_OF.get(key)
    if kind:
        stamp(kind, obj.id, path, school)
    return path
