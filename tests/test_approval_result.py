# -*- coding: utf-8 -*-
"""ผอ. กดอนุมัติแล้ว ต้องเห็นเอกสารฉบับสมบูรณ์ทันที

เดิมกดอนุมัติแล้วเด้งกลับกล่องรออนุมัติ ซึ่งรายการนั้นหายไปจากกล่องแล้ว
ผอ. จึงไม่เห็นใบลา/บันทึกที่ลงนามครบ ต้องไปตามหาเองในเมนูอื่น
รัน: .venv\Scripts\python.exe -m pytest tests/test_approval_result.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_approving_lands_on_the_item_not_the_empty_inbox():
    hr = _src("app/routers/hr.py")
    acad = _src("app/routers/academic.py")
    assert 'f"/hr/leave-requests/{lid}?msg=' in hr, "ใบลา: อนุมัติแล้วต้องกลับมาหน้ารายการนั้น"
    assert 'f"/hr/travel-requests/{tid}?msg=' in hr, "ไปราชการ: เหมือนกัน"
    assert 'f"/academic/lesson-plans/{plan_id}?msg=' in acad, "แผนการสอน: เหมือนกัน"
    # ต้องไม่เหลือการเด้งกลับกล่องรออนุมัติตอนบันทึกผลสำเร็จ
    for name, text in (("hr.py", hr), ("academic.py", acad)):
        assert '"/approvals?msg=บันทึกผลการพิจารณาแล้ว"' not in text, name


def test_each_detail_page_shows_the_finished_document_after_approval():
    for rel, obj in (("app/templates/leave_request_detail.html", "r"),
                     ("app/templates/travel_request_detail.html", "r"),
                     ("app/templates/lesson_plan_detail.html", "p")):
        html = _src(rel)
        assert "ฉบับสมบูรณ์" in html, rel
        assert f"{obj}.status == 'approved'" in html, rel


def test_the_finished_document_link_is_guarded_so_it_never_points_at_none():
    """ยังไม่อนุมัติจะยังไม่มีเลขทะเบียน ลิงก์ต้องไม่โผล่มาเป็น /None/"""
    for rel, guard in (("app/templates/leave_request_detail.html", "r.record_id"),
                       ("app/templates/travel_request_detail.html", "r.record_id"),
                       ("app/templates/lesson_plan_detail.html", "p.file_blob")):
        html = _src(rel)
        i = html.index("ฉบับสมบูรณ์")
        window = html[max(0, i - 400):i]
        assert guard in window, f"{rel}: ปุ่มเอกสารฉบับสมบูรณ์ยังไม่มีเงื่อนไขกัน"


def test_detail_routes_still_open_after_the_item_leaves_the_inbox():
    """สถานะเปลี่ยนเป็นอนุมัติแล้ว หน้ารายละเอียดต้องยังเปิดได้ ไม่เด้งทิ้ง"""
    hr = _src("app/routers/hr.py")
    for fn in ("def leave_request_detail", "def travel_request_detail"):
        body = hr[hr.index(fn):]
        body = body[:body.index("@router", 10)]
        assert 'r.status' not in body.split("return templates")[0], fn
