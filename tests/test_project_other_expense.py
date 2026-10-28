"""โครงการเดียวใช้เงินหลายทาง: ส่วนจัดซื้อ + ค่าเดินทาง (เบิกค่าใช้จ่ายอื่น) หักงบโครงการเดียวกัน"""
from docx import Document

from tests.test_subsidy import db, env  # noqa: F401
from app.models import Project, Procurement, DisburseMemo, School


def test_other_expense_memo_counts_and_document_wording(db, monkeypatch, tmp_path):
    from app.services.budget import project_spent
    from app.services import finance_doc as fd
    pj = Project(name='พัฒนาครู', plan_year=2569, budget=10000)
    db.add(pj); db.flush()
    db.add(Procurement(subject='ซื้อวัสดุอบรม', fiscal_year=2569, project_id=pj.id, total_amount=3000))
    memo = DisburseMemo(subject='ค่าเดินทางไปอบรม', fiscal_year=2569, project_id=pj.id, amount=1500,
                        payee='ครูสมชาย', proc_kind='ค่าใช้จ่ายอื่น')
    db.add(memo); db.commit()
    assert project_spent(pj) == 4500                       # ทั้งจัดซื้อและค่าเดินทางหักโครงการเดียวกัน
    monkeypatch.setattr(fd, 'get_data_dir', lambda: tmp_path)
    text = '\n'.join(p.text for p in Document(fd.render_disburse(memo, db.query(School).first())).paragraphs)
    assert 'มีค่าใช้จ่ายเป็นค่าเดินทางไปอบรม' in text and 'ผู้มีสิทธิ์รับเงิน' in text
    assert 'ผู้ขายได้ส่งมอบงาน' not in text


def test_project_page_buttons_prefill_project(env):
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        pj = Project(name='โครงการทัศนศึกษา', plan_year=2569, budget=5000)
        s.add(pj); s.commit(); pid = pj.id
    page = env.get(f'/projects/{pid}').text
    assert f'href="/finance/disburse?project={pid}"' in page and f'href="/procurement/new?project={pid}"' in page
    form = env.get(f'/finance/disburse?project={pid}').text
    assert f'<option value="{pid}" selected>' in form
    assert '<option value="ค่าใช้จ่ายอื่น" selected>' in form
    assert f'&project={pid}"' in env.get(f'/procurement/new?project={pid}').text
    assert 'value="โครงการทัศนศึกษา"' in env.get(f'/procurement/new?case={next(iter(__import__("app.routers.pages", fromlist=["PROC_CASES"]).PROC_CASES))}&project={pid}').text


def test_travel_request_claim_button(env):
    import datetime as dt
    import app.tenancy as tn
    from app.models import Person, TravelRequest
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        p = Person(name='ครูสมหญิง'); pj = Project(name='พัฒนาครู', plan_year=2569, budget=8000)
        s.add_all([p, pj]); s.flush()
        tr = TravelRequest(person_id=p.id, subject='อบรมวิทยาการคำนวณ', place='ขอนแก่น', budget=1200,
                           start_date=dt.date(2026, 11, 2), end_date=dt.date(2026, 11, 3), status='approved', reimburse='yes')
        s.add(tr); s.commit(); rid, pid = tr.id, pj.id
    assert f'href="/finance/disburse?travel={rid}"' in env.get(f'/hr/travel-requests/{rid}').text
    form = env.get(f'/finance/disburse?travel={rid}').text
    assert 'value="ค่าใช้จ่ายในการเดินทางไปราชการ อบรมวิทยาการคำนวณ ณ ขอนแก่น"' in form
    assert 'value="ครูสมหญิง"' in form and 'value="1200.00"' in form
    assert f'name="travel_request_id" value="{rid}"' in form
    env.post('/finance/disburse', data={'fiscal_year': '2570', 'subject': 'ค่าเดินทาง', 'payee': 'ครูสมหญิง',
                                        'amount': '1200', 'proc_kind': 'ค่าใช้จ่ายอื่น', 'project_id': str(pid),
                                        'travel_request_id': str(rid)})
    page = env.get(f'/hr/travel-requests/{rid}').text
    assert 'ทำเรื่องเบิกค่าเดินทางแล้ว' in page and 'หักจากโครงการ พัฒนาครู' in page
    from app.services.budget import project_spent
    with tn.session_for(tid) as s:
        assert project_spent(s.get(Project, pid)) == 1200
