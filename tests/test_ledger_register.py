from datetime import datetime
from pathlib import Path
import os
import pytest
from starlette.datastructures import FormData
from fastapi import HTTPException
from app import models as m
from app.services import doc_number as dn,doc_register as reg,finance_txn_edit as editor
from tests.test_subsidy import db,env


def txn(db,**kw):
    a=m.FinanceAccount(name='บัญชีทดสอบ',fund_type='เงินรายได้สถานศึกษา',deposit_type='bank')
    db.add(a);db.flush()
    t=m.FinanceTxn(account_id=a.id,fiscal_year=2570,date=datetime(2026,11,15),kind='out',amount=100,
                   note='ซื้อวัสดุ',**kw)
    db.add(t);db.commit();return t


def form(db,t,**kw):
    values=dict(version=editor.token(db,t),date='15/11/2569',kind='out',amount='250.25',note='แก้รายการ',
                category='วัสดุ',ref='ทดสอบ',remark='หมายเหตุ',place='bank',item_id='',eb_code='',due_date='',refund_date='')
    values.update(kw);return FormData(values)


def test_edit_recalculates_balance_and_receipt_without_duplicate(db):
    t=txn(db)
    r=m.Receipt(txn_id=t.id,amount=100,kind='จ่าย',receipt_no='ใบเสร็จเดิม',party='ร้านเดิม',account_id=t.account_id,fiscal_year=2570)
    db.add(r);db.commit()
    editor.save(db,t,form(db,t));db.commit()
    from app.services.asset_utils import account_balance_year
    assert account_balance_year(t.account,2570)==-250.25
    assert db.query(m.FinanceTxn).count()==1
    assert (r.amount,r.note,r.receipt_no,r.party)==(250.25,'แก้รายการ','ใบเสร็จเดิม','ร้านเดิม')


@pytest.mark.parametrize('values',[{'amount':'NaN'},{'amount':'-1'},{'amount':'1.234'},{'amount':'inf'},
    {'date':'15/11/2568'},{'date':'bad'},{'kind':'bad'},{'place':'wrong'}, {'item_id':'999'},
    {'eb_code':'not-code'},{'note':''},{'due_date':'bad'}])
def test_invalid_edit_does_not_change_money(db,values):
    t=txn(db)
    with pytest.raises(ValueError):editor.save(db,t,form(db,t,**values))
    db.rollback();assert db.get(m.FinanceTxn,t.id).amount==100


def test_stale_edit_and_foreign_category_rejected(db):
    t=txn(db);f=form(db,t);t.note='เปลี่ยนจากอีกหน้าต่าง';db.commit()
    with pytest.raises(ValueError,match='เปลี่ยนแปลง'):editor.save(db,t,f)
    a=m.FinanceAccount(name='อีกบัญชี');db.add(a);db.flush()
    item=m.AccountItem(account_id=a.id,fiscal_year=2570,name='คนละบัญชี');db.add(item);db.commit()
    with pytest.raises(ValueError,match='หมวดเงิน'):editor.save(db,t,form(db,t,item_id=str(item.id)))


@pytest.mark.parametrize('link',['memo','loan','lunch','check','wht','revenue','transfer','subsidy'])
def test_linked_transactions_cannot_be_edited_directly(db,link):
    t=txn(db)
    if link=='memo':t.disburse_id=11
    if link=='loan':t.loan_id=12
    if link=='transfer':t.no_count=True
    if link=='lunch':db.add(m.LunchLedger(program_id=1,finance_txn_id=t.id))
    if link=='check':db.add(m.CheckPayment(txn_id=t.id,fiscal_year=2570))
    if link=='wht':db.add(m.WithholdingCertificate(txn_id=t.id))
    if link=='revenue':db.add(m.RevenueRemit(txn_id=t.id,fiscal_year=2570,date=t.date,account_id=t.account_id,rtype='other'))
    if link=='subsidy':db.add(m.SubsidyReceiptLink(txn_id=t.id,academic_year=2569,term=2,item_key='teach',round=1,amount=100))
    db.commit()
    assert editor.source(db,t)
    with pytest.raises(ValueError,match='ต้นทาง'):editor.save(db,t,form(db,t))
    assert t.amount==100


