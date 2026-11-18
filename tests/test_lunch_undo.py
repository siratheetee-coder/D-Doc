from datetime import datetime
import pytest
from tests.test_subsidy import env
from tests.test_lunch_claim import make,create,session
from app.models import LunchInstallment,LunchLedger

def test_reverse_both_steps_clears_dates_and_rejects_stale_request(env):
    x=make(env)
    with session() as s:
        i=s.get(LunchInstallment,x['iid']);i.inspect_date=datetime(2026,12,15);i.deliver_date=datetime(2026,12,15);s.commit()
    url=f"/lunch/installment/{x['iid']}/undo-step"
    env.post(url,data={'expected_status':'ตรวจรับแล้ว'})
    with session() as s:
        i=s.get(LunchInstallment,x['iid']);assert i.status=='ส่งมอบแล้ว' and i.inspect_date is None and i.deliver_date is not None
    env.post(url,data={'expected_status':'ตรวจรับแล้ว'})
    with session() as s:assert s.get(LunchInstallment,x['iid']).status=='ส่งมอบแล้ว'
    env.post(url,data={'expected_status':'ส่งมอบแล้ว'})
    with session() as s:
        i=s.get(LunchInstallment,x['iid']);assert i.status=='ร่าง' and i.deliver_date is None
        assert s.query(LunchLedger).count()==0

@pytest.mark.parametrize('whole',[False,True])
def test_reverse_blocked_by_finance_memo_even_before_payment(env,whole):
    x=make(env,whole=whole);create(env,x)
    env.post(f"/lunch/installment/{x['iid']}/undo-step",data={'expected_status':'ตรวจรับแล้ว'})
    with session() as s:assert s.get(LunchInstallment,x['iid']).status=='ตรวจรับแล้ว'

def test_reverse_blocked_by_legacy_ledger(env):
    x=make(env)
    with session() as s:
        s.add(LunchLedger(program_id=x['pid'],installment_id=x['iid'],kind='out',amount=100));s.commit()
    env.post(f"/lunch/installment/{x['iid']}/undo-step",data={'expected_status':'ตรวจรับแล้ว'})
    with session() as s:
        assert s.get(LunchInstallment,x['iid']).status=='ตรวจรับแล้ว' and s.query(LunchLedger).count()==1
