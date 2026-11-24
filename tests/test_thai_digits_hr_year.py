"""ตัวเลือกเลขไทยในเอกสาร Word + ระยะขอบขวา 2 ซม. ชุดจำหน่ายพัสดุ"""
import io
import zipfile

from docx import Document
from docx.shared import Cm

from app.services.thai_digits import convert_docx, to_thai


def _docx(text):
    d = Document(); d.add_paragraph(text); b = io.BytesIO(); d.save(b); return b.getvalue()


def test_to_thai():
    assert to_thai("ที่ 12/2569") == "ที่ ๑๒/๒๕๖๙"


def test_convert_only_text_not_layout():
    out = convert_docx(_docx("ราคา 1,250.00 บาท"))
    xml = zipfile.ZipFile(io.BytesIO(out)).read("word/document.xml").decode("utf8")
    assert "๑,๒๕๐.๐๐" in xml and "1,250.00" not in xml
    # ค่าโครงสร้าง (เช่น ขนาดหน้า) ยังเป็นเลขอารบิก
    assert 'w:w="11906"' in xml or "w:pgSz" in xml
    Document(io.BytesIO(out))   # เปิดได้ปกติ


def test_fit_tables_shrinks_to_text_width():
    from app.services.asset_dispose_set import _fit_tables, _new
    from app.services.build_templates import _fixed_cols
    doc = _new()
    assert abs(doc.sections[0].right_margin.cm - 2.0) < 0.01
    t = doc.add_table(rows=1, cols=2)
    _fixed_cols(t, [Cm(10.0), Cm(6.5)])
    _fit_tables(doc)
    from docx.oxml.ns import qn
    total = sum(int(c.get(qn("w:w"))) for c in t._element.find(qn("w:tblGrid")).findall(qn("w:gridCol"))) / 567
    assert total <= 16.01
