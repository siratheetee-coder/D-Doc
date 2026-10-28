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
