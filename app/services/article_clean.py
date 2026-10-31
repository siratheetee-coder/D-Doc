# -*- coding: utf-8 -*-
"""
article_clean.py - กรองเนื้อหาบทความจากกล่องเขียนในคอนโซล ก่อนเก็บและแสดงบนเว็บสาธารณะ

หน้าบทความแสดง HTML ตรง ๆ (a.body|safe) จึงเก็บเฉพาะแท็กและแอตทริบิวต์ที่อนุญาตเท่านั้น
ข้อความที่วางจาก Word / Google Docs มีสไตล์ติดมาเยอะ ตรงนี้ล้างให้เหลือโครงสร้าง
  - span ที่เป็นตัวหนา/เอียงด้วย style แปลงเป็น <b>/<i>
  - Google Docs ห่อทั้งเอกสารด้วย <b style="font-weight:normal"> ต้องไม่กลายเป็นตัวหนาทั้งเรื่อง
รูปต้องอยู่ในเว็บเราเท่านั้น (/knowledge/media/ หรือ /static/knowledge/) รูปจากที่อื่นหรือ data: ตัดทิ้ง
"""
import html
import re
from html.parser import HTMLParser

ALLOWED = {"p", "br", "h2", "h3", "ul", "ol", "li", "b", "i", "u", "a", "img", "figure", "figcaption",
           "blockquote", "table", "thead", "tbody", "tr", "th", "td", "hr"}
