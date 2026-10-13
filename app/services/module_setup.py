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
