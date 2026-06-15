# -*- coding: utf-8 -*-
"""ตรวจว่าตารางมีแถวสรุป VAT/รวมทั้งสิ้น/คำอ่าน ถูกต้องทั้งกรณีมี/ไม่มี VAT"""
import tempfile, os
from types import SimpleNamespace as NS
from docxtpl import DocxTemplate
from docx import Document
from app.services.render import build_context, TEMPLATES_DIR

class Sch:
    name="โรงเรียนทดสอบ"; address="ต.ก อ.ข จ.ค"; director_name="นายเอ"; officer_name="นายบี"
    head_officer_name="นายซี"; doc_prefix="ศธ"; director_position="ผู้อำนวยการโรงเรียน"

def mkproc(vat):
    items=[NS(name="ปากกา",quantity=2,unit="กล่อง",unit_price=100,amount=200),
           NS(name="กระดาษ",quantity=1,unit="รีม",unit_price=110,amount=110)]
    return NS(items=items, committees=[], memo_no="1/2569", request_date=None, proc_type="ซื้อ",
              subject="วัสดุ", project_name="โครงการ X", department="วิชาการ", purpose="ใช้สอน",
              method="เฉพาะเจาะจง", budget_source="อุดหนุน", delivery_days=5, total_amount=310,
              inspection_mode="single", vendor=None, spec_memo_no="", order_no="1/2569",
              command_no="", result_memo_no="", penalty_rate=0.2, vat_mode=("include" if vat else "none"),
              order_signer="director", overdue_days=0, delivery_note_no="", delivery_note_book="",
              order_date=None, delivery_due_date=None, inspect_date=None)

for vat in (False, True):
    tpl=DocxTemplate(str(TEMPLATES_DIR/"ใบสั่งซื้อจ้าง.docx"))
    tpl.render(build_context(mkproc(vat), Sch()))
    f=os.path.join(tempfile.gettempdir(), f"vt_{vat}.docx"); tpl.save(f)
    d=Document(f); t=d.tables[0]
    print(f"\n===== VAT={vat} : table rows =====")
    for r in t.rows:
        print(" | ".join(c.text.strip() for c in r.cells))
