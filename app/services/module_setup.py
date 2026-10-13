# -*- coding: utf-8 -*-
"""
module_setup.py - รายการเริ่มต้นของงานอาหารกลางวัน งานธุรการ และงานบุคคล

แบบเดียวกับการเงิน/พัสดุ/วิชาการ (กล่อง _setup_checklist.html): ติ๊กจากข้อมูลจริง
ขั้นถัดไปขั้นเดียวพร้อมปุ่ม บอกตรง ๆ ว่ายังขาดอะไร ครบแล้วกล่องหายเอง
"""
from app.models import Person


def _pack(steps):
    for n, s in enumerate(steps, 1):
        s["n"] = n
        s.setdefault("extra", [])
    nxt = next((s for s in steps if not s["done"]), None)
    done = sum(1 for s in steps if s["done"])
    return dict(steps=steps, done=done, total=len(steps), complete=nxt is None, next=nxt)


def _missing(school, fields):
    return [label for key, label in fields if not (getattr(school, key, "") or "").strip()]


# ---------------- อาหารกลางวัน ----------------
def lunch_steps(db, year, school=None) -> dict:
    """โครงการของปีการศึกษาปัจจุบัน: ตั้งโครงการ > นักเรียนและอัตรา (งบ) > รูปแบบและผู้รับผิดชอบ
    > รอบจัดจ้าง/จัดซื้อแรก (โหมดทำเองไม่ออกเอกสาร ข้ามขั้นนี้) > เมนูอาหาร"""
    from app.models import LunchProgram, LunchMenu
    prog = (db.query(LunchProgram).filter(LunchProgram.year == year)
            .filter((LunchProgram.pool == 0) | (LunchProgram.pool.is_(None)))
            .order_by(LunchProgram.id.desc()).first())
    pid = prog.id if prog else None
    edit = f"/lunch/{pid}/edit" if pid else "/lunch/setup"
    budget = float(prog.budget or 0) if prog else 0
    who = _missing(prog, [("funding_org", "อปท.ผู้จัดสรร"), ("lunch_officer", "เจ้าหน้าที่โครงการอาหารกลางวัน")]) if prog else []
    mode = (prog.operate_mode or "hire") if prog else "hire"
    word = "รอบจัดซื้อ" if mode == "ingredient" else "รอบจัดจ้าง"
    steps = [
        dict(title=f"ตั้งโครงการปีการศึกษา {year}", done=bool(prog),
             detail=("ตั้งโครงการแล้ว" if prog else "ระบบดึงจำนวนนักเรียนแต่ละชั้นจากทะเบียนนักเรียนให้เอง"),
             href="/lunch/setup", cta="ตั้งโครงการ"),
        dict(title="ใส่จำนวนนักเรียนและอัตราต่อหัว", done=budget > 0,
             detail=(f"งบทั้งปี {budget:,.2f} บาท" if budget > 0
                     else "งบ = นักเรียน × อัตราต่อหัวต่อวัน × จำนวนวัน เช่น 120 คน × 36 บาท × 200 วัน = 864,000 บาท"),
             href=edit, cta="ตั้งค่าโครงการ"),
        dict(title="เลือกรูปแบบและผู้รับผิดชอบ", done=bool(prog) and not who,
             detail=("กรอกครบแล้ว" if prog and not who
                     else ("ยังไม่ได้กรอก: " + ", ".join(who) + " · ใช้ในเอกสารจัดจ้าง/จัดซื้อทุกฉบับ") if who
                     else "ตั้งโครงการก่อน"),
             href=edit, cta="ตั้งค่าโครงการ"),
    ]
    if mode != "self":
        n_round = len(prog.rounds) if prog else 0
        steps.append(dict(title=f"เพิ่ม{word}แรก", done=n_round > 0,
                          detail=(f"มี {n_round} รอบ" if n_round
                                  else ("1 รอบจัดจ้าง = ทำเรื่อง 1 ครั้ง แบ่งจ่ายเป็นงวดได้ เช่น ภาคเรียนละ 1 รอบ"
                                        if mode == "hire" else f"1 {word} = ทำเรื่องและจ่ายเงิน 1 ครั้ง เช่น เดือนละ 1 รอบ")),
                          href=f"/lunch/{pid}/rounds" if pid else "/lunch/setup", cta=f"เพิ่ม{word}"))
    n_menu = db.query(LunchMenu).filter_by(program_id=pid).count() if pid else 0
    steps.append(dict(title="ใส่เมนูอาหาร", done=n_menu > 0,
                      detail=(f"มีเมนู {n_menu} วัน" if n_menu
                              else "เมนูถูกดึงไปใส่ในเอกสารส่งมอบและตรวจรับให้เอง สร้างเมนูหมุนเวียนทั้งรอบได้ทีเดียว"),
                      href=f"/lunch/{pid}/menu" if pid else "/lunch/setup", cta="ใส่เมนู"))
    return _pack(steps)


