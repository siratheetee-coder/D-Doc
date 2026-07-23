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
        "unit": it.unit,
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

    # คณะกรรมการกำหนดคุณลักษณะ/ราคากลาง (ถ้ายังไม่มี ใช้รายชื่อผู้ตรวจรับแทนชั่วคราว)
    spec = _find_committee(proc, "spec")
    spec_members = ([{"name": m.name, "position": m.position, "role": m.role}
                     for m in spec.members] if spec and spec.members else inspect_members)

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
        "committee_word": ("คณะกรรมการตรวจรับพัสดุ" if (proc.inspection_mode or "single") == "committee"
                           else "ผู้ตรวจรับพัสดุ"),
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


def render_document(kind: str, proc, school) -> str:
    """สร้างไฟล์เอกสารชนิด kind จากแม่แบบ คืนค่าที่อยู่ไฟล์"""
    if kind not in TEMPLATE_FILES:
        raise ValueError(f"ยังไม่มีแม่แบบสำหรับ: {kind}")
    template_path = TEMPLATES_DIR / TEMPLATE_FILES[kind]
    if not template_path.exists():
        raise FileNotFoundError(
            f"ไม่พบแม่แบบ {template_path} - รัน build_templates ก่อน"
        )

    tpl = DocxTemplate(str(template_path))
    tpl.render(build_context(proc, school))

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
    "รายละเอียดคุณลักษณะ(TOR)",       # 2 TOR
    "รายงานขอซื้อ",                   # 3 รายงานขอซื้อ/จ้าง (+ แนบท้าย)
    "คำสั่งแต่งตั้งผู้ตรวจรับ",        # 4 ตั้งกรรมการตรวจรับ
    "ใบเสนอราคา",                     # 5 ผู้ขายเสนอราคา
    "รายงานผลการพิจารณา",            # 6 ตัดสินผู้ชนะ (ข้อ 79)
    "ประกาศผู้ชนะ",                   # 7 ประกาศผล
    "ใบสั่งซื้อ/สั่งจ้าง",             # 8 สั่งซื้อ/จ้าง
    "ใบส่งมอบงาน",                    # 9 ส่งมอบ
    "ใบตรวจรับพัสดุ",                 # 10 ตรวจรับ (กรรมการลงนาม)
    "รายงานผลตรวจรับและเบิกจ่าย",    # 11 บันทึกเสนอผลตรวจรับ + การเงิน + อนุมัติเบิกจ่าย
]
# ตรวจว่าครบและตรงกับแม่แบบที่มี (กันพิมพ์ชื่อผิด)
assert set(DOC_ORDER) == set(TEMPLATE_FILES), "DOC_ORDER ไม่ตรงกับ TEMPLATE_FILES"

# ชนิดเอกสารที่สร้างได้ (เรียงตามลำดับมาตรฐาน) ใช้แสดงปุ่ม/รวมไฟล์
AVAILABLE_KINDS = DOC_ORDER
