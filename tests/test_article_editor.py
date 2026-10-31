"""เจ้าของเขียนบทความคลังความรู้เองจากคอนโซล: ใส่ข้อความ + รูป เผยแพร่ได้โดยไม่ต้องแก้โค้ดหรือ deploy"""
import io

from tests.test_subsidy import env  # noqa: F401


def _boss():
    from fastapi.testclient import TestClient
    from app.accounts import acc_session, Account, hash_password
    from app.main import app
    with acc_session() as db:
        if not db.query(Account).filter_by(username="kb-editor").first():
            db.add(Account(username="kb-editor", password_hash=hash_password("Boss2569xyz"), role="superadmin"))
            db.commit()
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "kb-editor", "password": "Boss2569xyz"}, follow_redirects=False)
    return c


def _anon():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2400, 1200), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _form(slug, **kw):
    d = {"orig_slug": "", "slug": slug, "action": "draft", "title": "เรื่องทดสอบ", "body": "<p>เนื้อหา</p>",
         "description": "คำอธิบาย", "category": "งานพัสดุ"}
    d.update(kw)
    return d


def test_only_superadmin_can_write(env):
    r = env.get("/admin-console/articles", follow_redirects=False)
    assert r.status_code in (302, 303, 403)
    r = env.post("/admin-console/articles/save", data=_form("hack-one"), follow_redirects=False)
    assert r.status_code in (302, 303, 403)
    r = env.post("/admin-console/articles/upload", files={"file": ("a.png", _png(), "image/png")}, follow_redirects=False)
    assert r.status_code in (302, 303, 403)
    assert _anon().get("/knowledge/hack-one").status_code == 404


def test_write_publish_and_withdraw(env):
    boss = _boss()
    assert "เขียนบทความใหม่" in boss.get("/admin-console/articles").text
    assert "aeBody" in boss.get("/admin-console/articles/new").text

    # อัปโหลดรูป: ย่อให้ไม่เกิน 1600 ใช้ URL สาธารณะได้
    j = boss.post("/admin-console/articles/upload", files={"file": ("a.png", _png(), "image/png")}).json()
    assert j["ok"] and j["url"].startswith("/knowledge/media/") and j["url"].endswith(".jpg")
    img = _anon().get(j["url"])
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/jpeg")
    from PIL import Image
    assert max(Image.open(io.BytesIO(img.content)).size) == 1600

    body = (f'<h2>หัวข้อหนึ่ง</h2><p>เนื้อ<b>หนา</b></p><figure><img src="{j["url"]}" alt="รูป"><figcaption>คำบรรยาย</figcaption></figure>'
            '<script>alert(1)</script><p onclick="x()">ข้อความ<a href="javascript:alert(1)">ลิงก์</a></p>')
    r = boss.post("/admin-console/articles/save", data=_form("my-first-article", title="บทความแรก", body=body,
                                                              source_name="ว.119", source_url="https://example.com/a.pdf",
                                                              reviewed="01/10/2569", type="อธิบายระเบียบ")).json()
    assert r["ok"] and r["draft"] and r["url"] == "/knowledge/my-first-article"

    # ร่าง: คนทั่วไปไม่เห็น ผู้ดูแลเห็น
    assert _anon().get("/knowledge/my-first-article").status_code == 404
    assert "บทความแรก" in boss.get("/knowledge/my-first-article").text

    # เผยแพร่ ไม่ต้อง deploy: ขึ้นหน้ารวม sitemap และโค้ดอันตรายถูกตัด
    r = boss.post("/admin-console/articles/save", data=_form("", orig_slug="my-first-article", action="publish",
                                                             title="บทความแรก", body=body, reviewed="01/10/2569",
                                                             source_name="ว.119", source_url="https://example.com/a.pdf")).json()
    assert r["ok"] and not r["draft"]
    anon = _anon()
    page = anon.get("/knowledge/my-first-article").text
    assert "<script>alert" not in page and "javascript:alert" not in page and 'onclick="x()"' not in page
    assert j["url"] in page and "หัวข้อหนึ่ง" in page and "https://example.com/a.pdf" in page
    assert "บทความแรก" in anon.get("/knowledge").text
    assert "/knowledge/my-first-article" in anon.get("/sitemap.xml").text

    # เปิดแก้ไขได้ค่าเดิมครบ
    edit = boss.get("/admin-console/articles/my-first-article/edit").text
    assert "01/10/2569" in edit and "ว.119" in edit and "<h2>หัวข้อหนึ่ง</h2>" in edit

    # ถอนกลับเป็นร่าง -> หายจากหน้าเว็บ
    boss.post("/admin-console/articles/save", data=_form("", orig_slug="my-first-article", action="draft", title="บทความแรก", body=body))
    assert anon.get("/knowledge/my-first-article").status_code == 404

    boss.post("/admin-console/articles/my-first-article/delete")
    assert boss.get("/knowledge/my-first-article").status_code == 404


