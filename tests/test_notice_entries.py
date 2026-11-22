"""ประกาศอัปเดต: ข้อใหม่ขึ้นต้นด้วย "- " บรรทัดอื่นต่อในข้อเดิม + ปุ่ม "ไปดู" (>> /path) ประกาศเก่ายังแสดงได้"""
from types import SimpleNamespace as N


def _n(items):
    from app.accounts import MaintenanceNotice
    return MaintenanceNotice(items=items, title="t", kind="news")


def test_new_format_multiline_items_and_links():
    e = _n("- เพิ่มปุ่มเช็กชื่อ\nในหน้าหลักครู\n>> /academic/lessons/next\n- ปรับตารางสอน\n>> //evil.com\n- ข้อสาม").entries()
    assert [x["text"] for x in e] == ["เพิ่มปุ่มเช็กชื่อ\nในหน้าหลักครู", "ปรับตารางสอน", "ข้อสาม"]
    assert e[0]["href"] == "/academic/lessons/next"
    assert e[1]["href"] == ""                      # ลิงก์นอกระบบไม่รับ


def test_old_format_each_line_is_an_item():
    assert _n("ข้อหนึ่ง\nข้อสอง").lines() == ["ข้อหนึ่ง", "ข้อสอง"]


def test_email_has_line_breaks_and_go_link(monkeypatch):
    import app.services.retention as rt
    from app.services import notice_mail
    monkeypatch.setattr(rt, "_base_url", lambda: "https://example.test")
    n = _n("- บรรทัดแรก\nบรรทัดสอง\n>> /general/behavior")
    n.note, n.start_at, n.end_at = "", None, None
    monkeypatch.setattr(notice_mail, "when_text", lambda x: "")
    html = notice_mail.build_html(n)
    assert "บรรทัดแรก<br>บรรทัดสอง" in html and "https://example.test/general/behavior" in html and "ไปดู" in html
