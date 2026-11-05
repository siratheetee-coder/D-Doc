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
    assert 'ทำเรื่องเบิกค่าเดินทางแล้ว' in page and 'โครงการ พัฒนาครู' in page
    from app.services.budget import project_spent
    with tn.session_for(tid) as s:
        assert project_spent(s.get(Project, pid)) == 1200


def test_activity_groups_procurement_and_other_expense(env):
    import app.tenancy as tn
    from app.models import ProjectActivity
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        pj = Project(name='โครงการกีฬาสี', plan_year=2569, budget=20000); s.add(pj); s.commit(); pid = pj.id
    env.post(f'/projects/{pid}/activities', data={'name': 'แข่งกีฬาภายใน', 'budget': '8000'})
    env.post(f'/projects/{pid}/activities', data={'name': 'ประกวดกองเชียร์', 'budget': ''})
    with tn.session_for(tid) as s:
        a1, a2 = [a.id for a in s.query(ProjectActivity).filter_by(project_id=pid).order_by(ProjectActivity.seq)]
        s.add(Procurement(subject='อุปกรณ์กีฬา', fiscal_year=2569, project_id=pid, activity_id=a1, total_amount=5000))
        s.commit()
    form = env.get(f'/finance/disburse?project={pid}&activity={a1}').text
    assert f'data-selected="{a1}"' in form and 'PJ_ACTS' in form
    env.post('/finance/disburse', data={'fiscal_year': '2570', 'subject': 'ค่าตอบแทนกรรมการตัดสิน', 'payee': 'นายเอ',
                                        'amount': '1200', 'proc_kind': 'ค่าใช้จ่ายอื่น', 'project_id': str(pid),
                                        'activity_id': str(a1)})
    # กิจกรรมของโครงการอื่นใส่มาไม่ได้
    env.post('/finance/disburse', data={'fiscal_year': '2570', 'subject': 'ค่าอาหาร', 'payee': 'ร้านบี',
                                        'amount': '300', 'proc_kind': 'ค่าใช้จ่ายอื่น', 'project_id': '',
                                        'activity_id': str(a1)})
    with tn.session_for(tid) as s:
        assert s.query(DisburseMemo).filter_by(subject='ค่าอาหาร').one().activity_id is None
    page = env.get(f'/projects/{pid}').text
    blk = page.split(f'data-act="{a1}"')[1].split(f'data-act="{a2}"')[0]
    assert 'อุปกรณ์กีฬา' in blk and 'ค่าตอบแทนกรรมการตัดสิน' in blk and '>เหลือ</small>' in blk and '1,800 <em>บาท</em>' in blk
    assert f'href="/finance/disburse?project={pid}&activity={a1}"' in page
    # ลบกิจกรรม: เอกสารยังอยู่ ย้ายไปกลุ่มยังไม่ระบุกิจกรรม
    env.post(f'/projects/{pid}/activities/{a1}/delete')
    page = env.get(f'/projects/{pid}').text
    assert 'รายการที่ยังไม่ได้ผูกกับกิจกรรม' in page and 'อุปกรณ์กีฬา' in page and 'ค่าตอบแทนกรรมการตัดสิน' in page
    # ย้ายกลับเข้ากิจกรรมจากหน้าโครงการ
    with tn.session_for(tid) as s:
        proc_id = s.query(Procurement).filter_by(subject='อุปกรณ์กีฬา').one().id
    env.post(f'/projects/{pid}/assign', data={'kind': 'proc', 'doc_id': str(proc_id), 'activity_id': str(a2)})
    with tn.session_for(tid) as s:
        assert s.get(Procurement, proc_id).activity_id == a2
    assert '>เอาออกจากกิจกรรม</option>' in env.get(f'/projects/{pid}').text
    env.post(f'/projects/{pid}/assign', data={'kind': 'proc', 'doc_id': str(proc_id), 'activity_id': ''})
    with tn.session_for(tid) as s:
        assert s.get(Procurement, proc_id).activity_id is None
    lst = env.get('/projects?year=2569').text
    assert 'id="pjFind"' in lst and f'"id": {pid}' in lst