def test_duplicate_order_keeps_original_owner(db):
    a=m.SchoolOrder(fiscal_year=2569,order_no='80/2569',subject='เจ้าของเดิม')
    db.add(a);db.flush();dn.commit_doc_no(db,'command',2569,a.order_no,source='admin',ref_id=a.id,subject=a.subject);db.commit()
    with pytest.raises(HTTPException) as error:
        dn.commit_doc_no(db,'command',2569,a.order_no,source='procurement',ref_id=99,subject='เจ้าของใหม่')
    assert error.value.status_code==409
    db.rollback();assert db.query(m.IssuedDocNo).one().source=='admin'


def test_source_only_numbers_prevent_reuse_and_counter_never_rewinds(db):
    a=m.SchoolOrder(fiscal_year=2569,order_no='80/2569',subject='คำสั่งที่ทะเบียนตกหล่น')
    db.add(a);db.commit()
    assert dn.suggest_next(db,'command',2569)==81
    dn.commit_doc_no(db,'command',2569,a.order_no,source='admin',ref_id=a.id)
    dn.remove_issued(db,'admin',a.id,'command');db.delete(a);db.commit()
    item=next(x for x in reg.summary(db,{t:2569 for t in dn.COUNTER_TYPES}) if x['label']=='คำสั่ง')
    assert item['last']=='—' and item['next']=='81/2569' and item['gap']


@pytest.mark.parametrize('text,expected',[('ศธ 04002/45',45),('ศธ 04002/ว 45',45),('45/2569',45),('ศธ 45/2569',45),('',0),('-',0)])
def test_outgoing_sequence_ignores_ministry_prefix(text,expected):assert dn.parse_outgoing_seq(text)==expected


def test_register_projects_incoming_and_duplicate_sources_without_changing_data(db):
    db.add(m.IncomingLetter(fiscal_year=2570,calendar_year=2569,recv_no=8,recv_date=datetime(2026,11,15),subject='หนังสือรับ'))
    db.add(m.SchoolOrder(fiscal_year=2569,order_no='5/2569',subject='คำสั่งธุรการ'))
    db.add(m.Procurement(fiscal_year=2569,command_no='5/2569',subject='คำสั่งพัสดุ'))
    db.commit()
    rows=reg.records(db)
    assert len([r for r in rows if r.doc_type=='incoming' and r.seq==8])==1
    assert len([r for r in rows if r.doc_type=='command' and r.conflict])==2
    assert db.query(m.IssuedDocNo).count()==0


def test_incoming_unknown_year_remains_reserved_and_stale_rows_are_not_actual_documents(db):
    db.add(m.IncomingLetter(fiscal_year=2569,calendar_year=None,recv_no=99))
    db.add(m.IssuedDocNo(doc_type='command',fiscal_year=2569,seq=90,full_no='90/2569',source='admin',ref_id=999))
    db.commit()
    summary=reg.summary(db,{t:2569 for t in dn.COUNTER_TYPES})
    incoming=next(r for r in summary if r['label']=='หนังสือรับ')
    commands=next(r for r in summary if r['label']=='คำสั่ง')
    assert incoming['next']=='100/2569' and incoming['last']=='—'
    assert commands['last']=='—' and commands['next']=='91/2569'
    assert dn.suggest_next(db,'incoming',2569)==100
    assert dn.suggest_next(db,'command',2569)==91


def test_import_outgoing_reads_sequence_after_official_prefix(db):
    from openpyxl import Workbook
    from io import BytesIO
    from app.services.admin_io import import_admin_workbook
    wb=Workbook();ws=wb.active;ws.title='หนังสือส่ง'
    ws.append(['ชื่อทะเบียน']);ws.append(['เลข','วันที่','ถึง','เรื่อง'])
    ws.append(['ศธ 04002/ว 45','15/11/2569','หน่วยงาน','หนังสือนำเข้า'])
    stream=BytesIO();wb.save(stream)
    import_admin_workbook(stream.getvalue(),db)
    assert db.query(m.OutgoingLetter).one().send_seq==45
    assert dn.suggest_next(db,'outgoing',2569)==46


