"""ชื่อโครงการยาว (ไทย 3 ไบต์/ตัว) ต้องไม่ทำให้ชื่อไฟล์เกิน 255 ไบต์ -> OSError File name too long -> 500"""
from app.services.filenames import fit_name


def test_fit_name_keeps_extension_and_byte_limit():
    long = "รายงานขอซื้อ_1-2570_จัดจ้างถ่ายเอกสาร โครงการพัฒนาครูและบุคลากรทางการศึกษา ประจำปีการศึกษา 2569" * 2 + ".docx"
    out = fit_name(long)
    assert out.endswith(".docx") and len(out.encode("utf-8")) <= 180
    assert out.startswith("รายงานขอซื้อ_1-2570_จัดจ้าง")
    out.encode("utf-8").decode("utf-8")          # ไม่ตัดกลางตัวอักษร
    assert fit_name("สั้น.docx") == "สั้น.docx"


def test_every_safe_helper_trims():
    import importlib
    mods = ["acad_doc", "finance_doc", "office_doc", "hr_doc", "proc_alt_doc", "book_receipt_doc", "receipt_voucher"]
    for m in mods:
        f = importlib.import_module(f"app.services.{m}")._safe
        assert len((f("ก" * 300) + ".docx").encode("utf-8")) <= 255, m
    from app.services.render import _safe_filename
    assert len(_safe_filename("ข" * 300 + ".docx").encode("utf-8")) <= 255
