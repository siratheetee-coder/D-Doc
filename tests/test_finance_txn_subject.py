"""Registers describe the case being paid, while money and original provenance stay intact."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import os
from docx import Document
from tests.test_subsidy import env, db
from app.models import FinanceAccount, FinanceTxn, DisburseMemo, Procurement, AccountItem
from app.services.finance_txn_text import payment_note, display_notes
from app.services import disburse_split as splits

def account(db):
    a=FinanceAccount(name='เงินอุดหนุน',fund_type='เงินนอกงบประมาณ',deposit_type='bank',opening_balance=59141.98)
    db.add(a);db.flush();return a

def test_new_and_updated_split_payment_notes_use_subject(db):
    a=account(db);b=FinanceAccount(name='เงินรายได้สถานศึกษา');db.add(b);db.flush()
    m=DisburseMemo(fiscal_year=2570,subject='ซื้อวัสดุสำนักงาน',payee='ร้านผู้รับเงิน',amount=4000,account_id=a.id)
    db.add(m);db.flush()
    splits.post(db,m);db.flush()
    first=db.query(FinanceTxn).filter_by(disburse_id=m.id).one()
    assert first.note=='จ่าย ซื้อวัสดุสำนักงาน'
    m.subject='ซื้ออุปกรณ์การเรียน'
    splits.apply(db,m,[{'account_id':a.id,'item_id':None,'amount':3000},{'account_id':b.id,'item_id':None,'amount':1000}])
    splits.sync(db,m,[first]);db.flush()
    rows=db.query(FinanceTxn).filter_by(disburse_id=m.id).order_by(FinanceTxn.id).all()
    assert len(rows)==2 and sum(t.amount for t in rows)==4000
    assert rows[0].note=='จ่าย ซื้ออุปกรณ์การเรียน (ส่วนที่ 1 จาก 2 ของยอด 4,000.00 บาท)'
    assert rows[1].note=='จ่าย ซื้ออุปกรณ์การเรียน (ส่วนที่ 2 จาก 2 ของยอด 4,000.00 บาท)'

def test_linked_legacy_notes_resolve_case_and_preserve_original_data(db):
    a=account(db)
    p=Procurement(fiscal_year=2570,subject='จ้างซ่อมเครื่องพิมพ์',total_amount=5400);db.add(p);db.flush()
    m=DisburseMemo(fiscal_year=2570,subject='',payee='นายผู้รับเงิน',procurement_id=p.id,amount=5400)
    db.add(m);db.flush()
    linked=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=3000,disburse_id=m.id,
                      note='จ่าย นายผู้รับเงิน (ส่วนที่ 1 จาก 2 ของยอด 5,400.00 บาท)',linked_existing=True,ref='227/2569')
    manual=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=25,note='จ่าย ค่าธรรมเนียมธนาคาร')
    income=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='in',amount=100,note='รับเงินบริจาค')
    db.add_all([linked,manual,income]);db.commit()
    original=[(t.id,t.amount,t.note,t.account_id,t.disburse_id,t.ref) for t in (linked,manual,income)]
    notes=display_notes([linked,manual,income],db)
    assert notes=={linked.id:'จ่าย จ้างซ่อมเครื่องพิมพ์ (ส่วนที่ 1 จาก 2 ของยอด 5,400.00 บาท)'}
    assert payment_note(m)=='จ่าย จ้างซ่อมเครื่องพิมพ์'
    assert [(t.id,t.amount,t.note,t.account_id,t.disburse_id,t.ref) for t in (linked,manual,income)]==original
    assert not db.dirty
    linked.disburse_id=None
    assert display_notes([linked],db)=={} and 'นายผู้รับเงิน' in linked.note

def test_missing_subject_is_explicit_and_never_uses_payee(db):
    m=DisburseMemo(fiscal_year=2570,subject=' ',payee='ร้านที่ไม่ใช่ชื่อเรื่อง')
    db.add(m);db.flush()
    assert payment_note(m)=='จ่าย (ยังไม่ระบุชื่อเรื่อง)'

def test_existing_register_docx_and_ledger_page_use_subject_without_reposting(env,monkeypatch,tmp_path):
    from app.tenancy import session_for
    from app.accounts import Account,acc_session
    from app.services import finance_forms_doc
    monkeypatch.setattr(finance_forms_doc,'get_data_dir',lambda:tmp_path)
    with acc_session() as adb: tid=adb.query(Account).filter_by(username='demo').one().tenant_id
    with session_for(tid) as db:
        a=account(db)
        item=AccountItem(account_id=a.id,fiscal_year=2570,name='ค่าจัดการเรียนการสอน',opening_balance=59141.98,deposit_type='bank')
        db.add(item);db.flush();aid,iid=a.id,item.id
        source=[('ซื้อวัสดุสำนักงาน','ร้านตัวอย่างศึกษาภัณฑ์',4000,'220/2569',5),
                ('ซื้ออุปกรณ์กีฬา','ร้านอุปกรณ์ตัวอย่าง',1400,'225/2569',5),
                ('จ้างซ่อมเครื่องพิมพ์','นายช่างตัวอย่าง',5400,'227/2569',12)]
        ids=[]
        for subject,payee,amount,ref,day in source:
            m=DisburseMemo(fiscal_year=2570,subject=subject,payee=payee,amount=amount,account_id=aid,item_id=iid,memo_no=ref)
            db.add(m);db.flush()
            t=FinanceTxn(fiscal_year=2570,account_id=aid,item_id=iid,disburse_id=m.id,kind='out',amount=amount,
                         note='จ่าย '+payee,ref=ref,date=datetime(2026,10,day))
            db.add(t);db.flush();ids.append(t.id)
        db.commit()
    response=env.get(f'/finance/accounts/{aid}/money-register.docx?year=2570&item={iid}')
    assert response.status_code==200
    doc=Document(BytesIO(response.content));rows=doc.tables[0].rows
    texts=[row.cells[2].text for row in rows]
    for subject,payee,amount,ref,day in source:
        assert 'จ่าย '+subject in texts and 'จ่าย '+payee not in texts
    tabletext=' '.join(c.text for row in rows for c in row.cells)
    assert '48,341.98' in tabletext and '10,800.00' in tabletext
    combined=env.get('/finance/registers.docx?year=2570')
    assert combined.status_code==200
    combinedtext=' '.join(c.text for table in Document(BytesIO(combined.content)).tables for row in table.rows for c in row.cells)
    assert 'จ่าย ซื้อวัสดุสำนักงาน' in combinedtext and 'จ่าย ร้านตัวอย่างศึกษาภัณฑ์' not in combinedtext
    page=env.get(f'/finance/accounts/{aid}?year=2570')
    assert page.status_code==200 and 'ซื้อวัสดุสำนักงาน' in page.text
    # Neither opening balances nor original transactions are rewritten during rendering.
    with session_for(tid) as db:
        rows=db.query(FinanceTxn).filter(FinanceTxn.id.in_(ids)).order_by(FinanceTxn.id).all()
        assert [r.note for r in rows]==['จ่าย '+s[1] for s in source]
        assert [r.amount for r in rows]==[4000,1400,5400]
        assert db.get(AccountItem,iid).opening_balance==59141.98
    folder=os.environ.get('REGISTER_SUBJECT_CAPTURE')
    if folder:
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        (folder/'register-subject.docx').write_bytes(response.content)
        (folder/'ledger.html').write_text(page.text,encoding='utf-8')


def test_subject_keywords_do_not_turn_disbursements_into_loan_debtors(db):
    from app.services.fin_registers import _is_debtor
    a=account(db)
    m=DisburseMemo(fiscal_year=2570,subject='ซื้อหนังสือสำหรับบริการยืมอ่าน',payee='ร้านหนังสือ',amount=100,account_id=a.id)
    db.add(m);db.flush();splits.post(db,m);db.flush()
    t=db.query(FinanceTxn).filter_by(disburse_id=m.id).one()
    assert 'ยืม' in t.note and not _is_debtor(t)
    loan=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=100,loan_id=99,note='จ่ายเงิน')
    assert _is_debtor(loan)
    manual=FinanceTxn(account_id=a.id,fiscal_year=2570,kind='out',amount=100,note='จ่ายเงินยืม')
    assert _is_debtor(manual)
