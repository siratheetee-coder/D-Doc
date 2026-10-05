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
    values={i.id:amount(form.get('opening_'+str(i.id))) for i in items}
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
                raise ValueError('หมวดซ้ำหรือโครงสร้างไม่ตรง กรุณาตรวจบัญชี '+a.name)
            if matches:new=matches[0]
            else:
                new=AccountItem(account_id=a.id,fiscal_year=fy+1,name=old.name,parent_id=pid,budget=0,deposit_type=old.deposit_type,note=old.note)
                db.add(new);db.flush();target.append(new)
            if new.id in [x.id for x in mapped.values()]:
                raise ValueError('หมวดต้นทางชื่อซ้ำ กรุณาตรวจบัญชี '+a.name)
            new.opening_balance=item_remaining_asof(old)
            mapped[old.id]=new
        if any(i.id not in [x.id for x in mapped.values()] and (i.opening_balance or 0) for i in target):
            raise ValueError('มีหมวดปีใหม่ที่มียอดยกมาแต่ไม่มีคู่ในปีก่อน กรุณาตรวจบัญชี '+a.name)
        row=db.query(AccountOpening).filter_by(account_id=a.id,fiscal_year=fy+1).first()
        if row is None:row=AccountOpening(account_id=a.id,fiscal_year=fy+1);db.add(row)
        row.amount=account_balance_year(a,fy)
