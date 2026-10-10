"""PP7 grade certificate: explicit historical identity, frozen issue payload."""
from collections import defaultdict
from datetime import datetime
from app.models import AcadStudent, AcadClass, AcadSubject, AcadScore, Student
from app.thai_utils import is_secondary


def history(db, student, start, end):
    if not 2500 <= start <= end <= 2800 or end-start > 12:
        raise ValueError('เลือกช่วงปีการศึกษาไม่เกิน 13 ปี และปีเริ่มต้นไม่เกินปีสิ้นสุด')
    q=db.query(AcadStudent).join(AcadClass).filter(AcadClass.year.between(start,end))
    q=q.filter(AcadStudent.student_id==student.student_id) if student.student_id else q.filter(AcadStudent.id==student.id)
    records=q.order_by(AcadClass.year,AcadClass.id).all()
    warnings=[];groups=[]
    if not student.student_id:
        warnings.append('นักเรียนยังไม่เชื่อมทะเบียนกลาง จึงแสดงได้เฉพาะข้อมูลห้องนี้ ไม่จับคู่ประวัติจากชื่อ')
    for year in range(start,end+1):
        if not any(s.klass.year==year for s in records):warnings.append(f'ไม่พบประวัตินักเรียนปี {year}')
    seen=set()
    for s in records:
        key=(s.klass.year,s.klass.level)
        if key in seen:
            raise ValueError(f'พบประวัติห้องซ้ำปี {key[0]} ชั้น {key[1]} กรุณาตรวจทะเบียนก่อนออกเอกสาร')
        seen.add(key)
        subs=db.query(AcadSubject).filter_by(year=s.klass.year,level=s.klass.level).order_by(AcadSubject.term,AcadSubject.kind,AcadSubject.seq,AcadSubject.code).all()
        scores={(x.subject_id,x.term):x for x in db.query(AcadScore).filter_by(acad_student_id=s.id)}
        terms=sorted({x.term or 0 for x in subs})
        if not subs:warnings.append(f'ยังไม่มีรายวิชาปี {key[0]} ชั้น {key[1]}')
        for term in terms:
            rows=[]
            for sub in subs:
                if (sub.term or 0)!=term:continue
                score=scores.get((sub.id,term))
                grade=(score.grade or '').strip() if score else ''
                weight=float((sub.credit if is_secondary(s.klass.level) else sub.hours) or 0)
                if not grade:warnings.append(f'ยังไม่มีผลการเรียน {key[0]} {sub.code} {sub.name}'+(f' เทอม {term}' if term else ' รายปี'))
                if weight<=0:warnings.append(f'ยังไม่ระบุเวลาเรียน/หน่วยกิต {key[0]} {sub.code} {sub.name}')
                rows.append(dict(code=sub.code or '',name=sub.name,kind=sub.kind or '',grade=grade,weight=weight,group=sub.learn_group or ''))
            groups.append(dict(year=key[0],level=key[1],term=term,unit='หน่วยกิต' if is_secondary(s.klass.level) else 'ชั่วโมง',rows=rows))
    if not groups:warnings.append('ไม่มีผลการเรียนในช่วงปีที่เลือก')
    return groups,warnings,records


def average(rows):
    total=points=0
    for r in rows:
        try:g=float(r['grade'])
        except (ValueError,TypeError):return None
        if not 0<=g<=4 or r['weight']<=0:return None
        total+=r['weight'];points+=g*r['weight']
    from app.services.academic import weighted_avg
    return weighted_avg([(r['grade'],r['weight']) for r in rows]) if total else None


