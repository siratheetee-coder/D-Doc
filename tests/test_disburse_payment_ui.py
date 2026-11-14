from pathlib import Path
import os
from tests.test_subsidy import env
from tests.test_lunch_claim import make,create,session
from app.models import School,DisburseMemo,FinanceAccount,FinanceTxn,Procurement

def test_ready_panel_and_single_confirmation_form(env):
    x=make(env);mid=create(env,x)
    page=env.get(f'/finance/disburse/{mid}')
    assert page.status_code==200
    assert page.text.index('dm-payment-title')<page.text.index('id="disburse-details"')
    assert 'ยังไม่ได้บันทึกจ่ายเงินจริง' in page.text
    assert page.text.count(f'action="/finance/disburse/{mid}/post"')==1
    assert 'id="disburse-payment-dialog"' in page.text
    assert 'id="dm-payment-form"' in page.text
    assert 'id="disburse-details" open' not in page.text
    out=Path(os.environ['DM_UI_CAPTURE']);(out/'ready.html').write_text(page.text,encoding='utf-8')
    env.post(f'/finance/disburse/{mid}/post',data={'paid_date':'22/12/2569'})
    page=env.get(f'/finance/disburse/{mid}');assert page.status_code==200
    assert 'dm-payment dm-paid' in page.text and '22/12/2569' in page.text
    assert f'action="/finance/disburse/{mid}/post"' not in page.text
    assert 'ดูรายการจ่ายในทะเบียนคุมเงิน' in page.text
    assert 'lunch-cancel-payment' in page.text
    (out/'paid.html').write_text(page.text,encoding='utf-8')

def test_approval_and_stale_source_do_not_offer_payment_modal(env):
    x=make(env);mid=create(env,x)
    with session() as s:s.query(School).first().approval_on=True;s.commit()
    page=env.get(f'/finance/disburse/{mid}');assert page.status_code==200
    assert 'ส่งบันทึกให้ ผอ. อนุมัติก่อนจ่าย' in page.text
    assert 'id="disburse-payment-dialog"' not in page.text
    with session() as s:
        s.query(School).first().approval_on=False
        from app.models import LunchInstallment
        s.get(LunchInstallment,x['iid']).amount=7000;s.commit()
    page=env.get(f'/finance/disburse/{mid}')
    assert 'ตรวจข้อมูลงวดที่เปลี่ยน' in page.text and 'id="disburse-payment-dialog"' not in page.text

def test_missing_account_and_managed_source_keep_safeguards(env):
    with session() as s:
        acc=FinanceAccount(name='บัญชีทดสอบ');s.add(acc);s.flush()
        m=DisburseMemo(fiscal_year=2570,amount=1000,subject='บันทึกทั่วไป');s.add(m);s.commit();mid=m.id
    page=env.get(f'/finance/disburse/{mid}');assert page.status_code==200
    assert 'เลือกบัญชีที่จะจ่าย' in page.text and 'id="disburse-payment-dialog"' not in page.text
    x=make(env)
    with session() as s:
        proc=Procurement(fiscal_year=2570,subject='เรื่องอาหารกลางวัน',total_amount=7632);s.add(proc);s.flush()
        from app.models import LunchHireRound
        s.get(LunchHireRound,x['rid']).procurement_id=proc.id
        m=s.get(DisburseMemo,mid);m.procurement_id=proc.id;m.account_id=x['aid'];s.commit()
    page=env.get(f'/finance/disburse/{mid}')
    assert 'เชื่อมรายการจ่ายจากอาหารกลางวัน' in page.text and 'id="disburse-payment-dialog"' not in page.text

def test_generic_split_memo_modal_displays_all_accounts(env):
    from app.models import DisburseSplit
    with session() as s:
        a=FinanceAccount(name='บัญชีหนึ่ง');b=FinanceAccount(name='บัญชีสอง');s.add_all([a,b]);s.flush()
        m=DisburseMemo(fiscal_year=2570,amount=3000,wht=30,fine=0,account_id=a.id);s.add(m);s.flush()
        m.splits=[DisburseSplit(seq=1,account_id=a.id,amount=2000),DisburseSplit(seq=2,account_id=b.id,amount=1000)];s.commit();mid=m.id
    page=env.get(f'/finance/disburse/{mid}')
    assert page.status_code==200 and 'id="disburse-payment-dialog"' in page.text
    assert 'บัญชีหนึ่ง · 2,000.00 บาท' in page.text and 'บัญชีสอง · 1,000.00 บาท' in page.text
    assert '2,970.00' in page.text
