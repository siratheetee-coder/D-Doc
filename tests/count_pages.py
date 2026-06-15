# -*- coding: utf-8 -*-
"""นับจำนวนหน้าจริงของรายงานขอซื้อ (โหมดคณะกรรมการ 3 คน) ผ่าน Word COM
คาดหวัง: 2 หน้า (หน้า 1 = บันทึก, หน้า 2 = รายละเอียดแนบท้าย)"""
import os, tempfile
from types import SimpleNamespace as NS
from datetime import datetime
from docxtpl import DocxTemplate
from app.services.render import build_context, TEMPLATES_DIR, TEMPLATE_FILES

class Sch:
    name="โรงเรียนบ้านหินลาด"; address="หมู่ 23 ต.ท่าสองคอน อ.เมือง จ.มหาสารคาม 44000"
    director_name="นายอัครพงศ์ ศรีวงศ์"; officer_name="นายสิรธีร์ ตีเมืองซ้าย"
    head_officer_name="นายสิรธีร์ ตีเมืองซ้าย"; doc_prefix="ศธ"; director_position="ผู้อำนวยการโรงเรียน"
    finance_officer_name="นางกองแก้ว"

members=[NS(name="นายสิรธีร์ ตีเมืองซ้าย",position="ครู",role="ประธานกรรมการ"),
         NS(name="ว่าที่ร้อยตรีเกริกไกร สุขเพลีย",position="ครู",role="กรรมการ"),
         NS(name="นายเนติพงษ์ มาตราเรียง",position="ครู",role="กรรมการและเลขานุการ")]
proc=NS(items=[NS(name="วัสดุโครงการสถานศึกษาสีขาว",quantity=1,unit="รายการ",unit_price=10000,amount=10000)],
        committees=[NS(kind="inspect",members=members)], memo_no="2/2569", spec_memo_no="",
        inspect_memo_no="", result_memo_no="", request_date=datetime(2026,6,8), proc_type="ซื้อ",
        subject="วัสดุโครงการสถานศึกษาสีขาว", project_name="สถานศึกษาสีขาว", department="ฝ่ายบริหารงานทั่วไป",
        purpose="เพื่อใช้ในการปฏิบัติราชการ", method="เฉพาะเจาะจง", budget_source="อุดหนุน", delivery_days=7,
        total_amount=10000, inspection_mode="committee", vendor=None, order_no="", command_no="",
        penalty_rate=0.1, vat_mode="none", order_signer="director", overdue_days=0,
        delivery_note_no="", delivery_note_book="", order_date=datetime(2026,6,8),
        delivery_due_date=None, inspect_date=None)

tpl=DocxTemplate(str(TEMPLATES_DIR/TEMPLATE_FILES["รายงานขอซื้อ"]))
tpl.render(build_context(proc, Sch()))
f=os.path.join(tempfile.gettempdir(),"count.docx"); tpl.save(f)

import win32com.client as win32
word=win32.Dispatch("Word.Application"); word.Visible=False
try:
    d=word.Documents.Open(f)
    d.Repaginate()
    pages=d.ComputeStatistics(2)  # wdStatisticPages
    print("จำนวนหน้า:", pages, "(คาดหวัง 2)")
    d.Close(False)
finally:
    word.Quit()
