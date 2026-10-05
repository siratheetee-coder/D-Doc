"""The printed sheet uses exactly the draft/immutable snapshot passed by the router."""
from docx.shared import Cm, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from uuid import uuid4
from app.services.finance_forms_doc import _new, _save, _grid, _row
from app.services.build_templates import _p
from app.services.subsidy import NAMES, keys_for


def render(school, data, snapshot_id=None):
    doc = _new(landscape=True)
    cfg, result = data['config'], data['result']
    def amount(n):
        return f'{n:,.2f}' if n is not None else '—'
    def table(headers, widths, rows):
        ws = [Cm(w) for w in widths]
        t = _grid(doc, headers, ws, size=14)
        for row in rows:
            _row(t, [str(x) for x in row], ws, ['left']+['right']*(len(headers)-1), size=14)
        borders = OxmlElement('w:tblBorders')
        for edge in ('top','left','bottom','right','insideH','insideV'):
            el=OxmlElement('w:'+edge)
            for key,value in [('val','single'),('sz','4'),('color','D9D9D9')]:
                el.set(qn('w:'+key),value)
            borders.append(el)
        t._tbl.tblPr.append(borders)
        for cell in t.rows[0].cells:
            fill=OxmlElement('w:shd');fill.set(qn('w:fill'),'F1F4F6')
            cell._tc.get_or_add_tcPr().append(fill)
    title = _p(doc, 'กระดาษคำนวณเงินอุดหนุนเรียนฟรี 15 ปี', bold=True, size=20, align='center')
    title.style = 'Title'
    # Word's bundled Title style can inherit a blue paragraph border.
    for element in (title._p, doc.styles['Title'].element):
        for border in list(element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    no_border = OxmlElement('w:pBdr')
    for edge in ('top','bottom','left','right','between','bar'):
        el=OxmlElement('w:'+edge);el.set(qn('w:val'),'nil');no_border.append(el)
    title._p.get_or_add_pPr().append(no_border)
    for run in title.runs:
        run.font.color.rgb = RGBColor(0,0,0)
    _p(doc, school.name or '', align='center', size=16)
    _p(doc, f"ปีการศึกษา {data['academic_year']} ภาคเรียนที่ {data['term']} · อัตราปีงบประมาณ {data['fiscal_year']}", align='center')
    _p(doc, f'ฉบับยืนยัน #{snapshot_id}' if snapshot_id else 'ร่าง — ข้อมูลที่บันทึกล่าสุด ยังไม่ใช่ฉบับยืนยัน', bold=True, align='center')
    _p(doc, 'ประมาณการงวดปรับยอด = ยอดเต็มตามฐานล่าสุด − จัดสรรงวดแรก (หากยังไม่แจ้ง ใช้ประมาณการ 70%)', size=14)
    table(['รายการ', 'ประมาณการ\nงวดแรก', 'จัดสรรจริง\nงวดแรก', 'ประมาณการ\nเต็มเทอม', 'งวดปรับยอด\nที่คำนวณ', 'จัดสรรจริง\nงวดปรับยอด'], [6,3.6,3.6,3.6,3.6,3.6], [
        [r['name']]+[amount(r[k]) for k in ('first_estimate','first','full','remaining','second')] for r in result['rows']])
    _p(doc, f"รวมประมาณการเต็มเทอม {amount(result['total'])} บาท", bold=True)
    _p(doc, 'เงินรับจริงต้องตรวจจากรายการโอนที่เชื่อมแยกต่างหาก ยอดติดลบเป็นจุดตรวจสอบกับหนังสือจัดสรร ไม่ใช่คำสั่งคืนเงิน', size=14)
    if result['missing']:
        _p(doc, f"ยังมีข้อมูลต้องตรวจ {len(result['missing'])} จุด กรุณาตรวจช่องที่แสดง — และข้อมูล DMC ในหน้าคำนวณก่อนใช้งาน", size=14)
    _p(doc, 'หนังสือจัดสรรงวดแรก: ' + (cfg['first_ref'] or 'ยังไม่แจ้ง'), size=14)
    _p(doc, 'หนังสือจัดสรรงวดปรับยอด: ' + (cfg['second_ref'] or 'ยังไม่แจ้ง'), size=14)
    for k, extra in cfg['extras'].items():
        _p(doc, f"{NAMES[k]} {amount(extra['amount'])} บาท · {extra['ref']}", size=14)
    doc.add_page_break()
    _p(doc, 'ฐานข้อมูลประกอบการคำนวณ', bold=True, size=18)
    keys = keys_for(data['term'])
    table(['ชั้น']+[NAMES[k]+'\nบาท/คน/เทอม' for k in keys], [2]+[22/len(keys)]*len(keys), [
        [lv]+[amount(cfg['rates'].get(lv,{}).get(k)) for k in keys] for lv in cfg['levels']])
    _p(doc, 'จำนวนนักเรียนที่ใช้คำนวณ (คน)', bold=True)
    table(['ชั้นรับเงิน','ชั้นต้นทางงวดแรก','ฐานงวดแรก','ฐานล่าสุด'], [6]*4, [
        [b['level'],b['source_level'],b['advance'] if b['advance'] is not None else '—',b['final'] if b['final'] is not None else '—'] for b in result['basis']])
    for scan in data['census']:
        _p(doc, f"DMC {scan['label']}: {scan['source'] or 'ยังไม่ระบุแหล่งข้อมูล'} · {'ตรวจแล้ว' if scan['confirmed'] else 'ร่าง'}", size=14)
    if cfg.get('note'):
        _p(doc, 'หมายเหตุ: '+cfg['note'], size=14)
    return _save(doc, f"เงินอุดหนุน_{data['academic_year']}_เทอม{data['term']}_{snapshot_id or 'ร่าง'}_{uuid4().hex[:12]}")
