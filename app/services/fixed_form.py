"""Fixed-width fields with dotted writing guides for printable forms."""
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def row(doc, anchor, fields, *, right=False, after=False):
    """fields: (label, value, label width cm, value width cm)."""
    table=doc.add_table(rows=1, cols=len(fields)*2)
    table.autofit=False
    table.alignment=WD_TABLE_ALIGNMENT.RIGHT if right else WD_TABLE_ALIGNMENT.LEFT
    table_width=table._tbl.tblPr.find(qn('w:tblW'))
    table_width.set(qn('w:type'),'dxa');table_width.set(qn('w:w'),str(Cm(sum(f[2]+f[3] for f in fields)).twips))
    borders=OxmlElement('w:tblBorders')
    for edge in ('top','bottom','left','right','insideH','insideV'):
        node=OxmlElement('w:'+edge);node.set(qn('w:val'),'nil');borders.append(node)
    table._tbl.tblPr.append(borders)
    trpr=table.rows[0]._tr.get_or_add_trPr();trpr.append(OxmlElement('w:cantSplit'))
    for i,(label,value,lw,vw) in enumerate(fields):
        for j,(text,width) in enumerate(((label,lw),(value,vw))):
            cell=table.cell(0,i*2+j);cell.width=Cm(width);table.columns[i*2+j].width=Cm(width)
            cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.TOP
            mar=OxmlElement('w:tcMar')
            for side in ('top','bottom','left','right'):
                edge=OxmlElement('w:'+side);edge.set(qn('w:w'),'0' if side in ('top','bottom') else '40');edge.set(qn('w:type'),'dxa');mar.append(edge)
            cell._tc.get_or_add_tcPr().append(mar)
            p=cell.paragraphs[0];p.alignment=WD_ALIGN_PARAGRAPH.LEFT
            pf=p.paragraph_format;pf.space_before=Pt(0);pf.space_after=Pt(0);pf.line_spacing=1.0;pf.keep_with_next=False
            run=p.add_run(str(text or '\u00a0'));run.font.name='TH Sarabun New';run.font.size=Pt(16)
            run._element.get_or_add_rPr().rFonts.set(qn('w:cs'),'TH Sarabun New')
            if j:
                border=OxmlElement('w:pBdr');line=OxmlElement('w:bottom')
                for key,val in [('val','dotted'),('sz','4'),('space','0'),('color','777777')]:line.set(qn('w:'+key),val)
                border.append(line);p._p.get_or_add_pPr().append(border)
    if after:anchor._p.addnext(table._tbl)
    else:
        anchor._p.addprevious(table._tbl)
        anchor._p.getparent().remove(anchor._p)
    # Word merges adjacent tables when opening a file, even if their widths differ.
    # A one-point separator keeps independent field rows at their intended widths.
    separator=OxmlElement('w:p');props=OxmlElement('w:pPr')
    spacing=OxmlElement('w:spacing')
    for key,val in [('before','0'),('after','0'),('line','20'),('lineRule','exact')]:spacing.set(qn('w:'+key),val)
    props.append(spacing);separator.append(props);table._tbl.addprevious(separator)
    return table

def left_align_body(doc):
    for p in doc.paragraphs:
        if p.alignment in (WD_ALIGN_PARAGRAPH.JUSTIFY,WD_ALIGN_PARAGRAPH.DISTRIBUTE,WD_ALIGN_PARAGRAPH.THAI_JUSTIFY):
            p.alignment=WD_ALIGN_PARAGRAPH.LEFT
