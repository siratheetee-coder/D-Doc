"""SEO พื้นฐาน: หน้าแรกไม่ redirect, robots/sitemap, หน้าวิธีใช้เปิดสาธารณะ, canonical + JSON-LD"""
import json
import re

from tests.test_subsidy import env  # noqa: F401


def _anon():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_home_serves_landing_without_redirect(env):
    c = _anon()
    r = c.get("/?ref=fbad", follow_redirects=False)
    assert r.status_code == 200 and "ลดงานเอกสาร" in r.text
    assert '<link rel="canonical" href="https://www.easy-ekkasan.com/">' in r.text
    assert 'og:image" content="https://www.easy-ekkasan.com/static/landing/og-share.jpg' in r.text
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S).group(1)
    graph = json.loads(ld)["@graph"]
    app_ = next(g for g in graph if g["@type"] == "SoftwareApplication")
    assert app_["offers"]["priceCurrency"] == "THB" and app_["offers"]["price"]
    # /landing ยังใช้ได้ (ลิงก์โฆษณาเดิม)
    assert c.get("/landing").status_code == 200
    # คนล็อกอินแล้วยังเข้าหน้าหลักระบบตามเดิม
    assert "ลดงานเอกสาร" not in env.get("/").text


def test_robots_and_sitemap(env):
    c = _anon()
    r = c.get("/robots.txt")
    assert r.status_code == 200 and "Sitemap: https://www.easy-ekkasan.com/sitemap.xml" in r.text
    assert "Disallow: /login" in r.text and "Allow: /guide" in r.text
    s = c.get("/sitemap.xml")
    assert s.status_code == 200 and s.headers["content-type"].startswith("application/xml")
    assert "<loc>https://www.easy-ekkasan.com/guide</loc>" in s.text


def test_guide_public_for_visitors(env):
    c = _anon()
    r = c.get("/guide", follow_redirects=False)
    assert r.status_code == 200 and "วิธีใช้งาน" in r.text
    assert '<link rel="canonical" href="https://www.easy-ekkasan.com/guide">' in r.text
    assert 'og:image" content="https://www.easy-ekkasan.com/static/landing/og-share.jpg' in r.text
    # ล็อกอินแล้วยังเห็นแบบในระบบ (มีเมนูด้านข้าง)
    assert env.get("/guide").status_code == 200
    # หน้าในระบบอื่นยังต้องล็อกอิน
    assert c.get("/finance", follow_redirects=False).headers["location"] == "/login"


def test_knowledge_drafts_hidden_and_published_listed(env, monkeypatch, tmp_path):
    from app.services import articles
    monkeypatch.setattr(articles, "DIR", tmp_path)
    (tmp_path / "draft-one.html").write_text(
        "<!--\ntitle: ร่างลับ\ndescription: d\ndate: 2026-10-27\ncategory: งานพัสดุ\ndraft: true\n-->\n<p>x</p>", encoding="utf-8")
    c = _anon()
    # ยังไม่มีบทความเผยแพร่: หน้ารวมเปิดได้ แต่ร่างไม่โผล่ ไม่อยู่ใน sitemap ไม่มีลิงก์ในหน้าแรก
    r = c.get("/knowledge")
    assert r.status_code == 200 and "ร่างลับ" not in r.text
    assert c.get("/knowledge/draft-one").status_code == 404
    assert "/knowledge" not in c.get("/sitemap.xml").text
    assert 'href="/knowledge"' not in c.get("/").text

    (tmp_path / "pub-one.html").write_text(
        "<!--\ntitle: เรื่องเผยแพร่\ndescription: สรุปสั้น\ndate: 2026-10-20\nupdated: 2026-10-25\n"
        "category: งานพัสดุ\ndraft: false\n-->\n<h2>หัวข้อ</h2><p>เนื้อหา</p>", encoding="utf-8")
    page = c.get("/knowledge/pub-one")
    assert page.status_code == 200 and '<h2 id="s1">หัวข้อ</h2>' in page.text  # หัวข้อมี id ให้สารบัญลิงก์มา
    assert '<link rel="canonical" href="https://www.easy-ekkasan.com/knowledge/pub-one">' in page.text
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page.text, re.S).group(1))
    art = next(g for g in ld["@graph"] if g["@type"] == "Article")
    assert art["dateModified"] == "2026-10-25"
    sm = c.get("/sitemap.xml").text
    assert "<loc>https://www.easy-ekkasan.com/knowledge/pub-one</loc><lastmod>2026-10-25</lastmod>" in sm
    assert "draft-one" not in sm
    assert 'href="/knowledge"' in c.get("/").text
    # slug แปลก ๆ ไม่เปิดไฟล์นอกโฟลเดอร์
    assert c.get("/knowledge/..%2F..%2Fmain").status_code == 404


