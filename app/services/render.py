"""
render.py
---------
เติมข้อมูลจากฐานข้อมูลลงแม่แบบ docxtpl แล้วบันทึกเป็นไฟล์ .docx

ฟังก์ชันหลัก:
  build_context(proc, school) -> dict   สร้างชุดข้อมูลสำหรับเติมลงแม่แบบ
  render_document(kind, proc, school)   เลือกแม่แบบตามชนิด แล้วสร้างไฟล์
"""
from pathlib import Path

from docxtpl import DocxTemplate
from docx import Document as _Docx
from docx.enum.text import WD_BREAK
from docxcompose.composer import Composer

from app.database import get_data_dir
from app.thai_utils import bahttext, thai_date, thai_date_official

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "doc_templates"

# ชนิดเอกสาร -> ชื่อไฟล์แม่แบบ
TEMPLATE_FILES = {
    "รายงานขอซื้อ": "รายงานขอซื้อ.docx",
    "ใบตรวจรับพัสดุ": "ใบตรวจรับพัสดุ.docx",
    "ใบสั่งซื้อ/สั่งจ้าง": "ใบสั่งซื้อจ้าง.docx",
    "รายงานผลการพิจารณา": "รายงานผลพิจารณา.docx",
    "คำสั่งแต่งตั้งผู้ตรวจรับ": "คำสั่งแต่งตั้ง.docx",
    "ใบเสนอราคา": "ใบเสนอราคา.docx",
    "ประกาศผู้ชนะ": "ประกาศผู้ชนะ.docx",
    "แต่งตั้งกรรมการคุณลักษณะ": "แต่งตั้งคุณลักษณะ.docx",
    "คำสั่งแต่งตั้งกรรมการคุณลักษณะ": "คำสั่งแต่งตั้งกรรมการคุณลักษณะ.docx",
    "คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง": "คำสั่งแต่งตั้งกรรมการซื้อจ้าง.docx",
    "รายละเอียดคุณลักษณะ(TOR)": "TOR.docx",
    "ใบส่งมอบงาน": "ใบส่งมอบงาน.docx",
    "รายงานผลตรวจรับและเบิกจ่าย": "รายงานเบิกจ่าย.docx",
}

_BLANK = ".............................."


def _d(dt) -> str:
    """วันที่ไทยแบบสั้น หรือจุดไข่ปลาถ้ายังไม่ระบุ"""
    return thai_date(dt) if dt else _BLANK


def _do(dt) -> str:
    """วันที่ไทยแบบเต็ม (หัวกระดาษ) หรือจุดไข่ปลาถ้ายังไม่ระบุ"""
    return thai_date_official(dt) if dt else _BLANK


def _money(x) -> str:
    """จัดรูปจำนวนเงิน: ตัด .00 ถ้าเป็นจำนวนเต็ม (ตามแบบฟอร์มราชการ) เช่น 3610 -> '3,610'"""
    x = round(float(x or 0), 2)
    if x == int(x):
        return f"{int(x):,}"
    return f"{x:,.2f}"


def _clean_project(name: str) -> str:
    """ตัดคำว่า 'โครงการ' ที่นำหน้าออก กันคำซ้ำ (เทมเพลตเติม 'โครงการ' ให้แล้ว)"""
    name = (name or "").strip()
    if name.startswith("โครงการ"):
        name = name[len("โครงการ"):].strip()
    return name


def _director_office(school) -> str:
    """คำลงท้าย 'ผู้อำนวยการโรงเรียน...' ให้รวมชื่อโรงเรียนถ้าทำได้"""
    name = (school.name or "").strip()
    if name.startswith("โรงเรียน"):
        return "ผู้อำนวยการ" + name
    return school.director_position or "ผู้อำนวยการโรงเรียน"


def _school_office(school) -> str:
    parts = [school.name or "", school.address or ""]
    return "  ".join(p for p in parts if p).strip()


def _find_committee(proc, kind):
    for c in proc.committees:
        if c.kind == kind:
            return c
    return None


