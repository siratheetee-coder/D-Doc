"""Read-only lunch overview: one selected program, existing workflow destinations."""
from datetime import datetime, timedelta, timezone

from app.models import LunchProgram
from app.services import lunch_calendar as calendar, lunch_claim, lunch_loan, lunch_meals, school_calendar


MODE_LABELS = {
    "hire": "จ้างเหมาประกอบอาหาร", "person": "ซื้อวัตถุดิบ + จ้างแม่ครัว",
    "ingredient": "ซื้อวัตถุดิบมาทำเอง", "self": "โรงเรียนดำเนินการเอง",
}


def _task(title, cta, href, icon="todo", tone="orange"):
    return dict(title=title, cta=cta, href=href, icon=icon, tone=tone)


def round_card(db, rnd, can_finance=False):
    """Display progress without changing round/ledger state or posting a payment."""
    prog = rnd.program
    plan = f"/lunch/round/{rnd.id}/plan"
    insts = sorted(rnd.installments, key=lambda i: (i.seq, i.id))
    claims = lunch_claim.view_map(db, rnd) if prog.operate_mode == "hire" else {}
    task = None
    level = 0
    labels = ["ส่งมอบ", "ตรวจรับ", "ขอเบิก", "จ่ายแล้ว"]
    amount = float(rnd.amount or 0)
    paid_count = sum(i.status == "จ่ายแล้ว" for i in insts)
    complete = rnd.status == "จ่ายแล้ว" or bool(insts and paid_count == len(insts))
    caption = ""

    if prog.operate_mode == "hire":
        if complete:
            level, status = 4, "จ่ายครบแล้ว"
            caption = f"จ่ายครบ {paid_count}/{len(insts)} งวด" if insts else "จ่ายทั้งรอบแล้ว"
        elif not insts:
            status = "รอแบ่งงวด"
            task = _task("ยังไม่ได้แบ่งงวดจ่ายเงิน", "แบ่งงวด", plan + "#installments")
        else:
            inst = next(i for i in insts if i.status != "จ่ายแล้ว")
            prefix = f"งวดที่ {inst.seq} "
            href = plan + f"#inst-{inst.id}"
            level = {"ส่งมอบแล้ว": 1, "ตรวจรับแล้ว": 2}.get(inst.status, 0)
            if level == 0:
                status = "รอส่งมอบ"
                task = _task(prefix + "รอส่งมอบงาน", "ส่งมอบงาน", href)
            elif level == 1:
                status = "รอตรวจรับ"
                task = _task(prefix + "รอตรวจรับ", "ตรวจรับ", href)
            else:
                by_round = lunch_meals.pays_by_round(rnd)
                if by_round and not all(i.status in lunch_meals.DONE_INSPECT for i in insts):
                    pending = next(i for i in insts if i.status not in lunch_meals.DONE_INSPECT)
                    status = "รอตรวจรับครบทุกงวด"
                    task = _task(f"งวดที่ {pending.seq} รอตรวจรับก่อนเบิกทั้งรอบ", "เปิดงวด",
                                 plan + f"#inst-{pending.id}")
                else:
                    key = f"r:{rnd.id}" if by_round else f"i:{inst.id}"
                    claim = claims.get(key)
                    level = 3 if claim else 2
                    status = "รอลงจ่ายในการเงิน" if claim else "รอทำเรื่องขอเบิก"
                    dest = (claim["url"] if claim else "/finance/disburse?" +
                            (f"lunch_round={rnd.id}" if by_round else f"lunch_inst={inst.id}"))
                    task = _task(("ทั้งรอบ " if by_round else prefix) + status,
                                 ("เปิดเรื่องขอเบิก" if claim else "ทำเรื่องขอเบิก") if can_finance else "ดูสถานะงวด",
                                 dest if can_finance else href, "f_disburse", "green")
            caption = f"จ่ายแล้ว {paid_count}/{len(insts)} งวด"
    elif prog.operate_mode in ("person", "ingredient"):
        loan = lunch_loan.state(rnd)
        from app.routers.lunch import round_spend
        amount = round_spend(rnd)
        labels = ["รับเงินยืม", "บันทึกซื้อ", "ส่งใช้", "ปิดรอบ"]
        if loan["stale"] or (loan["loan"] and loan["received"] and not loan["repaid"] and complete):
            complete = False
            status = "ตรวจยอดส่งใช้" if loan["stale"] else "รอส่งใช้เงินยืม"
            level = 2
            task = _task(status, "ตรวจเงินยืม", plan + "#repay", "f_loans", "purple")
        elif complete:
            level, status, caption = 4, "ปิดรอบแล้ว", "บันทึกปิดรอบแล้ว"
        elif not loan["received"]:
            status = "รอบันทึกเงินยืม"
            task = _task(status, "เปิดเงินยืม", plan + "#loan", "f_loans", "purple")
        else:
            served = set(calendar.round_days(rnd))
            recorded = {i.date.date() for i in prog.ingredients if i.date}
            level = 1
            if served and not served.issubset(recorded):
                status = "รอบันทึกวัตถุดิบ"
                task = _task(status, "บันทึกวัตถุดิบ", f"/lunch/{prog.id}/ingredients?back={plan}",
                             "p_material", "purple")
            elif not loan["repaid"]:
                level, status = 2, "รอส่งใช้เงินยืม"
                task = _task(status, "ส่งใช้เงินยืม", plan + "#repay", "f_loans", "purple")
            else:
                level, status = 3, "รอจ่ายค่าจ้างและปิดรอบ" if prog.operate_mode == "person" else "รอปิดรอบ"
                task = _task(status, "เปิดสรุปปิดรอบ", plan + "#close", "f_disburse", "green")
    else:
        status = "ดำเนินการแล้ว" if complete else "กำลังดำเนินการ"
        level = 4 if complete else 0
        if not complete:
            task = _task("ตรวจข้อมูลรอบดำเนินการ", "เปิดรอบ", plan)

    return dict(r=rnd, href=plan, amount=amount, complete=complete, status=status,
                level=level, labels=labels, caption=caption, task=task,
                mode=MODE_LABELS.get(prog.operate_mode, "อาหารกลางวัน"))


