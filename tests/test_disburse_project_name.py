from tests.test_subsidy import db
from app.models import Project, Procurement, DisburseMemo, School
from app.services.finance_doc import _disburse_project_name, render_disburse
from docx import Document


def test_project_priority_and_procurement_fallback(db, monkeypatch, tmp_path):
    selected=Project(name='โครงการที่เลือกในบันทึก',plan_year=2569,active=False)
    linked=Project(name='โครงการจากเรื่องจัดซื้อ',plan_year=2569)
    db.add_all([selected,linked]);db.flush()
    proc=Procurement(subject='ซื้อวัสดุ',fiscal_year=2569,project_id=linked.id,project_name='ชื่อโครงการเดิม')
    db.add(proc);db.flush()
    memo=DisburseMemo(subject='ซื้อวัสดุ',fiscal_year=2569,project_id=selected.id,procurement_id=proc.id,note='ข้อความอื่น',amount=335)
    db.add(memo);db.commit()
    assert _disburse_project_name(memo)==selected.name
    import app.services.finance_doc as fd
    monkeypatch.setattr(fd,'get_data_dir',lambda:tmp_path)
    school=db.query(School).first()
    path=render_disburse(memo,school)
    text='\n'.join(p.text for p in Document(path).paragraphs)
    assert 'เพื่อใช้ในโครงการ/กิจกรรม '+selected.name in text
    assert 'เพื่อใช้ในโครงการ/กิจกรรม ข้อความอื่น' not in text
    memo.project_id=None
    assert _disburse_project_name(memo)==linked.name
    proc.project_id=None
    assert _disburse_project_name(memo)=='ชื่อโครงการเดิม'
    memo.procurement_id=None
    assert _disburse_project_name(memo)=='ข้อความอื่น'
    memo.note=''
    assert _disburse_project_name(memo)==''
