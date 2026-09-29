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


def test_procurement_wht_in_document_set():
    """งานพัสดุ: หนังสือรับรองแบบ 4235 อยู่ในรายการเลือกเอกสาร (ใบสุดท้าย) เฉพาะเรื่องที่ตั้งอัตราหักไว้
    ออกทีละใบ / รวมในชุดได้ · ไม่มีการ์ดแยกแล้ว"""
    from app.models import Procurement
    from app.services.render import WHT_KIND, kinds_for
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
        assert kinds_for(p)[-1] == WHT_KIND                 # ใบสุดท้ายของชุด
        assert WHT_KIND not in kinds_for(p0)                # ไม่ได้หักภาษี -> ไม่มีให้เลือก
        page = c.get(f"/procurement/{p.id}/bundle").text
        assert WHT_KIND in page
        assert WHT_KIND not in c.get(f"/procurement/{p0.id}/bundle").text
        detail = c.get(f"/procurement/{p.id}").text
        assert "wht.docx" not in detail                     # การ์ดแยกเอาออกแล้ว

        t = _text(c.post(f"/procurement/{p.id}/generate", data={"doc_kind": WHT_KIND}))
        assert "แบบ 4235" in t and "3440100123456" in t and "5 ถ.ทดสอบ" in t
        assert "ค่าจ้างทำของ" in t and "จ5/2569" in t and "15 ก.ย. 2569" in t
        assert "10,000.00" in t and "100.00" in t            # ฐานก่อน VAT 10,000 · หัก 1% = 100

        r = c.post(f"/procurement/{p.id}/bundle",
                   data={"kinds": ["รายงานขอซื้อ", WHT_KIND]})
        tb = _text(r)
        assert "แบบ 4235" in tb and "3440100123456" in tb    # รวมในชุดเดียวได้
    finally:
        from app.models import Document
        db.query(Document).filter(Document.procurement_id.in_([p.id, p0.id])).delete(
            synchronize_session=False)
        db.delete(p); db.delete(p0); db.delete(v); db.commit()


def test_lunch_certificates_use_4235():
    """อาหารกลางวัน (จ้างเหมา + จ้างแม่ครัว) ใช้แบบ 4235 ตัวเดียวกับการเงิน/พัสดุ"""
    from types import SimpleNamespace as N
    from app.services.lunch_doc import render_disburse_lunch_doc
    from app.services.lunch_ingredient_doc import render_wht_cook
    sch = N(name="โรงเรียนทดสอบ", address="ต.ทดสอบ", tax_id="0994000111223",
            director_name="นายผอ ทดสอบ", director_position="ผู้อำนวยการ", finance_officer_name="",
            area_office="", doc_prefix="ศธ", logo=None, district="", province="")
    v = N(name="นางแม่ครัว ใจดี", tax_id="3440100999999", address="9 ม.3")
    rnd = N(program=N(year=2569, funding_org="อบต.", classes=[]), vendor=v, order_no="จ 3/2569",
            cook_wage=12000, amount=12000, end_date=datetime(2026, 9, 30), seq=1,
            order_date=datetime(2026, 6, 1), docnos="", doc_meta="")
    inst = N(round=rnd, amount=48000, seq=1, start_date=datetime(2026, 6, 1),
             end_date=datetime(2026, 6, 30), days=20, inspect_date=datetime(2026, 7, 1))

    def text(path):
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        return re.sub(r"<[^>]+>", "", xml)

    for t in (text(render_disburse_lunch_doc(inst, sch)), text(render_wht_cook(rnd, sch))):
        assert "แบบ 4235" in t and "50 ทวิ" not in t and "๕๐ ทวิ" not in t
        assert "3440100999999" in t and "จ 3/2569" in t and "0994000111223" in t
    assert "480.00" in text(render_disburse_lunch_doc(inst, sch))     # 48,000 x 1%
    assert "120.00" in text(render_wht_cook(rnd, sch))                # ค่าจ้างแม่ครัว 12,000 x 1%


def test_fine_shown_but_not_in_tax_total():
    """ค่าปรับลงบรรทัดค่าปรับ แต่ยอดรวม/ตัวอักษร = ภาษีอย่างเดียว · ไม่มีหมายเหตุท้ายแบบ"""
    from types import SimpleNamespace as N
    from app.services.finance_forms_doc import render_wht_certificate
    sch = N(name="โรงเรียนทดสอบ", address="", tax_id="", director_name="", director_position="")
    memo = N(amount=10000, vat=0, wht=100, fine=50, payee="นายช่าง", date=datetime(2026, 9, 1),
             memo_no="T9", id=9)
    xml = zipfile.ZipFile(render_wht_certificate(sch, memo)).read("word/document.xml").decode("utf-8")
    t = re.sub(r"<[^>]+>", "", xml)
    assert "50.00" in t                       # ค่าปรับยังแสดง
    assert "150.00" not in t                  # ไม่รวมค่าปรับเข้ายอดภาษี
    assert "หนึ่งร้อยบาทถ้วน" in t
    assert "หมายเหตุ" not in t
