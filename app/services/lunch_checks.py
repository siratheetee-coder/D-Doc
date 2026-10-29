# -*- coding: utf-8 -*-
"""
lunch_checks.py - ตรวจความถูกต้องก่อนออกเอกสารงวด/ขอเบิกจ่าย ของงานจ้างเหมาประกอบอาหาร (ปรุงสำเร็จ)
และข้อมูลกราฟยอดนักเรียนรายวันทั้งรอบ

แต่ละข้อ = {"level": "err" (ต้องแก้) | "warn" (ควรเช็ค), "msg": ข้อความ, "href": ลิงก์ไปแก้}
ไม่บล็อกการออกเอกสาร แค่บอกก่อนกด (ผู้ใช้เลือกออกต่อได้)
"""
import json

from app.services import lunch_meals as lm


def _be(d) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year + 543}"


def _ent(rnd, kind) -> dict:
    try:
        return (json.loads(rnd.doc_nos or "{}") or {}).get(kind) or {}
    except Exception:
        return {}


def _issue(level, msg, href="", key="", short=""):
    """key/short: ใช้รวมเรื่องเดียวกันหลายงวดเป็นบรรทัดเดียวในกล่องตรวจ (เช่น ยังไม่มีเมนูบางวัน (งวดที่ 1, 2, 4))"""
    return {"level": level, "msg": msg, "href": href, "key": key or msg, "short": short or msg}


def round_issues(rnd, school) -> list:
    """เรื่องของทั้งรอบ ที่ทุกเอกสารงวดใช้ร่วมกัน"""
    plan = f"/lunch/round/{rnd.id}/plan"
    out = []
    if not rnd.vendor:
        out.append(_issue("err", "ยังไม่ได้เลือกผู้รับจ้าง", f"/lunch/round/{rnd.id}/edit"))
    if not (getattr(school, "director_name", "") or "").strip():
        out.append(_issue("err", "ยังไม่ได้กรอกชื่อผู้อำนวยการ (ผู้ลงนามในเอกสาร)", "/settings"))
    if not ((_ent(rnd, "hire-order").get("no") or "").strip() or (rnd.order_no or "").strip()):
        out.append(_issue("warn", "ยังไม่ได้ลงเลขที่ใบสั่งจ้าง (เอกสารงวดอ้างถึง)", plan + "#docnos"))
    kinds = {m.kind for m in rnd.committees}
    for k, label in (("control", "ผู้ควบคุมงาน"), ("inspect", "กรรมการตรวจรับ")):
        if k not in kinds:
            out.append(_issue("warn", f"ยังไม่ได้ใส่{label}", plan + "#committee"))
    committed = sum(float(i.amount or 0) for i in rnd.installments)
    if rnd.amount and committed - float(rnd.amount) > 0.005:
        out.append(_issue("err", f"ค่าจ้างรวมทุกงวด {committed:,.2f} บาท เกินวงเงินรอบ {float(rnd.amount):,.2f} บาท",
                          plan + "#installments"))
    return out


def installment_issues(db, inst, others, summary=None) -> list:
    """เรื่องของงวดหนึ่ง (เอกสารงวด: ควบคุม ส่งมอบ ตรวจรับ + บัญชีจำนวนนักเรียน)"""
    rnd = inst.round
    plan = f"/lunch/round/{rnd.id}/plan"
    row = plan + f"#inst-{inst.id}"
    meals = f"/lunch/installment/{inst.id}/meals"
    out = []
    if not inst.start_date or not inst.end_date:
        return [_issue("err", "ยังไม่ได้กรอกช่วงวันที่ของงวด", row)]
    if inst.end_date < inst.start_date:
        out.append(_issue("err", "วันสิ้นสุดงวดอยู่ก่อนวันเริ่มงวด", row))
    if rnd.start_date and rnd.end_date and (inst.start_date < rnd.start_date or inst.end_date > rnd.end_date):
        out.append(_issue("warn", "ช่วงวันที่ของงวดอยู่นอกช่วงเวลาของรอบ", row))
    for o in others:
        if o.id != inst.id and o.start_date and o.end_date \
                and o.start_date <= inst.end_date and inst.start_date <= o.end_date:
            out.append(_issue("err", f"ช่วงวันที่ซ้อนกับงวดที่ {o.seq}", row, "overlap", "ช่วงวันที่ซ้อนกับงวดอื่น"))
    if not inst.deliver_date or not inst.inspect_date:
        out.append(_issue("warn", "ยังไม่ได้ลงวันส่งมอบหรือวันตรวจรับ", row))
    else:
        if inst.inspect_date < inst.deliver_date:
            out.append(_issue("err", "วันตรวจรับอยู่ก่อนวันส่งมอบ", row))
        if inst.deliver_date.date() < inst.end_date.date():
            out.append(_issue("warn", "วันส่งมอบอยู่ก่อนวันสุดท้ายของงวด", row))
    if float(inst.amount or 0) <= 0:
        out.append(_issue("err", "ค่าจ้างงวดเป็น 0 บาท", row))

    s = summary or lm.summary(db, inst)
    prog = rnd.program
    menu_days = {m.date.date() for m in prog.menus if m.date}
    no_menu = [d for d in s["days"] if d not in menu_days]
    if no_menu:
        out.append(_issue("warn", f"ยังไม่มีเมนู {len(no_menu)} วัน (เช่น {_be(no_menu[0])})", plan + "#menus",
                          "menu", "ยังไม่มีเมนูบางวัน"))
    if prog.operate_mode == "hire":
        if not s["complete"]:
            out.append(_issue("warn", f"บันทึกยอดนักเรียนรายวันแล้ว {s['recorded']} จาก {len(s['days'])} วัน", meals,
                              "counts", "ยังบันทึกยอดนักเรียนรายวันไม่ครบ"))
        elif not s["matches"]:
            out.append(_issue("warn", f"ค่าจ้างงวด {s['amount']:,.2f} บาท ไม่ตรงกับยอดนักเรียน x ราคาต่อหัว "
                                      f"({s['value']:,.2f} บาท)", meals,
                              "value", "ค่าจ้างงวดไม่ตรงกับยอดนักเรียน x ราคาต่อหัว"))
        cap = s["eligible"]
        if cap:
            over = [d for d in s["days"] if sum(s["counts"].get(d, {}).values()) > cap]
            if over:
                out.append(_issue("err", f"ยอดนักเรียน {len(over)} วัน เกินจำนวนนักเรียนที่มีสิทธิ์ {cap:,} คน "
                                         f"(เช่น {_be(over[0])})", meals,
                                  "over", f"ยอดนักเรียนบางวันเกินจำนวนนักเรียนที่มีสิทธิ์ {cap:,} คน"))
    return out


