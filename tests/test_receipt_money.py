from tests.test_subsidy import db, env
from app.models import FinanceAccount, FinanceTxn, Receipt
from app.services.receipt_money import eligible,release_for_deleted_txn


def test_receipt_links_and_original_survives_deletion(db):
    a=FinanceAccount(name='a');db.add(a);db.flush()
    t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='in',amount=500)
    r=Receipt(account_id=a.id,fiscal_year=2570,kind='รับ',amount=500)
    db.add_all([t,r]);db.flush()
    assert eligible(db,r,t)
    t.kind='out';assert not eligible(db,r,t);t.kind='in'
    r.txn_id=t.id;r.linked_existing=True;db.flush()
    other=Receipt(account_id=a.id,fiscal_year=2570,kind='รับ',amount=500);db.add(other);db.flush()
    assert not eligible(db,other,t)
    release_for_deleted_txn(db,t);db.delete(t);db.commit()
    assert db.get(Receipt,r.id) and r.txn_id is None


def test_receipt_http_link_and_unlink_no_extra_cash(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as db:
        a=FinanceAccount(name='receipt test');db.add(a);db.flush()
        t=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=500)
        r=Receipt(account_id=a.id,fiscal_year=2570,kind='จ่าย',amount=500)
        db.add_all([t,r]);db.commit();rid,tid,aid=r.id,t.id,a.id
    for _ in range(2):
        response=env.post(f'/finance/receipts/{rid}/link',data={'txn_id':tid})
        assert response.status_code==200 and 'เชื่อมรายการจ่ายแล้ว' in response.text
    with tn.session_for(sid) as db:
        assert db.query(FinanceTxn).filter_by(account_id=aid).count()==1
    env.post(f'/finance/receipts/{rid}/link',data={'mode':'unlink'})
    with tn.session_for(sid) as db: assert db.get(Receipt,rid).txn_id is None
    env.post(f'/finance/receipts/{rid}/link',data={'txn_id':tid})
    env.post(f'/finance/receipts/{rid}/delete')
    with tn.session_for(sid) as db: assert db.get(FinanceTxn,tid)