def build_context(proc, school) -> dict:
    """รวบรวมข้อมูลทั้งหมดที่แม่แบบต้องใช้"""
    items = [{
        "name": it.name,
        "qty": f"{(it.quantity or 0):g}",
        # ตาราง TOR ใช้ชื่อ quantity · ตารางแนบท้ายเดิมใช้ qty จึงให้ทั้งสองชื่อ
        "quantity": f"{(it.quantity or 0):g}",
        "unit": it.unit,
        "spec": (getattr(it, "spec", "") or ""),   # คุณลักษณะเฉพาะรายรายการ (คอลัมน์ใน TOR)
        "unit_price": _money(it.unit_price),
        "amount": _money(it.amount),
    } for it in proc.items]

    # ผู้ตรวจรับ
    inspect = _find_committee(proc, "inspect")
    inspector_name = inspector_position = ""
    inspect_members = []
    if inspect:
        members = inspect.members
        if members:
            inspect_members = [{"name": m.name, "position": m.position, "role": m.role}
                               for m in members]
            inspector_name = members[0].name
            inspector_position = members[0].position

    # ผู้จัดทำร่างขอบเขตของงาน/รายละเอียดคุณลักษณะเฉพาะ (ระเบียบฯ ข้อ 21)
    # ข้อ 21 ให้เลือกได้ 2 ทาง: แต่งตั้งคณะกรรมการ หรือ มอบหมายบุคคลใดบุคคลหนึ่ง
    # โรงเรียนส่วนใหญ่ใช้ทางหลัง จึงต้องรองรับทั้งคู่ ไม่ใช่บังคับตั้งกรรมการ
    # (ไม่เอารายชื่อผู้ตรวจรับมาใส่แทน เพราะผู้ใช้จะไม่รู้ว่ามีชื่อคนอื่นโผล่ในเอกสาร)
    spec = _find_committee(proc, "spec")
    spec_members = ([{"name": m.name, "position": m.position, "role": m.role}
                     for m in spec.members] if spec and spec.members else [])
    spec_mode = spec_mode_of(proc)
    spec_drafter = (spec_members[0] if spec_members else {})

    # คณะกรรมการซื้อ/จ้าง (ไม่บังคับ) - ถ้าไม่มี = เจ้าหน้าที่ดำเนินการเอง
    purchase = _find_committee(proc, "purchase")
    purchase_members = ([{"name": m.name, "position": m.position, "role": m.role}
                         for m in purchase.members] if purchase and purchase.members else [])

    # ===== รายละเอียดการเงิน (สำหรับใบเบิกจ่าย) =====
    total = float(proc.total_amount or 0)
    if proc.vat_mode == "include":
        goods = round(total / 1.07, 2)
        vat = round(total - goods, 2)
    else:
        goods, vat = total, 0.0
    rate = float(proc.penalty_rate or 0.10)
    fine_num = round(total * rate / 100 * (proc.overdue_days or 0), 2)
    # ภาษีหัก ณ ที่จ่าย = อัตรา % ของมูลค่าก่อน VAT (goods); ปกติงานจ้าง/บริการ
    wht_num = round(goods * float(getattr(proc, "wht_rate", 0) or 0) / 100, 2)
    net = round(total - wht_num - fine_num, 2)

    return {
        "school_name": school.name or "",
        "school_address": (school.address or "") or _BLANK,
        "school_office": _school_office(school),
        "director_office": _director_office(school),
        "director_name": school.director_name or "",
        "officer_name": school.officer_name or "",
        "head_officer_name": school.head_officer_name or "",
        "doc_prefix": school.doc_prefix or "ศธ",

        "memo_no": proc.memo_no or "",
        "request_date": thai_date(proc.request_date),
        "request_date_official": thai_date_official(proc.request_date),
        "proc_type": proc.proc_type or "ซื้อ",
        "subject": proc.subject or "",
        "project_name": _clean_project(proc.project_name),
        "department": proc.department or "",
        "purpose": proc.purpose or "-",
        "method": proc.method or "เฉพาะเจาะจง",
        "budget_source": proc.budget_source or "อุดหนุน",
        "delivery_days": proc.delivery_days or 7,

        "item_count": len(items),
        "items": items,
        "total_amount": _money(proc.total_amount),
        "total_baht": bahttext(proc.total_amount or 0),

        "inspection_mode": proc.inspection_mode or "single",
        "inspector_name": inspector_name or "..............................",
        "inspector_position": inspector_position or "ครู",
        "inspect_members": inspect_members,
        "spec_members": spec_members,
        "spec_mode": spec_mode,
        "fiscal_year": proc.fiscal_year or "",
        # "จัดซื้อ"/"จัดจ้าง" สำหรับหัวเอกสาร (proc_type เป็น "ซื้อ"/"จ้าง" ใช้ต่อท้ายคำกริยา)
        "proc_word": ("จัดซื้อ" if (proc.proc_type or "ซื้อ") == "ซื้อ" else "จัดจ้าง"),
        "objective": (proc.objective or proc.purpose or "-"),
        "quote_valid_days": proc.quote_valid_days or 30,
        "warranty_text": proc.warranty_text or "1 ปี",
        "fix_days": proc.fix_days or 7,
        # มาตราที่รองรับวิธีที่เลือก (อ้างในคำสั่งแต่งตั้ง)
        "method_law": _METHOD_LAW.get((proc.method or "").strip(), ""),
        # คำสั่งมอบอำนาจของ สพฐ. - โรงเรียนกรอกเลขที่/วันที่ไว้ที่หน้าตั้งค่า
        "delegation_ref": (
            f"ตามคำสั่งสำนักงานคณะกรรมการการศึกษาขั้นพื้นฐาน ที่ {school.delegation_cmd_no} "
            f"ลงวันที่ {thai_date(school.delegation_cmd_date)}"
            if getattr(school, "delegation_cmd_no", "") else
            "ตามคำสั่งสำนักงานคณะกรรมการการศึกษาขั้นพื้นฐาน ที่ ................ "
            "ลงวันที่ ................"),
        "spec_drafter_name": spec_drafter.get("name") or "..............................",
        "spec_drafter_position": spec_drafter.get("position") or "เจ้าหน้าที่พัสดุ",
        # คำเรียกผู้จัดทำร่าง ใช้ทั้งหัวข้อและช่องลงนามใน TOR
        "spec_word": ("ผู้ได้รับมอบหมายให้จัดทำร่างขอบเขตของงานและรายละเอียดคุณลักษณะเฉพาะ"
                      if spec_mode == "single"
                      else "คณะกรรมการกำหนดรายละเอียดคุณลักษณะเฉพาะและราคากลาง"),
        # ซื้อ = รายละเอียดคุณลักษณะเฉพาะ · จ้าง = ขอบเขตของงาน (TOR)
        # เขียนรวมกันว่า "คุณลักษณะเฉพาะของงานจ้างที่จะจ้าง" ไม่ใช่คำที่ใช้กันจริง
        "spec_doc_title": ("รายละเอียดคุณลักษณะเฉพาะของพัสดุที่จะซื้อ"
                           if (proc.proc_type or "ซื้อ") == "ซื้อ"
                           else "ขอบเขตของงานจ้าง (Terms of Reference : TOR)"),
        "spec_doc_word": ("รายละเอียดคุณลักษณะเฉพาะ"
                          if (proc.proc_type or "ซื้อ") == "ซื้อ" else "ขอบเขตของงาน"),
        "purchase_members": purchase_members,
        # ผู้เจรจาตกลงราคาในรายงานผลการพิจารณา (มี กก.ซื้อ/จ้าง = คณะกรรมการ, ไม่มี = เจ้าหน้าที่)
        "negotiator": ("คณะกรรมการซื้อหรือจ้าง" if purchase_members else "เจ้าหน้าที่"),

        # สำหรับใบตรวจรับ / ใบสั่งซื้อ-จ้าง / เบิกจ่าย
        "vendor_name": (proc.vendor.name if proc.vendor else _BLANK),
        "vendor_address": (proc.vendor.address if proc.vendor else "") or _BLANK,
        "vendor_tax_id": (proc.vendor.tax_id if proc.vendor else "") or "-",
        "vendor_bank": (proc.vendor.bank_account if proc.vendor else "") or "-",
        "vendor_phone": (proc.vendor.phone if proc.vendor else "") or "-",
        # เจ้าของร้าน/ผู้มีอำนาจลงนาม
        "vendor_owner": (proc.vendor.owner_name if proc.vendor and proc.vendor.owner_name else "") or "",
        # ใช้ในเนื้อหาเอกสาร: "ชื่อร้าน โดย (ชื่อเจ้าของ)" ถ้ามีชื่อเจ้าของ
        "vendor_by": (
            f"{proc.vendor.name} โดย {proc.vendor.owner_name}"
            if proc.vendor and proc.vendor.owner_name
            else (proc.vendor.name if proc.vendor else _BLANK)
        ),
        # ชื่อที่ใช้ในช่องลงนาม: เจ้าของถ้ามี ไม่งั้นใช้ชื่อร้าน
        "vendor_signer": (
            proc.vendor.owner_name if proc.vendor and proc.vendor.owner_name
            else (proc.vendor.name if proc.vendor else _BLANK)
        ),
        "spec_memo_no": proc.spec_memo_no or "",
        "inspect_memo_no": getattr(proc, "inspect_memo_no", "") or "",
        "order_no": proc.order_no or "..............",
        "command_no": proc.command_no or "..............",
        "result_memo_no": proc.result_memo_no or "",
        "order_kind": ("ใบสั่งซื้อ" if proc.proc_type == "ซื้อ" else "ใบสั่งจ้าง"),
        "vendor_label": ("ผู้ขาย" if proc.proc_type == "ซื้อ" else "ผู้รับจ้าง"),
        "vendor_occupation": ("ขาย" if proc.proc_type == "ซื้อ" else "รับจ้าง"),
        # คำเรียกสิ่งที่จัดหา/ตรวจรับ/ส่งมอบ: งานซื้อ = "พัสดุ" · งานจ้าง = "งานจ้าง"
        # (ไม่ใช้กับชื่อกฎหมาย "การบริหารพัสดุภาครัฐ" หรือ "งานพัสดุ/เจ้าหน้าที่พัสดุ")
        "obj_word": ("พัสดุ" if proc.proc_type == "ซื้อ" else "งานจ้าง"),
        # หัวรายละเอียดแนบท้าย: งานซื้อ = "จัดซื้อพัสดุ" · งานจ้าง = "งานจัดจ้าง"
        # (ไม่ใช่ "จัดจ้างพัสดุ" เพราะงานจ้างไม่ได้ซื้อตัวพัสดุ)
        "attach_for": ("จัดซื้อพัสดุ" if proc.proc_type == "ซื้อ" else "งานจัดจ้าง"),
        "committee_word": (("คณะกรรมการตรวจรับพัสดุ" if proc.proc_type == "ซื้อ" else "คณะกรรมการตรวจรับงานจ้าง")
                           if (proc.inspection_mode or "single") == "committee"
                           else ("ผู้ตรวจรับพัสดุ" if proc.proc_type == "ซื้อ" else "ผู้ตรวจรับงานจ้าง")),
        "penalty_rate": f"{(proc.penalty_rate or 0.10):g}",
        # VAT
        "has_vat": (proc.vat_mode == "include"),
        "vat_note": ("ราคานี้รวมภาษีมูลค่าเพิ่มแล้ว"
                     if proc.vat_mode == "include" else "(โดยไม่คิดภาษีมูลค่าเพิ่ม)"),
        "price_ex_vat": _money(round((proc.total_amount or 0) / 1.07, 2)) if proc.vat_mode == "include" else _money(proc.total_amount),
        "vat_amount": _money(round((proc.total_amount or 0) - (proc.total_amount or 0) / 1.07, 2)) if proc.vat_mode == "include" else "0",
        # ผู้ลงนามใบสั่ง (เลือกได้)
        "signer_name": (school.head_officer_name if proc.order_signer == "head_officer" else school.director_name) or "",
        "signer_position": ("หัวหน้าเจ้าหน้าที่" if proc.order_signer == "head_officer" else _director_office(school)),
        # ค่าปรับอัตโนมัติ (ส่งเกินกำหนด)
        "overdue_days": proc.overdue_days or 0,
        "fine_amount": _money(round((proc.total_amount or 0) * (proc.penalty_rate or 0.10) / 100 * (proc.overdue_days or 0), 2)),
        "fine_baht": bahttext(round((proc.total_amount or 0) * (proc.penalty_rate or 0.10) / 100 * (proc.overdue_days or 0), 2)),
        # ใบส่งของ
        "delivery_note_no": proc.delivery_note_no or "..............",
        "delivery_note_book": proc.delivery_note_book or "..............",
        # วันที่ (แก้ไขได้ภายหลัง)
        "quotation_no": (getattr(proc, "quotation_no", "") or "").strip() or _BLANK,
        "quote_date_thai": _d(getattr(proc, "quotation_date", None) or proc.order_date),
        "order_date_thai": _d(proc.order_date),
        "order_date_official": _do(proc.order_date),
        "delivery_due_thai": _d(proc.delivery_due_date),
        # วันที่ส่งมอบจริง (ใบส่งมอบงาน) - ถ้าไม่ระบุใช้วันครบกำหนดส่งมอบแทน
        "delivery_date_thai": _d(getattr(proc, "delivery_date", None) or proc.delivery_due_date),
        "inspect_date_thai": _d(proc.inspect_date),
        "inspect_date_official": _do(proc.inspect_date),
        # วันที่เอกสารแต่ละชนิด (แยกอิสระ)
        "spec_date_thai": _d(proc.spec_memo_date),
        "result_date_thai": _d(proc.result_memo_date),
        "command_date_thai": _d(proc.command_date),
        "command_date_official": _do(proc.command_date),
        # ประกาศผู้ชนะ: ถ้าไม่ได้ระบุวันที่ประกาศ ใช้วันที่ใบสั่งแทน (พฤติกรรมเดิม)
        "winner_no": (getattr(proc, "winner_no", "") or "").strip() or _BLANK,
        "winner_date_thai": _d(getattr(proc, "winner_date", None) or proc.order_date),
        "spec_cmd_no": getattr(proc, "spec_cmd_no", "") or _BLANK,
        "spec_cmd_date_official": _do(getattr(proc, "spec_cmd_date", None)),
        "purchase_cmd_no": getattr(proc, "purchase_cmd_no", "") or _BLANK,
        "purchase_cmd_date_official": _do(getattr(proc, "purchase_cmd_date", None)),
        # รายละเอียดการเงิน (ใบเบิกจ่าย)
        "goods_value": _money(goods),
        "vat_value": _money(vat),
        "wht_amount": _money(wht_num),
        "net_pay": _money(net),
        "net_pay_baht": bahttext(net),
        "finance_officer_name": getattr(school, "finance_officer_name", "") or "",
    }