# ---------------- ธุรการ ----------------
def admin_steps(db, school) -> dict:
    from app.models import IncomingLetter, OutgoingLetter, OfficeMemo
    who = _missing(school, [("name", "ชื่อโรงเรียน"), ("director_name", "ชื่อผู้อำนวยการ"),
                            ("admin_officer_name", "เจ้าหน้าที่ธุรการ")])
    prefix = (school.doc_prefix or "").strip()
    has_code = any(ch.isdigit() for ch in prefix)
    n_in = db.query(IncomingLetter.id).first() is not None
    n_out = (db.query(OutgoingLetter.id).first() is not None) or (db.query(OfficeMemo.id).first() is not None)
    return _pack([
        dict(title="กรอกข้อมูลโรงเรียนและผู้ลงนาม", done=not who,
             detail=("กรอกครบแล้ว" if not who else "ยังไม่ได้กรอก: " + ", ".join(who) + " · ใช้ในหนังสือทุกฉบับ"),
             href="/settings", cta="ไปตั้งค่าโรงเรียน"),
        dict(title="ตั้งอักษรนำเลขที่หนังสือ", done=has_code,
             detail=(f"ใช้ \"{prefix}\"" if has_code
                     else f"ตอนนี้เป็น \"{prefix or 'ศธ'}\" ยังไม่มีรหัสโรงเรียน ใส่ให้ครบ เช่น ศธ 04123 "
                          "เลขหนังสือส่งจะออกเป็น ศธ 04123/123"),
             href="/settings", cta="ไปตั้งค่าโรงเรียน"),
        dict(title="ลงรับหนังสือฉบับแรก", done=n_in,
             detail=("มีหนังสือรับในทะเบียนแล้ว" if n_in
                     else "ระบบออกเลขรับให้เอง อ่านหนังสือจาก PDF หรือรูปด้วย AI ได้"),
             href="/admin/incoming", cta="ลงรับหนังสือ"),
        dict(title="ออกหนังสือส่งหรือบันทึกข้อความ", done=n_out,
             detail=("ออกเลขหนังสือแล้ว" if n_out else "ระบบออกเลขที่ต่อเนื่องให้เอง ไม่ซ้ำกัน"),
             href="/admin/outgoing", cta="ออกหนังสือส่ง",
             extra=[("บันทึกข้อความ", "/admin/memos")]),
    ])


