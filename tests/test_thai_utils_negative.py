from app.thai_utils import bahttext


def test_bahttext_negative_does_not_crash():
    assert bahttext(-150.5) == "ลบหนึ่งร้อยห้าสิบบาทห้าสิบสตางค์"
    assert bahttext(None) == "ศูนย์บาทถ้วน"
