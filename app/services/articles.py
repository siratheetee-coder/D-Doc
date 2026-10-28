# -*- coding: utf-8 -*-
"""
articles.py - คลังความรู้ (บทความสาธารณะสำหรับ SEO)

บทความ 1 เรื่อง = ไฟล์ app/content/articles/<slug>.html
ส่วนหัวไฟล์เป็นคอมเมนต์ HTML บอกข้อมูลบทความ บรรทัดละ 1 ค่า แล้วตามด้วยเนื้อหา HTML

    <!--
    title: ว.119 ตาราง 1 กับ ตาราง 2 ต่างกันยังไง
    description: สรุปสั้น ๆ สำหรับผลค้นหา Google (ไม่เกิน ~155 ตัวอักษร)
    date: 2026-10-27
    updated: 2026-11-02          (ไม่ใส่ก็ได้)
    category: งานพัสดุ
    draft: true                  (true = ร่าง ยังไม่ขึ้นเว็บ / false = เผยแพร่)
    image: w119-cover.jpg        (ไม่ใส่ก็ได้) รูปปก วางไฟล์ไว้ที่ app/static/knowledge/
    image_alt: คำอธิบายรูป        (ไม่ใส่ก็ได้)
    cover: ว.119                 (ไม่ใส่ก็ได้) คำตัวใหญ่บนปกเมื่อไม่มีรูป
    featured: true               (ไม่ใส่ก็ได้) ขึ้นเป็นเรื่องแนะนำบนสุดของหน้ารวม
    type: อธิบายระเบียบ          (ไม่ใส่ก็ได้) ป้ายชนิดบทความ: อธิบายระเบียบ / คู่มือใช้งาน / อัปเดตระบบ
    reviewed: 2026-10-28         (ไม่ใส่ก็ได้) วันที่ตรวจทานเนื้อหากับเอกสารต้นทางล่าสุด
    source: ชื่อเอกสาร | https://ลิงก์เอกสารต้นทาง   (ใส่ได้หลายบรรทัด ไม่มีลิงก์ก็ใส่แค่ชื่อ) ไฟล์ของเราเองวางที่ app/static/knowledge/refs/
    -->
    <p>เนื้อหา...</p>

ร่าง (draft: true) ไม่ขึ้นในหน้ารวม ไม่อยู่ใน sitemap และเปิดได้เฉพาะผู้ดูแลระบบ (superadmin)
เนื้อหาเป็น HTML ที่เราเขียนเองใน repo จึงแสดงแบบไม่ escape
รูปในเนื้อหาใช้ <figure><img src="/static/knowledge/xxx.jpg" alt="..."><figcaption>...</figcaption></figure>
"""
import re
from datetime import date
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "content" / "articles"
_SLUG = re.compile(r"^[a-z0-9-]{3,80}$")
_HEAD = re.compile(r"^\s*<!--(.*?)-->", re.S)
_cache: dict = {}          # path -> (mtime, article)