# ---------------- บุคคล ----------------
def hr_steps(db, school) -> dict:
    who = _missing(school, [("name", "ชื่อโรงเรียน"), ("director_name", "ชื่อผู้อำนวยการ")])
    people = db.query(Person).filter(Person.active.isnot(False)).all()
    director = (school.director_name or "").strip()
    d_person = next((p for p in people if (p.name or "").strip() == director), None) if director else None
    has_sig = bool(d_person and (d_person.signature or "").strip())
    emails = [e for e in ((school.director_email or "").strip(), (school.hr_head_email or "").strip()) if e]
    return _pack([
        dict(title="กรอกข้อมูลโรงเรียนและผู้อำนวยการ", done=not who,
             detail=("กรอกครบแล้ว" if not who else "ยังไม่ได้กรอก: " + ", ".join(who)),
             href="/settings", cta="ไปตั้งค่าโรงเรียน"),
        dict(title="เพิ่มทะเบียนบุคลากร", done=bool(people),
             detail=(f"มี {len(people)} คน" if people
                     else "ชื่อ ตำแหน่ง วันเริ่มงาน ใช้ในใบลา ไปราชการ และสรุปวันลา นำเข้าจาก Excel ได้"),
             href="/hr/staff", cta="ไปทะเบียนบุคลากร"),
        dict(title="ตั้งอีเมลผู้อนุมัติ", done=bool(emails),
             detail=("ระบบแจ้งเตือนผู้อนุมัติทางอีเมลแล้ว" if emails
                     else "ใส่อีเมลผู้อำนวยการหรือหัวหน้าฝ่ายบุคคล ระบบจะส่งอีเมลแจ้งเมื่อมีใบลาหรือขอไปราชการรออนุมัติ"),
             href="/settings", cta="ไปตั้งค่าโรงเรียน"),
        dict(title="อัปโหลดลายเซ็นผู้อำนวยการ", done=has_sig,
             detail=("มีลายเซ็นแล้ว ระบบแปะลงเอกสารที่อนุมัติให้เอง" if has_sig
                     else (f"ยังไม่มีลายเซ็นของ {director} · อัปโหลดรูปลายเซ็นพื้นใส ระบบแปะลงใบลาที่อนุมัติให้เอง"
                           if d_person else f"ยังไม่มี {director or 'ผู้อำนวยการ'} ในรายชื่อบุคลากร "
                                            "เพิ่มชื่อให้ตรงกับในตั้งค่าโรงเรียน แล้วอัปโหลดลายเซ็น")),
             href="/masters", cta="อัปโหลดลายเซ็น"),
    ])