def test_validation_and_header_injection(env):
    boss = _boss()
    assert not boss.post("/admin-console/articles/save", data=_form("ไทยล้วน")).json()["ok"]
    assert not boss.post("/admin-console/articles/save", data=_form("../../etc")).json()["ok"]
    assert not boss.post("/admin-console/articles/save", data=_form("no-title", title="  ")).json()["ok"]
    assert not boss.post("/admin-console/articles/save", data=_form("no-body", action="publish", body="<p> </p>")).json()["ok"]
    assert boss.post("/admin-console/articles/save", data=_form("dup-slug")).json()["ok"]
    assert not boss.post("/admin-console/articles/save", data=_form("dup-slug")).json()["ok"]

    # ชื่อเรื่องพยายามปิดคอมเมนต์หัวไฟล์/แอบแก้ค่า draft ไม่ได้
    r = boss.post("/admin-console/articles/save", data=_form("inject-one", title="ก\ndraft: false\n--><script>x</script>")).json()
    assert r["ok"]
    from app.services import articles
    a = articles.get("inject-one", include_drafts=True)
    assert a["draft"] and "<script>" not in a["body"]
    assert _anon().get("/knowledge/inject-one").status_code == 404

    # ไฟล์ปลอม
    j = boss.post("/admin-console/articles/upload", files={"file": ("a.png", b"<svg onload=x>", "image/png")}).json()
    assert not j["ok"]
    j = boss.post("/admin-console/articles/upload", data={"kind": "pdf"}, files={"file": ("a.pdf", b"<html>", "application/pdf")}).json()
    assert not j["ok"]
    assert _anon().get("/knowledge/media/..%2F..%2Fsecret.key").status_code == 404
    assert _anon().get("/knowledge/media/evil.html").status_code == 404


def test_edit_and_delete_bundled_article(env):
    """บทความเดิมในโค้ด แก้จากเว็บได้ และลบได้โดยไม่แตะไฟล์ใน repo"""
    from app.services import articles
    boss = _boss()
    slug = "clause-79-urgent-purchase"
    a = articles.get(slug, include_drafts=True)
    assert a and "<h2>" in boss.get(f"/admin-console/articles/{slug}/edit").text
    r = boss.post("/admin-console/articles/save", data=_form("", orig_slug=slug, title="แก้จากเว็บ", body=a["raw_body"])).json()
    assert r["ok"] and articles.get(slug, include_drafts=True)["title"] == "แก้จากเว็บ"
    assert (articles.DIR / f"{slug}.html").exists() and "แก้จากเว็บ" not in (articles.DIR / f"{slug}.html").read_text(encoding="utf-8")
    boss.post(f"/admin-console/articles/{slug}/delete")
    assert articles.get(slug, include_drafts=True) is None


def test_paste_from_docs_is_cleaned(env):
    boss = _boss()
    j = boss.post("/admin-console/articles/clean", data={
        "html": '<b style="font-weight:normal"><p style="color:red"><span style="font-weight:700">หนา</span> ปกติ</p></b><img src="file:///c:/a.png">'}).json()
    assert j["html"] == "<p><b>หนา</b> ปกติ</p>" and j["dropped"] == 1
