"""
หนังสือรับรองการหักภาษี ณ ที่จ่าย (50 ทวิ) จากบันทึกขอเบิกจ่าย
- เลขผู้เสียภาษีของโรงเรียน (ตั้งค่า) ขึ้นในหนังสือ
- ผู้ถูกหักภาษี: ดึงเลขผู้เสียภาษี/ที่อยู่จากทะเบียนผู้ขายที่ชื่อตรงกัน · ชื่อไม่ตรง = เว้นว่าง
รัน: .venv\Scripts\python.exe -m pytest tests/test_wht_cert.py
"""
import io
import re
import zipfile
from datetime import datetime

from tests.test_assignments import _login, _db
from app.models import DisburseMemo, Vendor
from app.routers.pages import get_school

MARK = "ทดสอบ50ทวิ_"


def _text(resp):
    xml = zipfile.ZipFile(io.BytesIO(resp.content)).read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def test_wht_certificate_fills_tax_ids():
    c = _login(); db = _db()
    sch = get_school(db)
    # ฟอร์มตั้งค่าบันทึกทุกช่อง -> เก็บค่าเดิมทั้งแถวไว้คืนหลังเทสต์ (กันล้างค่าตั้งค่าจริง)
    cols = [col.name for col in sch.__table__.columns if col.name != "id"]
    snapshot = {k: getattr(sch, k) for k in cols}
    v = Vendor(name=MARK + "ร้านเครื่องเขียน", tax_id="0994000123456", address="99 ม.1 ต.หินลาด")
    m1 = DisburseMemo(fiscal_year=2569, memo_no="T1", date=datetime(2026, 9, 1),
                      payee=MARK + "ร้านเครื่องเขียน", amount=10700, vat=700, wht=100)
    m2 = DisburseMemo(fiscal_year=2569, memo_no="T2", date=datetime(2026, 9, 1),
                      payee=MARK + "ร้านอื่น", amount=5000, wht=50)
    db.add_all([v, m1, m2]); db.commit()
    try:
        form = {k: (getattr(sch, k) or "") for k in (
            "name", "address", "district", "province", "area_office", "director_name",
            "director_position", "officer_name", "head_officer_name")}
        c.post("/settings", data={**form, "tax_id": "0-9940-00111-22-3"})
        db.expire_all()
        assert get_school(db).tax_id == "0994000111223"

        t1 = _text(c.get(f"/finance/disburse/{m1.id}/wht.docx"))
        assert "0994000111223" in t1                    # โรงเรียน
        assert "0994000123456" in t1 and "99 ม.1 ต.หินลาด" in t1   # ผู้ขาย
        assert "10,000.00" in t1 and "100.00" in t1     # ฐานก่อน VAT + ภาษีที่หัก

        t2 = _text(c.get(f"/finance/disburse/{m2.id}/wht.docx"))
        assert "0994000123456" not in t2                # ชื่อไม่ตรง -> ไม่ดึงร้านอื่นมา
    finally:
        sch = get_school(db)
        for k, val in snapshot.items():
            setattr(sch, k, val)
        db.delete(m1); db.delete(m2); db.delete(v); db.commit()


def test_procurement_wht_certificate():
    from app.models import Procurement
    c = _login(); db = _db()
    v = Vendor(name=MARK + "ร้านซ่อม", tax_id="3440100123456", address="5 ถ.ทดสอบ")
    db.add(v); db.commit()
    p = Procurement(fiscal_year=2569, subject=MARK + "จ้างซ่อมหลังคา", proc_type="จ้าง",
                    total_amount=10700, vat_mode="include", wht_rate=1, vendor_id=v.id,
                    order_no="จ5/2569", inspect_date=datetime(2026, 9, 15))
    p0 = Procurement(fiscal_year=2569, subject=MARK + "ซื้อกระดาษ", proc_type="ซื้อ",
                     total_amount=500, wht_rate=0)
    db.add_all([p, p0]); db.commit()
    try:
        t = _text(c.get(f"/procurement/{p.id}/wht.docx"))
        assert "3440100123456" in t and "5 ถ.ทดสอบ" in t
        assert "ค่าจ้างทำของ" in t
        assert "10,000.00" in t and "100.00" in t      # ฐานก่อน VAT 10,000 · หัก 1% = 100
        assert "15 ก.ย. 2569" in t
        page = c.get(f"/procurement/{p.id}").text
        assert f"/procurement/{p.id}/wht.docx" in page
        page0 = c.get(f"/procurement/{p0.id}").text
        assert f"/procurement/{p0.id}/wht.docx" not in page0   # ไม่ได้ตั้งอัตรา -> ไม่มีปุ่ม
    finally:
        db.delete(p); db.delete(p0); db.delete(v); db.commit()