def render(payload, output):
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from app.services.doc_page import set_a4
    from app.services.build_templates import _font, _krut_center, _no_split_row
    from app.services.cash_report import _set_cell, _p
    doc=Document();set_a4(doc);_font(doc)
    sec=doc.sections[0];sec.left_margin=sec.right_margin=Cm(1.2)
    sec.top_margin=sec.bottom_margin=Cm(1.2)
    groups=payload['groups']
    # Three parallel panels; split large histories into subsequent pages, never shrink to illegibility.
    panels=[]
    for g in groups:
        for offset in range(0,len(g['rows']),22):
            panels.append([(g,g['rows'][offset:offset+22],offset>0)])
    packed=[]
    for panel in panels:
        if packed and sum(len(x[1])+3 for x in packed[-1])+len(panel[0][1])+3<=28:
            packed[-1].extend(panel)
        else:packed.append(panel)
    panels=packed
    for page in range(0,len(panels),3):
        if page:doc.add_page_break()
        _p(doc,'ปพ.7',align='right',size=11,after=0)
        _krut_center(doc,height_cm=1.4)
        _p(doc,'ใบรับรองผลการเรียน',align='center',bold=True,size=17,after=2)
        _p(doc,f"เลขที่ {payload['number']}   โรงเรียน{payload['school'].removeprefix('โรงเรียน')}",size=13,after=0)
        _p(doc,f"ขอรับรองว่า {payload['name']}   เลขประจำตัวนักเรียน {payload['student_no']}",size=13,after=0)
        _p(doc,f"เลขประจำตัวประชาชน {payload['id_card'] or '...........................'}   เกิดวันที่ {payload['birthdate'] or '...........................'}",size=12,after=0)
        _p(doc,f"ชื่อบิดา {payload['father'] or '...........................'}   ชื่อมารดา {payload['mother'] or '...........................'}",size=12,after=0)
        _p(doc,f"{payload['status']} โดยมีรายวิชาและผลการเรียนในช่วงปี {payload['start']}–{payload['end']} ดังนี้",size=12,after=3)
        outer=doc.add_table(rows=1,cols=3);outer.autofit=False
        for c in outer.columns:c.width=Cm(6.2)
        for col,panel in enumerate(panels[page:page+3]):
            cell=outer.cell(0,col);cell.width=Cm(6.2)
            for g,rows,continued in panel:
                title_cell=cell.add_table(rows=1,cols=1).cell(0,0)
                _set_cell(title_cell,f"ปี {g['year']} {g['level']}"+(f" ภาค {g['term']}" if g['term'] else ' ทั้งปี')+(' (ต่อ)' if continued else ''),bold=True,size=11)
                t=cell.add_table(rows=1,cols=3);t.style='Table Grid';t.autofit=False
                for c,w in zip(t.columns,[4.2,1,0.7]):c.width=Cm(w)
                for c,text,w in zip(t.rows[0].cells,['รหัส / รายวิชา','ชม.' if g['unit']=='ชั่วโมง' else 'นก.','ผล'],[4.2,1,0.7]):
                    c.width=Cm(w);_set_cell(c,text,bold=True,size=10)
                for r in rows:
                    cells=t.add_row().cells
                    for c,text,w in zip(cells,[f"{r['code']} {r['name']}",f"{r['weight']:g}",r['grade'] or '—'],[4.2,1,0.7]):
                        c.width=Cm(w);_set_cell(c,text,size=11)
                    _no_split_row(t.rows[-1])
                if rows[-1] is g['rows'][-1]:
                    avg=average(g['rows'])
                    p=cell.add_paragraph('ผลการเรียนเฉลี่ย '+(f'{avg:.2f}' if avg is not None else '— (ข้อมูลไม่ครบ/มีผลที่ไม่ใช่ตัวเลข)'))
                    for r in p.runs:r.font.size=Pt(10)
        _p(doc,'',after=2)
        if page+3>=len(panels) and len({g['unit'] for g in groups})==1:
            avg=average([r for g in groups for r in g['rows']]) if not payload['warnings'] else None
            _p(doc,'ผลการเรียนเฉลี่ยรวมช่วงปีที่รับรอง: '+(f'{avg:.2f}' if avg is not None else '— (ข้อมูลยังไม่ครบหรือมีผลที่ไม่ใช่ตัวเลข)'),size=12,bold=True)
        _p(doc,f"ออกให้ ณ วันที่ {payload['issued']}   ใบรับรองมีอายุ {payload['valid_days']} วันนับแต่วันที่ออก",size=12,after=2)
        footer=doc.add_table(rows=1,cols=3)
        _set_cell(footer.cell(0,0),'ติดรูปถ่าย\nนักเรียน\nขนาด 2 นิ้ว',align='center',size=12)
        _set_cell(footer.cell(0,1),f"ลงชื่อ....................................\n({payload['registrar']})\nนายทะเบียน",align='center',size=12)
        _set_cell(footer.cell(0,2),f"ลงชื่อ....................................\n({payload['director']})\nผู้อำนวยการโรงเรียน",align='center',size=12)
        if payload['warnings']:_p(doc,'แสดงเฉพาะข้อมูลที่มีในระบบ ช่อง — หมายถึงยังไม่มีข้อมูล ไม่ใช่ผลการเรียน 0',size=10)
    def normalize(container):
        for p in container.paragraphs:
            p.paragraph_format.space_before=Pt(0)
            p.paragraph_format.line_spacing=1
            if not p.text and not p._element.xpath('.//w:drawing'):
                p.paragraph_format.space_after=Pt(0)
                p.paragraph_format.line_spacing=Pt(1)
                p.add_run('').font.size=Pt(1)
            for r in p.runs:
                size=r.font.size.pt if r.font.size else 11
                r.font.name='TH Sarabun New'
                pr=r._element.get_or_add_rPr()
                cs=pr.find(qn('w:szCs'))
                if cs is None:cs=OxmlElement('w:szCs');pr.append(cs)
                cs.set(qn('w:val'),str(int(size*2)))
        for t in container.tables:
            for row in t.rows:
                for c in row.cells:normalize(c)
    normalize(doc)
    doc.save(output)
    return str(output)