# ---------------- อาหารกลางวัน: ขั้นตอนในหนึ่งรอบ ----------------
def lunch_round_steps(rnd, *, committees, com_labels, doc_rows, menu_days, ing_total, ing_remaining) -> dict:
    """ขั้นตอนของรอบจัดจ้าง/จัดซื้อหนึ่งรอบ แยกตามรูปแบบ (เจ้าของขอ)
      hire       จ้างเหมาปรุงสำเร็จ: ช่วงเวลา/วงเงิน > ผู้รับจ้าง > กรรมการ > เลขที่หนังสือ > เมนู
                 > ตกลงจ้าง (เลขที่ใบสั่งจ้าง) > แบ่งงวดจ่ายเงิน > ส่งมอบ ตรวจรับ จ่ายครบทุกงวด
      ingredient ซื้อวัตถุดิบ: ช่วงเวลา > กรรมการ > เลขที่หนังสือ (รวมสัญญายืม) > เมนู > วัตถุดิบรายวัน > ส่งใช้เงินยืม
      person     จ้างแม่ครัว + ซื้อวัตถุดิบ: ช่วงเวลา/ค่าจ้าง > แม่ครัว > กรรมการ > เลขที่หนังสือ > เมนู
                 > วัตถุดิบรายวัน > ตกลงจ้าง > จ่ายแล้ว
    ข้อมูลทุกตัวมาจากหน้ารอบอยู่แล้ว (contract_plan) ไม่ได้นับว่ากดดาวน์โหลดเอกสารหรือยัง"""
    p = rnd.program
    mode = p.operate_mode or "hire"
    rid, pid = rnd.id, p.id
    page = f"/lunch/round/{rid}/plan"
    edit = f"/lunch/round/{rid}/edit"
    word = "รอบจัดซื้อ" if mode == "ingredient" else "รอบจัดจ้าง"

    has_period = bool(rnd.start_date and (rnd.days or 0) > 0)
    no_com = [label for k, label in com_labels.items() if not committees.get(k)]
    doc_total = len(doc_rows)
    doc_done = sum(1 for d in doc_rows if any(f.get("value") for f in d["fields"]))
    doc_left = [d["label"] for d in doc_rows if not any(f.get("value") for f in d["fields"])]
    menu_total = len(menu_days)
    menu_have = sum(1 for d in menu_days if d.get("has"))
    ordered = bool((rnd.order_no or "").strip() and rnd.order_date)
    paid = (rnd.status or "") == "จ่ายแล้ว"

    def period_step(extra_ok=True, extra_text=""):
        ok = has_period and extra_ok
        return dict(title="ตั้งช่วงเวลา" + ("และวงเงิน" if mode == "hire" else "และค่าจ้างแม่ครัว" if mode == "person" else ""),
                    done=ok,
                    detail=(f"{rnd.days} วันทำการ" + (f" · {extra_text}" if extra_text else "")) if ok
                    else ("ใส่วันเริ่มและจำนวนวันทำการ ระบบคำนวณวันสิ้นสุดให้ (ไม่นับวันหยุด)" if not has_period
                          else f"ยังไม่ได้ใส่{'วงเงินรอบนี้' if mode == 'hire' else 'ค่าจ้างแม่ครัว (รอบนี้)'}"),
                    href=edit, cta=f"แก้ไข{word}")

    vendor_step = dict(title="เลือกผู้รับจ้าง" if mode == "hire" else "เลือกแม่ครัว (ผู้รับจ้าง)",
                       done=bool(rnd.vendor_id),
                       detail=(rnd.vendor.name if rnd.vendor else "เลือกจากรายชื่อ หรือพิมพ์ชื่อใหม่ในหน้าแก้ไขรอบ ระบบบันทึกเป็นผู้รับจ้างให้"),
                       href=edit, cta=f"แก้ไข{word}")
    com_step = dict(title="แต่งตั้งกรรมการ", done=not no_com,
                    detail=("ครบทุกชุดแล้ว" if not no_com else "ยังไม่มีกรรมการ: " + ", ".join(no_com)
                            + " · ดึงจากรอบอื่นที่ตั้งไว้แล้วได้"),
                    href=page + "#committee", cta="ไปที่กรรมการ")
    doc_step = dict(title="กรอกเลขที่หนังสือ", done=doc_total > 0 and not doc_left,
                    detail=(f"ครบ {doc_total} ฉบับ" if not doc_left
                            else f"กรอกแล้ว {doc_done} จาก {doc_total} ฉบับ · ยังไม่ได้กรอก {doc_left[0]}"
                            + (f" และอีก {len(doc_left) - 1} ฉบับ" if len(doc_left) > 1 else "")),
                    href=page + "#docnos", cta="ไปกรอกเลขที่")
    menu_step = dict(title="ใส่เมนูอาหารครบทุกวัน", done=menu_total > 0 and menu_have >= menu_total,
                     detail=(f"ครบ {menu_total} วัน" if menu_total and menu_have >= menu_total
                             else (f"มีเมนู {menu_have} จาก {menu_total} วัน · สร้างเมนูหมุนเวียนทั้งรอบได้ทีเดียว"
                                   if menu_total else "ตั้งช่วงเวลาของรอบก่อน")),
                     href=page + "#menus", cta="ไปที่เมนู")
    ing_ok = ing_total > 0 and ing_remaining >= 0
    ing_step = dict(title="กรอกวัตถุดิบรายวัน", done=ing_ok,
                    detail=(f"ค่าวัตถุดิบ {ing_total:,.2f} บาท อยู่ในงบ" if ing_ok
                            else (f"ค่าวัตถุดิบ {ing_total:,.2f} บาท เกินงบ {-ing_remaining:,.2f} บาท" if ing_total > 0
                                  else "กรอกวัตถุดิบและราคาต่อวัน ระบบรวมยอดและออกใบจัดซื้อรายวันให้")),
                    href=f"/lunch/{pid}/ingredients?back={page}", cta="กรอกวัตถุดิบ")
    order_step = dict(title="ตกลงจ้าง (เลขที่ใบสั่งจ้าง)", done=ordered,
                      detail=(f"เลขที่ {rnd.order_no}" if ordered
                              else "ใส่เลขที่และวันที่ตกลงจ้างในหน้าแก้ไขรอบ ใบสั่งจ้างและเอกสารเบิกจ่ายใช้เลขนี้"),
                      href=edit, cta=f"แก้ไข{word}")

    if mode == "hire":
        insts = list(rnd.installments)
        n_paid = sum(1 for i in insts if i.status == "จ่ายแล้ว")
        steps = [period_step((rnd.amount or 0) > 0, f"วงเงิน {rnd.amount or 0:,.2f} บาท"), vendor_step, com_step,
                 doc_step, menu_step, order_step,
                 dict(title="แบ่งงวดจ่ายเงิน", done=bool(insts),
                      detail=(f"{len(insts)} งวด" if insts else "เช่น 5 งวด งวดละ 20 วัน ระบบแบ่งวันและวงเงินให้"),
                      href=page + "#installments", cta="แบ่งงวด"),
                 dict(title="ส่งมอบ ตรวจรับ และจ่ายครบทุกงวด", done=bool(insts) and n_paid == len(insts),
                      detail=(f"จ่ายแล้ว {n_paid} จาก {len(insts)} งวด" if insts else "แบ่งงวดก่อน"),
                      href=page + "#installments", cta="ไปที่งวดจ่ายเงิน")]
    elif mode == "person":
        steps = [period_step((rnd.cook_wage or 0) > 0, f"ค่าจ้าง {rnd.cook_wage or 0:,.2f} บาท"), vendor_step,
                 com_step, doc_step, menu_step, ing_step, order_step,
                 dict(title="เบิกจ่ายและปิดรอบ", done=paid,
                      detail=("จ่ายแล้ว ระบบลงบัญชีให้แล้ว" if paid
                              else "ออกเอกสารขอเบิกจ่ายค่าจ้างและส่งใช้เงินยืม แล้วตั้งสถานะรอบเป็น \"จ่ายแล้ว\""),
                      href=f"/lunch/{pid}/rounds", cta="ตั้งสถานะรอบ")]
    else:
        steps = [period_step(), com_step, doc_step, menu_step, ing_step,
                 dict(title="ส่งใช้เงินยืมและปิดรอบ", done=paid,
                      detail=("จ่ายแล้ว ระบบลงบัญชีให้แล้ว" if paid
                              else "ออกเอกสารส่งใช้เงินยืม แล้วตั้งสถานะรอบเป็น \"จ่ายแล้ว\""),
                      href=f"/lunch/{pid}/rounds", cta="ตั้งสถานะรอบ")]
    if not doc_total:                      # รูปแบบที่ไม่มีเลขที่หนังสือให้กรอก ไม่ต้องมีขั้นนี้
        steps = [st for st in steps if st is not doc_step]
    return _pack(steps)