def _safe_filename(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _doc_seq(proc) -> str:
    """เลขที่ใช้ตั้งชื่อไฟล์: ใช้เลขใบสั่งซื้อ/จ้างก่อน ถ้ายังไม่มีใช้เลขบันทึก แล้วค่อย id"""
    seq = (proc.order_no or "").strip() or (proc.memo_no or "").strip() or str(proc.id)
    return seq.replace("/", "-")


def book_purchase_of(proc):
    """ถ้าเรื่องนี้สร้างมาจาก "จัดซื้อหนังสือเรียน" คืน TextbookPurchase · ไม่ใช่ = None"""
    from sqlalchemy.orm import object_session
    from app.models import TextbookPurchase
    db = object_session(proc)
    if db is None or not getattr(proc, "id", None):
        return None
    try:
        return db.query(TextbookPurchase).filter_by(procurement_id=proc.id).first()
    except Exception:
        return None


# เอกสารที่สร้างด้วยโค้ด (ไม่มีแม่แบบ .docx) - ต่อท้ายชุดเอกสารพัสดุ
WHT_KIND = "หนังสือรับรองการหักภาษี ณ ที่จ่าย (แบบ 4235)"


def render_proc_wht(proc, school) -> str:
    """หนังสือรับรองการหักภาษี ณ ที่จ่าย แบบ 4235 ของเรื่องจัดซื้อ/จ้าง
    ภาษี = อัตราหัก ณ ที่จ่ายของเรื่อง x มูลค่าก่อน VAT (สูตรเดียวกับใบเบิกจ่ายในชุด)
    ค่าปรับ = วันที่ส่งมอบเกินกำหนด (แสดงบรรทัดค่าปรับ ไม่รวมในยอดภาษี)"""
    from types import SimpleNamespace
    from app.services.finance_forms_doc import write_wht_4235, _new, _save
    total = float(proc.total_amount or 0)
    goods = round(total / 1.07, 2) if proc.vat_mode == "include" else total
    wht = round(goods * float(getattr(proc, "wht_rate", 0) or 0) / 100, 2)
    fine = round(total * float(proc.penalty_rate or 0.10) / 100 * (proc.overdue_days or 0), 2)
    v = proc.vendor
    memo = SimpleNamespace(
        id=proc.id, memo_no=proc.order_no or proc.memo_no or "",
        amount=total, vat=round(total - goods, 2), wht=wht, fine=fine,
        payee=(v.name if v else "") or "",
        date=proc.inspect_date or proc.delivery_date or proc.order_date)
    doc = _new()
    write_wht_4235(
        doc, school, memo,
        payee_tax_id=((v.tax_id or "").strip() if v else ""),
        payee_address=((v.address or "").strip() if v else ""),
        pay_type="ค่าจ้างทำของ" if (proc.proc_type or "") == "จ้าง" else "ค่าซื้อพัสดุ",
        rate=float(getattr(proc, "wht_rate", 0) or 0))
    return _save(doc, f"หนังสือรับรองหักภาษีณที่จ่าย_{_doc_seq(proc)}")


def render_document(kind: str, proc, school) -> str:
    """สร้างไฟล์เอกสารชนิด kind จากแม่แบบ คืนค่าที่อยู่ไฟล์"""
    if kind == WHT_KIND:
        return render_proc_wht(proc, school)
    # TOR ของเรื่องที่มาจากหนังสือเรียน ใช้ฉบับเฉพาะ (8 หัวข้อ + รายการหนังสือแนบท้าย)
    # แทนแม่แบบ TOR ทั่วไป เพราะมีคุณสมบัติผู้เสนอราคา/หลักฐานเสนอราคา/หลักประกันครบตามแฟ้มจริง
    tp = book_purchase_of(proc)
    if tp is not None:
        if kind == "รายละเอียดคุณลักษณะ(TOR)":
            from sqlalchemy.orm import object_session
            from app.services.book_tor_doc import render_book_tor
            from app.routers.textbooks import _book_groups
            return render_book_tor(school, tp, _book_groups(object_session(proc), tp.year))
        # เอกสารจัดซื้อฉบับหนังสือเรียน (wording/ช่องกรอกต่างจากพัสดุทั่วไป)
        from app.services.book_proc_doc import BOOK_RENDERERS
        maker = BOOK_RENDERERS.get(kind)
        if maker:
            return maker(school, proc, tp)
    if kind not in TEMPLATE_FILES:
        raise ValueError(f"ยังไม่มีแม่แบบสำหรับ: {kind}")
    template_path = TEMPLATES_DIR / TEMPLATE_FILES[kind]
    if not template_path.exists():
        raise FileNotFoundError(
            f"ไม่พบแม่แบบ {template_path} - รัน build_templates ก่อน"
        )

    tpl = DocxTemplate(str(template_path))
    tpl.render(build_context(proc, school))
    if kind in ONE_PAGE_KINDS:
        # บันทึกข้อความต้องจบหน้าเดียวเสมอ ต่อให้ชื่อโครงการยาวหรือกรรมการหลายคน
        # (บีบช่องไฟ/ระยะบรรทัดเท่านั้น ขนาดตัวอักษรคง 16 pt ตามระเบียบงานสารบรรณ)
        try:
            from app.services.page_fit import fit_one_page
            fit_one_page(tpl.docx)
        except Exception:
            pass

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    seq = _doc_seq(proc)
    fname = _safe_filename(f"{kind}_{seq}_{proc.subject}.docx")
    out_path = out_dir / fname
    tpl.save(str(out_path))
    return str(out_path)


def _bundle_filename(proc) -> str:
    """ชื่อไฟล์ชุดเอกสาร: 'เลขใบสั่งซื้อ/จ้าง ชื่อโครงการ ราคา'
    (ถ้ายังไม่มีเลขใบสั่ง ใช้เลขบันทึกหรือ id แทน)"""
    price = proc.total_amount or 0
    price_s = f"{int(price)}" if price == int(price) else f"{price:.2f}"
    seq = _doc_seq(proc)
    project = proc.project_name or proc.subject or ""
    return _safe_filename(f"{seq} {project} {price_s}") + ".docx"


def render_bundle(kinds, proc, school) -> str:
    """
    สร้างเอกสารทุกชนิดที่เลือก แล้วรวมเป็นไฟล์ .docx เดียว
    (แต่ละเอกสารขึ้นหน้าใหม่) คืนค่าที่อยู่ไฟล์รวม
    """
    paths = [render_document(k, proc, school) for k in kinds]
    master = _Docx(paths[0])
    composer = Composer(master)
    for p in paths[1:]:
        # ขึ้นหน้าใหม่ก่อนต่อเอกสารถัดไป
        master.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        composer.append(_Docx(p))

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / _bundle_filename(proc)
    composer.save(str(out_path))
    return str(out_path)


# ลำดับมาตรฐานของเอกสาร (ตามไทม์ไลน์การจัดซื้อจริง) - ใช้ทั้งปุ่มรายใบและการรวมไฟล์
# เตรียมสเปก -> ขออนุมัติ -> เสนอราคา -> ตัดสิน -> สั่ง -> ส่งมอบ -> ตรวจรับ/เบิกจ่าย
DOC_ORDER = [
    "แต่งตั้งกรรมการคุณลักษณะ",      # 1 ตั้ง กก.กำหนดคุณลักษณะ/ราคากลาง (ข้อ 21)
    "คำสั่งแต่งตั้งกรรมการคุณลักษณะ",  # 1.5 คำสั่งแต่งตั้ง กก.กำหนดคุณลักษณะ (เฉพาะเรื่องที่กรอกรายชื่อไว้)
    "รายละเอียดคุณลักษณะ(TOR)",       # 2 TOR
    "รายงานขอซื้อ",                   # 3 รายงานขอซื้อ/จ้าง (+ แนบท้าย)
    "คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง",   # 3.5 ตั้ง กก.ซื้อ/จ้าง (เฉพาะเรื่องที่กรอกรายชื่อไว้)
    "คำสั่งแต่งตั้งผู้ตรวจรับ",        # 4 ตั้งกรรมการตรวจรับ
    "ใบเสนอราคา",                     # 5 ผู้ขายเสนอราคา
    "รายงานผลการพิจารณา",            # 6 ตัดสินผู้ชนะ (ข้อ 79)
    "ประกาศผู้ชนะ",                   # 7 ประกาศผล
    "ใบสั่งซื้อ/สั่งจ้าง",             # 8 สั่งซื้อ/จ้าง
    "ใบส่งมอบงาน",                    # 9 ส่งมอบ
    "ใบตรวจรับพัสดุ",                 # 10 ตรวจรับ (กรรมการลงนาม)
    "รายงานผลตรวจรับและเบิกจ่าย",    # 11 บันทึกเสนอผลตรวจรับ + การเงิน + อนุมัติเบิกจ่าย
    WHT_KIND,                         # 12 หนังสือรับรองหักภาษี ณ ที่จ่าย (เฉพาะเรื่องที่ตั้งอัตราหักไว้)
]
# ตรวจว่าครบและตรงกับแม่แบบที่มี (กันพิมพ์ชื่อผิด) - ยกเว้นเอกสารที่สร้างด้วยโค้ด
assert set(DOC_ORDER) - {WHT_KIND} == set(TEMPLATE_FILES), "DOC_ORDER ไม่ตรงกับ TEMPLATE_FILES"

# ชนิดเอกสารที่สร้างได้ (เรียงตามลำดับมาตรฐาน) ใช้แสดงปุ่ม/รวมไฟล์
AVAILABLE_KINDS = DOC_ORDER

# บันทึกข้อความที่ต้องจบในหน้าเดียว (ท่อนก่อน page break แรก)
# แบบฟอร์มที่ต้องจบในหน้าเดียว (ท่อนก่อน page break แรก)
# ไม่รวม TOR เพราะรายการพัสดุเยอะ ๆ ยาวข้ามหน้าเป็นเรื่องปกติของเอกสารนั้น
ONE_PAGE_KINDS = {
    "แต่งตั้งกรรมการคุณลักษณะ", "คำสั่งแต่งตั้งกรรมการคุณลักษณะ",
    "รายงานขอซื้อ", "คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง", "คำสั่งแต่งตั้งผู้ตรวจรับ",
    "ใบเสนอราคา", "รายงานผลการพิจารณา", "ประกาศผู้ชนะ", "ใบสั่งซื้อ/สั่งจ้าง",
    "ใบส่งมอบงาน", "ใบตรวจรับพัสดุ", "รายงานผลตรวจรับและเบิกจ่าย",
}

# เอกสารที่มีความหมายเฉพาะเมื่อกรอกข้อมูลนั้นไว้ -> ไม่มีข้อมูล = ไม่โชว์ปุ่ม/ไม่รวมในชุด
_NEEDS_COMMITTEE = {"คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง": "purchase"}


# มาตราที่ใช้อ้างในคำสั่งแต่งตั้ง ตามวิธีจัดซื้อจัดจ้างที่เลือก
_METHOD_LAW = {
    "เฉพาะเจาะจง": "ตามมาตรา 56 วรรคหนึ่ง (2) (ข)",
    "คัดเลือก": "ตามมาตรา 56 วรรคหนึ่ง (1)",
    "ประกาศเชิญชวนทั่วไป": "ตามมาตรา 55 (1)",
}


def spec_mode_of(proc) -> str:
    """ผู้จัดทำร่างตามข้อ 21 เป็นแบบไหน: 'single' (มอบหมายคนเดียว) หรือ 'committee'

    เรื่องเก่าที่บันทึกไว้ก่อนมีตัวเลือกนี้ ไม่มีค่า mode ที่เชื่อถือได้
    จึงดูจากจำนวนคนที่กรอกไว้จริง (กรอกคนเดียว = มอบหมาย, หลายคน = คณะกรรมการ)
    """
    c = _find_committee(proc, "spec")
    if c is None:
        return "single"
    if (c.mode or "") in ("single", "committee"):
        return c.mode
    return "committee" if len(c.members or []) > 1 else "single"


def kinds_for(proc):
    """ชนิดเอกสารที่ออกได้สำหรับเรื่องนี้ (ตัดเอกสารที่ไม่มีข้อมูลรองรับออก)"""
    # หนังสือเรียน: คำสั่งแต่งตั้งเป็นฉบับเดียว (กก.จัดซื้อ + กก.ตรวจรับ)
    # จึงไม่ต้องมีคำสั่ง กก.ซื้อ/จ้าง กับคำสั่ง กก.คุณลักษณะ แยกอีกใบ
    book = book_purchase_of(proc) is not None
    skip = {"คำสั่งแต่งตั้งกรรมการซื้อ/จ้าง"} if book else set()
    out = []
    for k in DOC_ORDER:
        if k in skip:
            continue
        if k == WHT_KIND and not float(getattr(proc, "wht_rate", 0) or 0) > 0:
            continue                      # ไม่ได้หักภาษี ณ ที่จ่าย -> ไม่มีหนังสือรับรอง
        if k == "คำสั่งแต่งตั้งกรรมการคุณลักษณะ":
            # คำสั่ง (ครุฑ) ใช้เฉพาะเมื่อแต่งตั้งเป็นคณะกรรมการ
            # ทางมอบหมายบุคคลเดียวใช้บันทึกมอบหมายใบเดียวจบ ตามข้อ 21 วรรคท้าย
            c = _find_committee(proc, "spec")
            if spec_mode_of(proc) != "committee" or not (c and c.members):
                continue
        need = _NEEDS_COMMITTEE.get(k)
        if need:
            c = _find_committee(proc, need)
            if not (c and c.members):
                continue
        out.append(k)
    return out