def test_knowledge_drafts_visible_to_superadmin(env, monkeypatch, tmp_path):
    from app.services import articles
    monkeypatch.setattr(articles, "DIR", tmp_path)
    (tmp_path / "draft-two.html").write_text(
        "<!--\ntitle: ร่างให้แอดมินดู\ndate: 2026-10-27\ndraft: true\n-->\n<p>x</p>", encoding="utf-8")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.accounts import acc_session, Account, hash_password
    with acc_session() as db:
        db.add(Account(username="kb-boss", password_hash=hash_password("Boss2569xyz"), role="superadmin"))
        db.commit()
    boss = TestClient(app, raise_server_exceptions=False)
    boss.post("/login", data={"username": "kb-boss", "password": "Boss2569xyz"}, follow_redirects=False)
    assert "ร่างให้แอดมินดู" in boss.get("/knowledge").text
    r = boss.get("/knowledge/draft-two")
    assert r.status_code == 200 and 'name="robots" content="noindex"' in r.text
    # เจ้าของโรงเรียน (ไม่ใช่ผู้ดูแลระบบ) ไม่เห็นร่าง
    assert env.get("/knowledge/draft-two").status_code == 404


def test_bundled_articles_parse():
    from app.services import articles
    arts = articles.all_articles(include_drafts=True)
    assert len(arts) >= 3
    for a in arts:
        assert a["title"] and a["description"] and a["category"], a["slug"]
        assert len(a["description"]) <= 170, a["slug"]


def test_knowledge_cover_image_and_featured(env, monkeypatch, tmp_path):
    from app.services import articles
    monkeypatch.setattr(articles, "DIR", tmp_path)
    (tmp_path / "with-pic.html").write_text(
        "<!--\ntitle: มีรูปปก\ndescription: d\ndate: 2026-10-20\ncategory: งานการเงิน\ndraft: false\n"
        "image: pic.jpg\nimage_alt: ภาพทะเบียน\nfeatured: true\n-->\n<p>x</p>", encoding="utf-8")
    (tmp_path / "no-pic.html").write_text(
        "<!--\ntitle: ไม่มีรูป\ndescription: d\ndate: 2026-10-25\ncategory: งานพัสดุ\ndraft: false\ncover: ว.119\n-->\n<p>x</p>",
        encoding="utf-8")
    c = _anon()
    lst = c.get("/knowledge").text
    # เรื่องแนะนำ = featured ไม่ใช่เรื่องใหม่สุด, ไม่มีรูปใช้ปกตัวอักษร
    feat = lst.split('class="kl-feat')[1].split("</a>")[0]
    assert "มีรูปปก" in feat and 'src="/static/knowledge/pic.jpg" alt="ภาพทะเบียน"' in feat
    assert "<b>ว.119</b>" in lst
    page = c.get("/knowledge/with-pic").text
    assert '<meta property="og:image" content="https://www.easy-ekkasan.com/static/knowledge/pic.jpg">' in page
    assert 'class="kb-cover"' in page


def test_knowledge_tabs_type_and_sources(env, monkeypatch, tmp_path):
    from app.services import articles
    monkeypatch.setattr(articles, "DIR", tmp_path)
    (tmp_path / "rule-one.html").write_text(
        "<!--\ntitle: อธิบายระเบียบ\ndescription: d\ndate: 2026-10-20\ncategory: งานพัสดุ\ndraft: false\n"
        "type: อธิบายระเบียบ\nreviewed: 2026-10-28\nsource: หนังสือ ว 1 | https://example.go.th/w1.pdf\nsource: ระเบียบ ข้อ 79\n"
        "-->\n<p>x</p>", encoding="utf-8")
    c = _anon()
    lst = c.get("/knowledge").text
    # แถบหมวดครบทุกหมวดแม้มีบทความหมวดเดียว หมวดว่างเป็นสีจาง
    assert 'data-cat="งานการเงิน" class="soon"' in lst and 'data-cat="อัปเดตระบบ" class="soon"' in lst
    assert '<b class="kl-type">อธิบายระเบียบ</b>' in lst
    page = c.get("/knowledge/rule-one").text
    assert 'href="https://example.go.th/w1.pdf"' in page and "<li>ระเบียบ ข้อ 79</li>" in page
    assert "ตรวจทานกับเอกสารต้นทางล่าสุด" in page
    assert 'class="kb-draftbar"' not in page      # แถบเหลืองเห็นเฉพาะร่าง (ผู้ดูแล)