def _parse(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8")
    m = _HEAD.match(raw)
    if not m:
        return None
    meta, sources = {}, []
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "source" and v:
                name, _, url = v.partition("|")
                url = url.strip()
                sources.append({"name": name.strip(), "url": url if url.startswith(("http://", "https://", "/static/")) else ""})
            else:
                meta[k] = v
    try:
        d = date.fromisoformat(meta.get("date", ""))
    except ValueError:
        return None
    try:
        upd = date.fromisoformat(meta["updated"]) if meta.get("updated") else d
    except ValueError:
        upd = d
    try:
        reviewed = date.fromisoformat(meta["reviewed"]) if meta.get("reviewed") else None
    except ValueError:
        reviewed = None
    if not meta.get("title"):
        return None
    body = raw[m.end():].strip()
    # สารบัญ: ใส่ id ให้หัวข้อ <h2> ทุกตัว (s1, s2, ...) แล้วเก็บชื่อไว้ทำลิงก์ข้ามไปหัวข้อ
    toc = []

    def _anchor(mm):
        toc.append({"id": f"s{len(toc) + 1}", "text": re.sub(r"<[^>]+>", "", mm.group(1)).strip()})
        return f'<h2 id="{toc[-1]["id"]}">{mm.group(1)}</h2>'
    body = re.sub(r"<h2>(.*?)</h2>", _anchor, body, flags=re.S)
    img = meta.get("image", "")
    if img and not img.startswith(("/", "http://", "https://")):
        img = "/static/knowledge/" + img
    chars = len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", body)))   # ภาษาไทยไม่เว้นวรรคระหว่างคำ นับตัวอักษรแทน
    return {"slug": path.stem, "title": meta["title"], "description": meta.get("description", ""),
            "category": meta.get("category", ""), "date": d, "updated": upd,
            "draft": meta.get("draft", "true").lower() != "false",
            "image": img, "image_alt": meta.get("image_alt", "") or meta["title"],
            "type": meta.get("type", ""), "reviewed": reviewed, "sources": sources,
            "cover": meta.get("cover", ""), "featured": meta.get("featured", "").lower() == "true",
            "body": body, "toc": toc, "minutes": max(1, round(chars / 450))}


# ไอคอน + สีประจำหมวด (ใช้ในหน้ารวมและหัวบทความ)
CATEGORY_STYLE = {
    "งานพัสดุ": ("ic-package", "#2563eb", "#7c3aed"),
    "งานการเงิน": ("ic-coins", "#059669", "#0d9488"),
    "งานธุรการ": ("ic-file", "#7c3aed", "#c026d3"),
    "งานวิชาการ": ("ic-book", "#ea580c", "#db2777"),
    "งานบุคคล": ("ic-users", "#0891b2", "#2563eb"),
    "งานอาหารกลางวัน": ("ic-food", "#d97706", "#dc2626"),
    "อัปเดตระบบ": ("ic-star", "#4f46e5", "#db2777"),
}
# แถบหมวดในหน้ารวม (แสดงครบทุกหมวดแม้ยังไม่มีบทความ ให้รู้ว่าคลังนี้ครอบคลุมอะไร): (ชื่อสั้นบนปุ่ม, category)
CATEGORY_TABS = [("พัสดุ", "งานพัสดุ"), ("การเงิน", "งานการเงิน"), ("ธุรการ", "งานธุรการ"), ("วิชาการ", "งานวิชาการ"),
                 ("บุคคล", "งานบุคคล"), ("อาหารกลางวัน", "งานอาหารกลางวัน"), ("อัปเดตระบบ", "อัปเดตระบบ")]
DEFAULT_STYLE = ("ic-file", "#2563eb", "#7c3aed")


def style_of(category: str) -> dict:
    icon, c1, c2 = CATEGORY_STYLE.get(category or "", DEFAULT_STYLE)
    return {"icon": icon, "c1": c1, "c2": c2}


def _load(path: Path):
    mt = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    art = _parse(path)
    _cache[path] = (mt, art)
    return art


def all_articles(include_drafts: bool = False) -> list:
    """บทความเรียงใหม่สุดก่อน"""
    if not DIR.exists():
        return []
    out = []
    for p in DIR.glob("*.html"):
        if not _SLUG.match(p.stem):
            continue
        a = _load(p)
        if a and (include_drafts or not a["draft"]):
            out.append(a)
    return sorted(out, key=lambda a: (a["date"], a["slug"]), reverse=True)


def get(slug: str, include_drafts: bool = False):
    if not _SLUG.match(slug or ""):
        return None
    p = DIR / f"{slug}.html"
    if not p.exists():
        return None
    a = _load(p)
    if not a or (a["draft"] and not include_drafts):
        return None
    return a


def related(art: dict, n: int = 3) -> list:
    """บทความหมวดเดียวกันก่อน แล้วค่อยเติมเรื่องอื่น"""
    rest = [a for a in all_articles() if a["slug"] != art["slug"]]
    same = [a for a in rest if a["category"] == art["category"]]
    other = [a for a in rest if a["category"] != art["category"]]
    return (same + other)[:n]
