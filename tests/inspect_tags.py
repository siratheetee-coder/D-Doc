import zipfile, re
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "app" / "doc_templates" / "รายงานขอซื้อ.docx"
xml = zipfile.ZipFile(str(p)).read("word/document.xml").decode("utf-8")
for t in re.findall(r"\{%[^%]*%\}", xml):
    print(t)