def test_http_ledger_edit_register_and_conflict(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        t=txn(db);tid=t.id;aid=t.account_id
        r=env.get(f'/finance/txn/{tid}/edit');assert r.status_code==200,r.text[:200]
        capture=Path(os.environ['LEDGER_CAPTURE'])
        (capture/'editor.html').write_text(r.text,encoding='utf-8')
        f=dict(form(db,t));r=env.post(f'/finance/txn/{tid}/edit',data=f,follow_redirects=False)
        assert r.status_code==303,r.text[:300]
        db.expire_all();assert db.get(m.FinanceTxn,tid).amount==250.25
        r=env.get(f'/finance/accounts/{aid}?year=2570&txn_saved=1');assert r.status_code==200
        assert f'/finance/txn/{tid}/edit' in r.text
        (capture/'ledger.html').write_text(r.text,encoding='utf-8')
        assert env.post(f'/finance/txn/{tid}/edit',data=f).status_code==409
        assert env.get('/finance/txn/999999/edit').status_code==404
        r=env.get('/docnos?year=2569');assert r.status_code==200,r.text[:200]
        (capture/'register.html').write_text(r.text,encoding='utf-8')
        r=env.post('/admin/orders',data={'fiscal_year':'2569','order_no':'800/2569','subject':'คำสั่งทดสอบ'},follow_redirects=False)
        assert r.status_code==303,r.text
        r=env.post('/admin/orders',data={'fiscal_year':'2569','order_no':'800/2569','subject':'เลขชน'},follow_redirects=False)
        assert r.status_code==409,r.text
        db.expire_all();assert db.query(m.SchoolOrder).filter_by(order_no='800/2569').count()==1
        r=env.post('/admin/outgoing',data={'fiscal_year':'2570','send_no':'ศธ 04002/81','date':'15/11/2569','subject':'เลขส่งทดสอบ'},follow_redirects=False)
        assert r.status_code==303,r.text
        assert env.get('/docnos?year=2569').status_code==200
        assert env.get('/docnos/register.docx?year=2569').status_code==200
        assert env.get('/docnos/register.docx').status_code==200
        r=env.get('/admin/outgoing');assert r.status_code==200 and 'เลขส่งทดสอบ' in r.text
        r=env.get('/admin/letters/export.xlsx?year=2569');assert r.status_code==200
        from openpyxl import load_workbook
        from io import BytesIO
        wb=load_workbook(BytesIO(r.content))
        assert any('เลขส่งทดสอบ' in str(row) for row in wb['หนังสือส่ง'].values)
        p=m.Procurement(fiscal_year=2570,proc_type='ซื้อ',subject='ทดสอบคัดลอก',memo_no='1000/2569')
        db.add(p);db.commit()
        from app.routers.pages import _sync_proc_docnos
        _sync_proc_docnos(db,p);db.commit()
        r=env.post(f'/procurement/{p.id}/duplicate',follow_redirects=False)
        assert r.status_code==303,r.text[:200]
        new_id=int(r.headers['location'].split('/')[2]);db.expire_all()
        new=db.get(m.Procurement,new_id)
        assert new.memo_no!='1000/2569'
        assert db.query(m.IssuedDocNo).filter_by(source='procurement',ref_id=new_id).count()==1
        db.add(m.IncomingLetter(calendar_year=2569,fiscal_year=2570,recv_no=8,recv_date=datetime(2026,11,15),subject='แจ้งการจัดสรรงบประมาณ'))
        db.commit()
        r=env.get('/docnos?year=2569');assert r.status_code==200
        (capture/'register.html').write_text(r.text,encoding='utf-8')
        t=db.get(m.FinanceTxn,tid);t.disburse_id=999;db.commit()
        r=env.get(f'/finance/txn/{tid}/edit');assert r.status_code==200 and 'เปิดงานต้นทาง' in r.text
        assert env.post(f'/finance/txn/{tid}/edit',data=dict(form(db,t))).status_code==409
    finally:db.close()