def pay_issues(inst) -> list:
    """เพิ่มเติมสำหรับเอกสารขอเบิกจ่าย (บันทึก ใบสำคัญรับเงิน หนังสือรับรองหักภาษี)"""
    if (inst.status or "") not in lm.DONE_INSPECT:
        return [_issue("warn", f"งวดที่ {inst.seq} ยังไม่ได้ตรวจรับ",
                       f"/lunch/round/{inst.round_id}/plan#inst-{inst.id}", "uninspected", "ยังไม่ได้ตรวจรับ")]
    return []


def vendor_pay_issues(rnd) -> list:
    v = rnd.vendor
    if v and not (v.tax_id or "").strip():
        return [_issue("warn", "ผู้รับจ้างยังไม่มีเลขประจำตัวผู้เสียภาษี (ใช้ในหนังสือรับรองหักภาษี)",
                       f"/lunch/round/{rnd.id}/edit")]
    return []


def doc_checks(db, rnd, school, summaries=None) -> dict:
    """รายการตรวจต่อเอกสาร: "i<id>" เอกสารงวด, "d<id>" ขอเบิกจ่ายรายงวด, "r" ขอเบิกจ่ายทั้งรอบ"""
    summaries = summaries or {}
    insts = sorted(rnd.installments, key=lambda i: i.seq)
    base = round_issues(rnd, school)
    vend = vendor_pay_issues(rnd)
    out, all_inst = {}, []
    for i in insts:
        own = installment_issues(db, i, insts, summaries.get(i.id))
        out[f"i{i.id}"] = base + own
        out[f"d{i.id}"] = base + own + pay_issues(i) + vend
        all_inst += [dict(x, msg=f"งวดที่ {i.seq}: {x['msg']}", seq=i.seq) for x in own] \
            + [dict(x, seq=i.seq) for x in pay_issues(i)]
    out["r"] = base + all_inst + vend
    return out


def overview(checks: dict) -> list:
    """กล่องตรวจของหน้ารอบ: เรื่องเดียวกันหลายงวดรวมเป็นบรรทัดเดียว เรียง ต้องแก้ ก่อน ควรเช็ค"""
    out, by_key = [], {}
    for x in checks.get("r", []):
        if "seq" not in x:
            out.append(x)
            continue
        g = by_key.get(x["key"])
        if g is None:
            g = by_key[x["key"]] = dict(x, seqs=[])
            out.append(g)
        if x["seq"] not in g["seqs"]:
            g["seqs"].append(x["seq"])
    for g in by_key.values():
        if len(g["seqs"]) > 1:
            g["msg"] = f"{g['short']} (งวดที่ {', '.join(str(n) for n in g['seqs'])})"
    return sorted(out, key=lambda x: x["level"] != "err")


def round_chart(db, rnd, summaries=None) -> dict:
    """ข้อมูลกราฟ: ยอดนักเรียนรายวันทั้งรอบ แยกช่วงตามงวด (None = ยังไม่บันทึก)"""
    summaries = summaries or {}
    prog = rnd.program
    menus = {m.date.date(): " ".join(x for x in ((m.main or "").strip(), (m.dessert or "").strip()) if x)
             for m in prog.menus if m.date}
    groups = []
    for i in sorted(rnd.installments, key=lambda i: i.seq):
        s = summaries.get(i.id) or lm.summary(db, i)
        days = [{"be": _be(d), "n": (sum(s["counts"][d].values()) if d in s["counts"] else None),
                 "menu": menus.get(d, "")} for d in s["days"]]
        groups.append({"id": i.id, "seq": i.seq, "days": days, "total": s["meals"],
                       "recorded": s["recorded"], "ndays": len(s["days"])})
    vals = [d["n"] for g in groups for d in g["days"] if d["n"] is not None]
    return {"eligible": int(prog.total_students or 0), "groups": groups,
            "recorded": len(vals), "ndays": sum(g["ndays"] for g in groups),
            "avg": round(sum(vals) / len(vals)) if vals else 0,
            "min": min(vals) if vals else 0, "max": max(vals) if vals else 0}