def overview(db, current_year, year=0, pid=0, can_finance=False, today=None):
    # Dates shown on the dashboard follow the school's timezone, including UTC hosts.
    today = today or datetime.now(timezone(timedelta(hours=7))).date()
    programs = (db.query(LunchProgram)
                .filter((LunchProgram.pool == 0) | LunchProgram.pool.is_(None))
                .order_by(LunchProgram.year.desc(), LunchProgram.id.desc()).all())
    years = sorted({current_year, *(p.year for p in programs if p.year)}, reverse=True)
    selected_year = year or (current_year if any(p.year == current_year for p in programs)
                             else programs[0].year if programs else current_year)
    if selected_year not in years:
        years = sorted([*years, selected_year], reverse=True)
    choices = [p for p in programs if p.year == selected_year]
    prog = next((p for p in choices if p.id == pid), choices[0] if choices else None)
    cards = []
    tasks = []
    menus = []
    paid = returned = 0.0
    if prog:
        paid = sum(float(l.amount or 0) for l in prog.ledger if l.kind == "out")
        returned = sum(float(l.amount or 0) for l in prog.ledger if l.kind == "in" and l.loan_return_id)
        menus = [m for m in prog.menus if m.date and m.date.date() == today]
        for rnd in sorted(prog.rounds, key=lambda r: (r.start_date or datetime.min, r.id)):
            card = round_card(db, rnd, can_finance)
            cards.append(card)
            if card["task"]:
                tasks.append(dict(card["task"], detail=f"{card['mode']} · รอบที่ {rnd.seq}"))
            # Flag actual differences only; the overview never realigns served days.
            if not card["complete"] and prog.operate_mode == "hire":
                affected = [i for i in rnd.installments if i.status in ("", "ร่าง") and i.start_date and i.end_date
                            and calendar.stored_days(i, prog) != school_calendar.days(db, prog.year, i.start_date, i.end_date)]
                if affected:
                    tasks.append(dict(_task("วันในงวดต่างจากปฏิทินโรงเรียน", "ตรวจวันในงวด",
                        f"/lunch/round/{rnd.id}/calendar-review", "calendar", "blue"),
                        detail=f"รอบที่ {rnd.seq} · {len(affected)} งวดที่ควรตรวจ"))
    # Prefer active rounds while retaining completed rounds in a compact list.
    cards.sort(key=lambda c: (c["complete"], -(c["r"].start_date or datetime.min).toordinal(), -c["r"].id))
    return dict(year=selected_year, years=years, programs=choices, program=prog, modes=MODE_LABELS,
                today=today, menus=menus, paid=round(paid-returned, 2), returned=returned,
                tasks=tasks, rounds=cards, task_count=len(tasks))