# ---------------- บุคคล: ข้อมูลรายคนครบหรือยัง ----------------
def person_checks(p) -> list:
    """[{label, ok, why}] ของบุคลากรหนึ่งคน เฉพาะช่องที่เอกสารในระบบใช้จริง (เจ้าของขอเช็กลิสต์รายคน)
    วิทยฐานะถามเฉพาะครูและผู้บริหาร (นักการ/ธุรการไม่มีวิทยฐานะ)"""
    digits = "".join(ch for ch in (p.id_card or "") if ch.isdigit())
    items = [
        ("ตำแหน่ง", bool((p.position or "").strip()), "ใช้ในใบลา ไปราชการ และเอกสารที่ลงนาม"),
    ]
    if (p.person_type or "ครู") in ("ครู", "ผู้บริหาร"):
        items.append(("วิทยฐานะ/ระดับ", bool((p.rank or "").strip()), "เช่น ครู คศ.1 ใช้ในหนังสือรับรอง"))
    items += [
        ("เลขบัตรประชาชน 13 หลัก", len(digits) == 13, "ใช้ในหนังสือรับรองหักภาษี ณ ที่จ่าย และหนังสือรับรอง"),
        ("วันเกิด", bool(p.birthdate), "ใช้ในหนังสือรับรองบุคลากร"),
        ("วันบรรจุ/เริ่มงาน", bool(p.start_date), "ใช้คิดสิทธิ์วันลาพักผ่อนและในหนังสือรับรอง"),
        ("เงินเดือน", bool(p.salary), "ใช้ในหนังสือรับรองเงินเดือน"),
        ("อีเมล", "@" in (p.email or ""), "รับแจ้งเตือนเมื่อใบลาหรือคำขอได้รับอนุมัติ"),
        ("ลายเซ็น", bool((p.signature or "").strip()), "ระบบแปะลายเซ็นลงเอกสารให้เอง อัปโหลดที่หน้าบุคลากร/ฝ่าย"),
    ]
    return [dict(label=a, ok=b, why=c) for a, b, c in items]
