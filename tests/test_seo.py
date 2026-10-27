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
    assert 'og:image" content="https://www.easy-ekkasan.com/static/' in r.text
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
    # ล็อกอินแล้วยังเห็นแบบในระบบ (มีเมนูด้านข้าง)
    assert env.get("/guide").status_code == 200
    # หน้าในระบบอื่นยังต้องล็อกอิน
    assert c.get("/finance", follow_redirects=False).headers["location"] == "/login"
