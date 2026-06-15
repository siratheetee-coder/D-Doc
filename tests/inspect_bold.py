# -*- coding: utf-8 -*-
"""ลิสต์เฉพาะย่อหน้าที่มีตัวหนา (bold) ในไฟล์ docx"""
import sys
from docx import Document
d = Document(sys.argv[1])
print(f"=== ย่อหน้าที่มีตัวหนา: {sys.argv[1]} ===")
for i, p in enumerate(d.paragraphs):
    bolds = [r.text for r in p.runs if r.font.bold and r.text.strip()]
    if bolds:
        full = p.text.strip()[:70]
        print(f"[P{i}] BOLD={bolds} | {full}")
