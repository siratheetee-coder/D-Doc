"""Cash openings are separate from budgets; parent values exclude child balances."""
from decimal import Decimal, InvalidOperation
from sqlalchemy import update
from app.models import School, AccountItem, AccountOpening, FinanceAccount
from app.services.asset_utils import opening_for, account_balance_year, item_remaining_asof
from app.services.subsidy import fingerprint


def token(db, account, fy):
    items = db.query(AccountItem).filter_by(account_id=account.id,fiscal_year=fy).order_by(AccountItem.id).all()
    return fingerprint([opening_for(account,fy),[[i.id,i.parent_id,i.opening_balance or 0] for i in items]])


def amount(raw):
    try:
        n=Decimal(str(raw))
        if not n.is_finite() or abs(n)>1_000_000_000: raise ValueError()
        return float(n.quantize(Decimal('.01')))
    except (ValueError,InvalidOperation):
        raise ValueError('กรอกยอดยกมาเป็นตัวเลขให้ครบทุกช่อง (ไม่มีให้กรอก 0)')


def save(db, account, fy, form):
    db.execute(update(School).values(id=School.id))
    if form.get('opening_token') != token(db,account,fy):
        raise ValueError('ยอดยกมาหรือหมวดเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่ก่อนบันทึก')
    total=amount(form.get('account_opening'))
    items=db.query(AccountItem).filter_by(account_id=account.id,fiscal_year=fy).all()
    parents={i.parent_id for i in items if i.parent_id is not None}
    values={i.id:(i.opening_balance or 0) if i.id in parents else amount(form.get('opening_'+str(i.id))) for i in items}
    if items and round(sum(values.values())-total,2)!=0:
        raise ValueError('ผลรวมยอดยกมาทุกหมวดต้องเท่ากับยอดยกมาของบัญชี โดยไม่นับยอดลูกซ้ำในหมวดแม่')
    for i in items:i.opening_balance=values[i.id]
    row=db.query(AccountOpening).filter_by(account_id=account.id,fiscal_year=fy).first()
    if row is None:
        row=AccountOpening(account_id=account.id,fiscal_year=fy);db.add(row)
    row.amount=total


def carry(db, fy):
    db.execute(update(School).values(id=School.id))
    for a in db.query(FinanceAccount).all():
        source=db.query(AccountItem).filter_by(account_id=a.id,fiscal_year=fy).order_by(AccountItem.id).all()
        target=db.query(AccountItem).filter_by(account_id=a.id,fiscal_year=fy+1).all()
        mapped={}
        for old in sorted(source,key=lambda i:(i.parent_id is not None,i.id)):
            parent=mapped.get(old.parent_id)
            pid=parent.id if parent else None
            matches=[i for i in target if i.name==old.name and i.parent_id==pid]
            if len(matches)>1 or (old.parent_id and not parent):
                raise ValueError(f'ยกยอดไม่ได้: บัญชี "{a.name}" ปีงบ {fy+1} มีหมวดชื่อ "{old.name}" ซ้ำกันหลายหมวด '
                                 f'หรือหมวดย่อยอยู่ใต้หมวดแม่คนละชื่อกับปีงบ {fy} ให้แก้ชื่อหมวดปีงบ {fy+1} ไม่ให้ซ้ำก่อน')
            if matches:new=matches[0]
            else:
                new=AccountItem(account_id=a.id,fiscal_year=fy+1,name=old.name,parent_id=pid,budget=0,deposit_type=old.deposit_type,note=old.note)
                db.add(new);db.flush();target.append(new)
            if new.id in [x.id for x in mapped.values()]:
                raise ValueError(f'ยกยอดไม่ได้: บัญชี "{a.name}" ปีงบ {fy} มีหมวดชื่อ "{old.name}" ซ้ำกัน '
                                 f'ให้แก้ชื่อหมวดปีงบ {fy} ไม่ให้ซ้ำก่อน')
            new.opening_balance=item_remaining_asof(old)
            if not (new.eb_slot or '') and (old.eb_slot or ''):   # ช่อง e-Budget ที่เลือกไว้ ตามไปปีใหม่
                new.eb_slot=old.eb_slot
            mapped[old.id]=new
        orphan=[i.name for i in target if i.id not in [x.id for x in mapped.values()] and (i.opening_balance or 0)]
        if orphan:
            # แต่ละบรรทัด = 1 ข้อ (หน้าการเงินแสดงบรรทัดแรกเป็นหัวข้อ ที่เหลือเป็น bullet)
            raise ValueError(f'ยกยอดไม่ได้ เพราะบัญชี "{a.name}" ปีงบ {fy+1} มีหมวด "{", ".join(orphan)}" ที่ปีงบ {fy} ไม่มี\n'
                             f'ถ้ายอดยกมาปีงบ {fy+1} ที่กรอกไว้ถูกแล้ว ไม่ต้องกดยกยอด\n'
                             f'ถ้าจะยกยอด ให้เปลี่ยนชื่อหมวดปีงบ {fy+1} ให้ตรงกับปีงบ {fy} ก่อน')
        row=db.query(AccountOpening).filter_by(account_id=a.id,fiscal_year=fy+1).first()
        if row is None:row=AccountOpening(account_id=a.id,fiscal_year=fy+1);db.add(row)
        row.amount=account_balance_year(a,fy)


def carry_status(db, fy) -> list:
    """บัญชีที่ยอดยกมาปีงบ fy ไม่ตรงกับยอดคงเหลือสิ้นปีงบ fy-1 -> ยอดทุกหน้าของปีงบ fy ผิดอยู่

    เกิดได้ 2 แบบ: ยังไม่ได้กดยกยอดเลย (ระบบใช้ยอดตั้งต้นของบัญชีแทน) หรือ
    ยกยอดแล้วแต่มีรายการปีก่อนเพิ่ม/แก้ทีหลัง · ตรวจเฉพาะบัญชีที่ปีก่อนมีความเคลื่อนไหว
    และเฉพาะเมื่อปีก่อนปิดไปแล้ว (ปีที่ยังไม่จบ ยอดยังเปลี่ยนได้ ไม่ต้องเตือน)
    """
    from app.thai_utils import current_fiscal_year
    from app.services.finance_health import _joined
    if fy > current_fiscal_year():
        return []
    # โรงเรียนเริ่มใช้ระบบที่ปีงบ fy (กรอกยอดยกมาเอง ปีก่อนไม่มีเงินเข้าเลย): รายการปีก่อนคือรายการก่อนเริ่มใช้ระบบ
    # ห้ามชวนให้ยกยอด (จะได้ยอดติดลบทับยอดยกมาจริง) · หน้าตรวจสุขภาพข้อมูลบอกให้ลบรายการพวกนั้นแทน
    if _joined(db, fy):
        return []
    out = []
    for a in db.query(FinanceAccount).order_by(FinanceAccount.name):
        prev = (any(t.fiscal_year == fy - 1 for t in a.txns)
                or any(o.fiscal_year == fy - 1 for o in (a.openings or [])))
        if not prev:
            continue
        want, got = account_balance_year(a, fy - 1), opening_for(a, fy)
        if round(want - got, 2) != 0:
            out.append({"name": a.name, "want": want, "got": got,
                        "carried": any(o.fiscal_year == fy for o in (a.openings or []))})
    return out