RENAME = {"h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "strong": "b", "em": "i"}
VOID = {"br", "img", "hr"}
BLOCK = {"p", "h2", "h3", "ul", "ol", "table", "figure", "blockquote", "hr"}
# ตัดทั้งแท็กและเนื้อใน
DROP = {"script", "style", "iframe", "object", "head", "title", "svg", "math", "template",
        "noscript", "xml", "select", "textarea", "canvas", "audio", "video"}
# เปิดแท็กเดิมซ้ำโดยไม่ปิด = ปิดตัวก่อนหน้าให้ (<p>ก<p>ข)
SELF_CLOSING = {"p", "li", "tr", "td", "th"}
IMG_PREFIX = ("/knowledge/media/", "/static/knowledge/")


def safe_url(url: str) -> str:
    """ลิงก์ที่ใช้ได้ (http/https/mailto/ลิงก์ในเว็บ) ไม่ผ่านคืน '' กัน javascript: ที่แทรกช่องว่าง"""
    u = re.sub(r"[\x00-\x20\x7f]+", "", url or "")
    low = u.lower()
    if low.startswith(("http://", "https://", "mailto:", "#")):
        return u
    if u.startswith("/") and not u.startswith(("//", "/\\")):
        return u
    return ""


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []        # (แท็กต้นฉบับ, [แท็กที่ต้องปิด])
        self.skip = 0          # อยู่ในแท็กที่ตัดทิ้ง
        self.skip_tag = None
        self.blocks = 0        # บล็อกที่เปิดอยู่
        self.auto_p = False    # เปิด <p> ให้เองกับข้อความที่ลอยอยู่นอกบล็อก
        self.dropped_images = 0

    def _open_auto(self):
        if not self.blocks and not self.auto_p:
            self.out.append("<p>")
            self.auto_p = True

    def _close_auto(self):
        if self.auto_p:
            self.out.append("</p>")
            self.auto_p = False

    def _style_tags(self, tag, style):
        s = (style or "").replace(" ", "").lower()
        m = re.search(r"font-weight:(\w+)", s)
        bold = bool(m and (m.group(1) in ("bold", "bolder") or (m.group(1).isdigit() and int(m.group(1)) >= 600)))
        ital = "font-style:italic" in s
        under = "text-decoration:underline" in s or "text-decoration-line:underline" in s
        return [t for t, on in (("b", bold), ("i", ital), ("u", under)) if on]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if self.skip:
            if tag == self.skip_tag:
                self.skip += 1
            return
        if tag in DROP:
            self.skip, self.skip_tag = 1, tag
            return
        tag = RENAME.get(tag, tag)
        if tag == "b" and re.search(r"font-weight:\s*(normal|[1-5]00)", a.get("style", ""), re.I):
            self.stack.append((tag, []))        # Google Docs ห่อทั้งเอกสาร ไม่ใช่ตัวหนาจริง
            return
        if tag in ("span", "font"):
            closers = self._style_tags(tag, a.get("style"))
            if closers:
                self._open_auto()
                self.out.extend(f"<{t}>" for t in closers)
            self.stack.append((tag, closers[::-1]))
            return
        if tag == "div":
            self._close_auto()
            self.stack.append((tag, []))
            return
        if tag not in ALLOWED:
            return
        if tag == "img":
            self._img(a)
            return
        if tag in SELF_CLOSING and self.stack and self.stack[-1][0] == tag:
            self._pop_to(len(self.stack) - 1)
        if tag in BLOCK:
            self._close_auto()
            if self.stack and self.stack[-1][0] == "p":     # บล็อกซ้อนใน <p> ไม่ได้ ปิดย่อหน้าก่อน
                self._pop_to(len(self.stack) - 1)
        elif tag not in ("li", "tr", "td", "th", "thead", "tbody", "figcaption"):
            self._open_auto()
        self.out.append("<" + tag + self._attrs(tag, a) + ">")
        if tag in VOID:
            return
        if tag in BLOCK:
            self.blocks += 1
        self.stack.append((tag, [tag]))

    def _img(self, a):
        src = a.get("src", "").strip()
        if not src.startswith(IMG_PREFIX) or ".." in src:
            self.dropped_images += 1
            return
        self._open_auto()
        self.out.append(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(a.get("alt", "")[:300], quote=True)}">')

    def _attrs(self, tag, a):
        if tag == "a":
            url = safe_url(a.get("href", ""))
            if not url:
                return ""
            ext = url.lower().startswith(("http://", "https://"))
            return f' href="{html.escape(url, quote=True)}"' + (' rel="noopener" target="_blank"' if ext else "")
        if tag in ("td", "th"):
            return "".join(f' {k}="{a[k]}"' for k in ("colspan", "rowspan") if a.get(k, "").isdigit())
        cls = a.get("class", "").split()
        if tag == "p" and "note" in cls:
            return ' class="note"'
        if tag == "ol" and "full" in cls:
            return ' class="full"'
        return ""

    def _pop_to(self, depth):
        """ปิดทุกแท็กที่อยู่เหนือตำแหน่ง depth"""
        while len(self.stack) > depth:
            orig, closers = self.stack.pop()
            for t in closers:
                self.out.append(f"</{t}>")
                if t in BLOCK:
                    self.blocks -= 1
            if orig == "div":
                self._close_auto()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip_tag:
                self.skip -= 1
            return
        tag = RENAME.get(tag, tag)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self._pop_to(i)
                return

    def handle_data(self, data):
        if self.skip:
            return
        if data.strip():
            self._open_auto()
        elif not self.blocks and not self.auto_p:
            return                 # ช่องว่างระหว่างบล็อก ไม่ต้องเก็บ
        self.out.append(html.escape(data, quote=False))

    def finish(self):
        self._pop_to(0)
        self._close_auto()
        return "".join(self.out)


def clean(raw: str) -> tuple:
    """กรอง HTML คืน (เนื้อหาที่ปลอดภัย, จำนวนรูปที่ตัดทิ้ง)"""
    # คอมเมนต์เงื่อนไขของ Word (<!--[if ...]>) และแท็กแบบ o:p ไม่ถูกเก็บอยู่แล้ว
    c = _Cleaner()
    c.feed(raw or "")
    c.close()
    out = c.finish()
    empty = re.compile(r"<(p|h2|h3|li|figcaption|blockquote)>(?:[\s\xa0]|<br>)*</\1>")
    while True:
        new = empty.sub("", out)
        if new == out:
            break
        out = new
    return out.strip(), c.dropped_images


def plain_len(body: str) -> int:
    """จำนวนตัวอักษรในเนื้อหา (ไว้เช็กว่าเขียนอะไรมาบ้าง)"""
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", body or "")))
