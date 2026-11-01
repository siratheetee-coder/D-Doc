from datetime import date
from pathlib import Path
import os
from app.models import Person,TravelRequest,DisburseMemo
from app.services.dashboard_tasks import finance_tasks
from app.services.travel_claim import pending
from tests.test_subsidy import db,env

def test_queue_counts_pending_expense_requests_across_years(db):
    p=Person(name='ครูรอเบิก');db.add(p);db.flush()
    requests=[]
    for i in range(8):
        r=TravelRequest(person_id=p.id,status='approved',reimburse='yes',budget=100+i,start_date=date(2025 if i==0 else 2026,9,1),subject=f'อบรม {i}')
        db.add(r);requests.append(r)
    for status,flag in [('pending','yes'),('rejected','yes'),('approved','no'),('approved','')]:
        db.add(TravelRequest(person_id=p.id,status=status,reimburse=flag,budget=0))
    db.flush();db.add(DisburseMemo(fiscal_year=2568,travel_request_id=requests[-1].id,subject='ทำบันทึกแล้ว',amount=100));db.commit()
    cards=finance_tasks(db,2570)
    travel=next(c for c in cards if c.get('key')=='travel-claim')
    assert travel['count']==7 and len(travel['items'])==5
    assert pending(db).count()==7
    db.query(DisburseMemo).delete();db.commit()
    assert pending(db).count()==8

def test_finance_dashboard_queue_pages_and_create_link(env,tmp_path):
    import app.tenancy as tn
    tid=next(iter(tn._engines))
    with tn.session_for(tid) as db:
        p=Person(name='ครูอรุณ รักการสอน');db.add(p);db.flush()
        for i in range(32):db.add(TravelRequest(person_id=p.id,status='approved',reimburse='yes',budget=2500,subject=f'อบรมพัฒนาครู {i+1}',place='สำนักงานเขตพื้นที่การศึกษา',start_date=date(2026,9,15),end_date=date(2026,9,16)))
        db.commit()
    out=Path(os.environ.get('DDOC_QUEUE_QA_DIR',str(tmp_path)));out.mkdir(exist_ok=True)
    for url,name in [('/finance?year=2570','dashboard'),('/finance/travel-claims','queue'),('/finance/travel-claims?page=2','queue-page2'),('/hr','hr-dashboard')]:
        r=env.get(url);assert r.status_code==200,(url,r.text[:100])
        (out/(name+'.html')).write_text(r.text,encoding='utf-8')
    text=(out/'dashboard.html').read_text(encoding='utf-8')
    assert 'คำขอไปราชการรอทำเรื่องเบิก' in text and 'data-task="travel-claim"' in text
    from lxml import html
    doc=html.fromstring((out/'queue.html').read_text(encoding='utf-8'))
    links=doc.xpath('//article[contains(@class,"tcq-item")]//a/@href')
    assert len(links)==30
    assert len(html.fromstring((out/'queue-page2.html').read_text(encoding='utf-8')).xpath('//article[contains(@class,"tcq-item")]'))==2
    r=env.get(links[0]);assert r.status_code==200 and 'name="travel_request_id"' in r.text
