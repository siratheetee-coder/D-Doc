from datetime import datetime
from types import SimpleNamespace as N
from docx import Document
from docx.oxml.ns import qn

def test_leave_and_travel_keep_dotted_guides_and_field_widths(tmp_path,monkeypatch):
    from app.services import gov_forms as gf
    monkeypatch.setattr(gf,'get_data_dir',lambda:tmp_path)
    school=N(name='โรงเรียนบ้านตัวอย่าง',director_name='ผู้อำนวยการ ทดสอบ',director_position='ผู้อำนวยการโรงเรียน',area_office='สำนักงานเขตพื้นที่การศึกษาประถมศึกษามหาสารคาม เขต 1')
    leave=N(id=1,leave_type='personal',start_date=datetime(2026,11,3),end_date=datetime(2026,11,4),days=2,reason='ติดต่อราชการของครอบครัว',contact='บ้านเลขที่ 123 โทร. 0800000000',created_at=datetime(2026,11,1),year=None)
    travel=N(id=2,subject='อบรมพัฒนาการเรียนรู้',place='สำนักงานเขตพื้นที่การศึกษา',start_date=datetime(2026,11,3),end_date=datetime(2026,11,4),days=2,created_at=datetime(2026,11,1),purpose_type='อบรม',budget=2500,reimburse='yes',doc_ref='หนังสือเชิญ 123')
    for render,record,kwargs in [(gf.render_leave_official,leave,{'work_group':'กลุ่มสาระการเรียนรู้การงานอาชีพ'}),(gf.render_travel_official,travel,{})]:
        docs=[]
        for name,position in [('ครู ก','ครู'),('นางกัณฑ์ฉันทน์ รัตนสีหา','ครูชำนาญการพิเศษ')]:
            person=N(id=11,name=name,position=position,rank='ครู คศ.3')
            doc=Document(render(school,person,record,**kwargs));docs.append(doc)
            text='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
            assert name in text and position in text and 'มหาสารคาม' in text if render==gf.render_leave_official else name in text and position in text
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            assert not p._p.xpath('./w:pPr/w:jc[@w:val="distribute"]')
        def borders(doc):return len(doc.element.body.xpath('.//w:pBdr/w:bottom[@w:val="dotted"]'))
        assert borders(docs[0])==borders(docs[1]) and borders(docs[0])>=10
        def widths(doc):return [tc.get(qn('w:w')) for tc in doc.element.body.xpath('.//w:tbl/w:tr/w:tc/w:tcPr/w:tcW')]
        assert widths(docs[0])==widths(docs[1])