def test_disburse_memo_from_procurement_not_listed_twice(env):
    """ทำเรื่องจัดซื้อแล้วเบิกจ่ายจากเรื่องนั้น: หน้าโครงการขึ้นแถวเดียว (จัดซื้อ) ไม่ขึ้น "เบิกค่าอื่น" ซ้ำ"""
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        pj = Project(name='โครงการพัฒนาบุคลากร', plan_year=2569, budget=20000); s.add(pj); s.flush()
        pr = Procurement(subject='วัสดุอบรมครู', fiscal_year=2569, project_id=pj.id, total_amount=4500)
        s.add(pr); s.flush()
        s.add(DisburseMemo(subject='ขอเบิกเงินค่าวัสดุอบรมครู', fiscal_year=2569, project_id=pj.id,
                           procurement_id=pr.id, amount=4500, proc_kind='จัดซื้อ'))
        s.add(DisburseMemo(subject='ค่าตอบแทนวิทยากร', fiscal_year=2569, project_id=pj.id,
                           amount=1000, proc_kind='ค่าใช้จ่ายอื่น'))
        s.commit(); pid = pj.id
    page = env.get(f'/projects/{pid}').text
    assert 'ขอเบิกเงินค่าวัสดุอบรมครู' not in page          # แถวซ้ำจากเรื่องจัดซื้อ
    assert 'วัสดุอบรมครู' in page and 'ค่าตอบแทนวิทยากร' in page
    assert '5,500.00' in page and '10,000.00' not in page    # ยอดใช้รวม 4,500 + 1,000 ไม่นับซ้ำ


def test_procurement_status_follows_paid_memo(env):
    """ลงจ่ายบันทึกขอเบิกของเรื่องจัดซื้อครบ -> เรื่องเป็น "เบิกจ่ายแล้ว" ยกเลิกจ่าย -> ถอยกลับ"""
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        pr = Procurement(subject='จ้างถ่ายเอกสาร', fiscal_year=2569, total_amount=1400, status='ร่าง')
        s.add(pr); s.flush()
        m = DisburseMemo(subject='ขอเบิกค่าถ่ายเอกสาร', fiscal_year=2569, procurement_id=pr.id,
                         amount=1400, status='อนุมัติ')
        s.add(m); s.commit(); prid, mid = pr.id, m.id
        assert s.get(Procurement, prid).status == 'ร่าง'          # ยังไม่จ่าย ไม่เปลี่ยน
        s.get(DisburseMemo, mid).status = 'จ่ายแล้ว'; s.commit()
        assert s.get(Procurement, prid).status == 'เบิกจ่ายแล้ว'
        s.get(DisburseMemo, mid).status = 'อนุมัติ'; s.commit()   # ยกเลิกการเชื่อมรายการจ่าย
        assert s.get(Procurement, prid).status == 'อนุมัติ'


def test_procurement_status_partial_payment_and_backfill(env):
    import app.tenancy as tn
    from app.services.proc_paid import backfill
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        pr = Procurement(subject='ซื้อวัสดุ', fiscal_year=2569, total_amount=4000, status='ร่าง')
        old = Procurement(subject='เรื่องเก่าจ่ายแล้ว', fiscal_year=2569, total_amount=1800, status='ร่าง')
        s.add_all([pr, old]); s.flush()
        s.add(DisburseMemo(subject='งวด 1', fiscal_year=2569, procurement_id=pr.id, amount=2000, status='จ่ายแล้ว'))
        s.add(DisburseMemo(subject='งวด 2', fiscal_year=2569, procurement_id=pr.id, amount=2000, status='อนุมัติ'))
        s.commit(); prid, oid = pr.id, old.id
        assert s.get(Procurement, prid).status == 'ร่าง'          # จ่ายแค่บางงวด ยังไม่ครบ
        # ข้อมูลเดิมก่อนมีตัวฟัง: เขียนตรงลงฐานข้อมูล แล้วให้ backfill แก้
        s.execute(__import__('sqlalchemy').text(
            "INSERT INTO disburse_memo (fiscal_year, subject, procurement_id, amount, status) "
            "VALUES (2569, 'เก่า', :p, 1800, 'จ่ายแล้ว')"), {"p": oid})
        s.commit()
    backfill(tn._engines[tid][0])
    with tn.session_for(tid) as s:
        assert s.get(Procurement, oid).status == 'เบิกจ่ายแล้ว'
        assert s.get(Procurement, prid).status == 'ร่าง'
