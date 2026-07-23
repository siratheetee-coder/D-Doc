# -*- coding: utf-8 -*-
"""
ai_extract.py
-------------
อ่านข้อมูลเรื่องจัดซื้อ/จัดจ้างจากข้อความเอกสารด้วย AI (Anthropic Claude API)
เป็นทางเลือก (ออปชัน) - ต้องตั้งค่า API key ในตั้งค่าโรงเรียน + เครื่องต้องต่อเน็ต
ดึงได้ครบกว่ารวมรายการพัสดุและกรรมการ (เทียบกับ heuristic ออฟไลน์)

ใช้ urllib (stdlib) เรียก REST API โดยตรง ไม่ต้องเพิ่ม dependency
"""
import re
import json
import urllib.request

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5"   # สกัดจากข้อความ: โมเดลเล็ก เร็ว ประหยัด
# อ่านรูปถ่าย/สแกน (คำไทยยาก/ลายมือ) ใช้โมเดลที่แม่นกว่าเพื่อลดการอ่านผิด
_VISION_MODEL = "claude-sonnet-5"

_PROMPT = """คุณคือผู้ช่วยสกัดข้อมูลจากเอกสารราชการไทย (เรื่องจัดซื้อ/จัดจ้างของโรงเรียน)
อ่านข้อความด้านล่างแล้วตอบกลับเป็น JSON เท่านั้น (ไม่มีคำอธิบายอื่น) ตามคีย์นี้:
{
 "proc_type": "ซื้อ หรือ จ้าง",
 "subject": "ชื่อเรื่อง/รายการที่จัดซื้อ (ไม่ต้องมีคำว่า รายงานขอซื้อ/จ้าง)",
 "memo_no": "เลขที่บันทึก เช่น 1/2569",
 "request_date": "วันที่รายงาน รูปแบบ DD/MM/YYYY เป็น พ.ศ.",
 "department": "ฝ่าย/งานที่ขอ",
 "project_name": "ชื่อโครงการ",
 "purpose": "เหตุผลความจำเป็น",
 "budget_source": "แหล่งงบประมาณ",
 "delivery_days": จำนวนวันส่งมอบ (ตัวเลข),
 "vendor_name": "ชื่อผู้ขาย/ผู้รับจ้าง",
 "order_no": "เลขที่ใบสั่งซื้อ/จ้าง (ถ้ามี)",
 "command_no": "เลขที่คำสั่งแต่งตั้ง (ถ้ามี)",
 "items": [{"name":"ชื่อพัสดุ","qty":จำนวน,"unit":"หน่วย","unit_price":ราคาต่อหน่วย}],
 "inspectors": [{"name":"ชื่อ-สกุล","position":"ตำแหน่ง","role":"ประธานกรรมการ/กรรมการ/กรรมการและเลขานุการ/ผู้ตรวจรับ"}]
}
ถ้าฟิลด์ใดไม่พบ ให้ใส่ค่าว่าง "" หรือ [] (ตัวเลขใส่ 0). ใช้เลขอารบิก. คงข้อความไทยตามต้นฉบับ.

ข้อความเอกสาร:
---
{TEXT}
---
ตอบเป็น JSON เท่านั้น:"""


_IMG_PROMPT = """คุณคือผู้ช่วยอ่าน "รายการพัสดุ" จากรูปถ่าย/สแกนเอกสารไทย (ใบเสนอราคา/บิล/รายการขอซื้อ)
อ่านเฉพาะแถวรายการสินค้า/พัสดุในรูป แล้วตอบกลับเป็น JSON เท่านั้น (ไม่มีคำอธิบายอื่น):
{"items":[{"name":"ชื่อพัสดุ","qty":จำนวน,"unit":"หน่วยนับ","unit_price":ราคาต่อหน่วย}]}
- เอาเฉพาะรายการพัสดุจริง ไม่เอาหัวตาราง ยอดรวม ภาษี หรือข้อความลงนาม
- ตัวเลขใช้เลขอารบิก ไม่ต้องมีจุลภาค ถ้าไม่ทราบจำนวนใส่ 1 ถ้าไม่ทราบราคาใส่ 0
- อ่านชื่อพัสดุให้ครบทั้งบรรทัด (รวมขนาด/รุ่น/สี/หน่วยบรรจุ) สะกดคำไทยให้ถูกต้อง
  ถ้าตัวอักษรเลือน ให้เดาคำที่สมเหตุสมผลที่สุดตามบริบทพัสดุสำนักงาน/โรงเรียน
- คงชื่อภาษาไทยตามรูป ตอบเป็น JSON เท่านั้น"""


def extract_items_from_image(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    """ส่งรูปให้ AI (vision) อ่านรายการพัสดุ คืน {'items':[...], 'ok':True} หรือ {'error': ...}"""
    if not (api_key or "").strip():
        return {"error": "no_key"}
    if not image_bytes:
        return {"error": "no_image"}
    import base64
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = json.dumps({
        "model": _VISION_MODEL, "max_tokens": 2000,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": media_type, "data": b64}},
            {"type": "text", "text": _IMG_PROMPT},
        ]}],
    }).encode("utf-8")
    req = urllib.request.Request(_API_URL, data=body, headers={
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": "request", "detail": str(e)[:200]}
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"error": "no_json"}
    try:
        result = json.loads(m.group(0))
        return {"items": result.get("items", []), "ok": True}
    except Exception:
        return {"error": "bad_json"}


def extract_with_ai(text: str, api_key: str) -> dict:
    """ส่งข้อความให้ AI สกัดข้อมูล คืน dict (หรือ {'error': ...} ถ้าพลาด)"""
    if not (api_key or "").strip():
        return {"error": "no_key"}
    if not (text or "").strip():
        return {"error": "no_text"}
    prompt = _PROMPT.replace("{TEXT}", text[:18000])   # จำกัดความยาว
    body = json.dumps({
        "model": _MODEL, "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(_API_URL, data=body, headers={
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": "request", "detail": str(e)[:200]}
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"error": "no_json"}
    try:
        result = json.loads(m.group(0))
        result["ok"] = True
        return result
    except Exception:
        return {"error": "bad_json"}


_LETTER_PROMPT = """คุณคือผู้ช่วยร่าง "หนังสือราชการภายนอก" ของโรงเรียนไทย ให้ถูกต้องตามระเบียบงานสารบรรณ
เขียนด้วยภาษาราชการสุภาพ กระชับ ครบถ้วน

ข้อมูลที่ได้รับ:
- โรงเรียนผู้ส่ง: {SCHOOL}
- เรื่อง: {SUBJECT}
- เรียน (ผู้รับ): {TO}
- จุดประสงค์/ประเด็นสำคัญ: {POINTS}
- รายละเอียดเพิ่มเติม: {DETAIL}

ให้ตอบกลับเป็น JSON เท่านั้น (ไม่มีคำอธิบายอื่น):
{
 "subject": "เรื่อง (กระชับ เป็นทางการ)",
 "body": "เนื้อความหนังสือ ขึ้นต้นด้วย 'ด้วย...' หรือ 'ตามที่...' อธิบายเหตุ ความประสงค์ และปิดท้ายด้วย 'จึงเรียนมาเพื่อ...' โดยเว้นบรรทัดว่างคั่นย่อหน้า (ไม่ต้องมีคำลงท้าย ไม่ต้องมีลายเซ็น)"
}
- ใช้สรรพนามและถ้อยคำราชการ เช่น ขอความอนุเคราะห์/ขอเรียนเชิญ/ขออนุญาต ตามบริบท
- คงข้อเท็จจริงตามที่ให้มา อย่าแต่งข้อมูลเท็จ (วันเวลา/สถานที่ที่ไม่ทราบให้เว้นเป็น ...)
ตอบเป็น JSON เท่านั้น:"""


def write_official_letter(info: dict, api_key: str) -> dict:
    """ให้ AI ร่างหนังสือราชการ คืน {'subject':..., 'body':..., 'ok':True} หรือ {'error':...}"""
    if not (api_key or "").strip():
        return {"error": "no_key"}
    prompt = (_LETTER_PROMPT
              .replace("{SCHOOL}", (info.get("school") or "")[:120])
              .replace("{SUBJECT}", (info.get("subject") or "")[:300])
              .replace("{TO}", (info.get("to") or "")[:200])
              .replace("{POINTS}", (info.get("points") or "")[:1500])
              .replace("{DETAIL}", (info.get("detail") or "")[:2500]))
    body = json.dumps({
        "model": _VISION_MODEL, "max_tokens": 2000,   # ใช้โมเดลที่เขียนดีกว่า
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(_API_URL, data=body, headers={
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": "request", "detail": str(e)[:200]}
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"error": "no_json"}
    try:
        result = json.loads(m.group(0))
        result["ok"] = True
        return result
    except Exception:
        return {"error": "bad_json"}


def _ai_write_json(prompt: str, api_key: str) -> dict:
    """ส่ง prompt ให้ AI (โมเดลเขียนดี) คาดหวังผลเป็น JSON คืน dict + ok/error"""
    if not (api_key or "").strip():
        return {"error": "no_key"}
    body = json.dumps({
        "model": _VISION_MODEL, "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(_API_URL, data=body, headers={
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": "request", "detail": str(e)[:200]}
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"error": "no_json"}
    try:
        result = json.loads(m.group(0))
        result["ok"] = True
        return result
    except Exception:
        return {"error": "bad_json"}


_MEMO_PROMPT = """คุณคือผู้ช่วยร่าง "บันทึกข้อความ" (หนังสือราชการภายใน) ของโรงเรียนไทย ตามระเบียบงานสารบรรณ
ภาษาราชการสุภาพ กระชับ ครบถ้วน

ข้อมูล:
- โรงเรียน: {SCHOOL}
- จากหน่วยงาน/ฝ่าย: {FROM}
- เรียน (ผู้รับ): {TO}
- เรื่อง: {SUBJECT}
- ประเด็น/รายละเอียดที่ต้องการสื่อ: {POINTS}

ตอบกลับเป็น JSON เท่านั้น:
{
 "subject": "เรื่อง (กระชับ เป็นทางการ)",
 "body": "เนื้อความบันทึกข้อความ ขึ้นต้นด้วย 'ด้วย...' หรือ 'ตามที่...' อธิบายเหตุและความประสงค์ ปิดท้ายด้วย 'จึงเรียนมาเพื่อโปรด...' (เช่น โปรดทราบ/พิจารณา/อนุมัติ) เว้นบรรทัดว่างคั่นย่อหน้า ไม่ต้องมีหัวกระดาษ/ลายเซ็น"
}
- คงข้อเท็จจริงตามที่ให้มา อย่าแต่งข้อมูลเท็จ (ที่ไม่ทราบให้เว้น ...)
ตอบเป็น JSON เท่านั้น:"""


_ORDER_PROMPT = """คุณคือผู้ช่วยร่าง "คำสั่งโรงเรียน" ของโรงเรียนไทย ตามระเบียบงานสารบรรณและแบบคำสั่งราชการ
ภาษาราชการสุภาพ ถูกต้องตามรูปแบบคำสั่ง

ข้อมูล:
- โรงเรียน: {SCHOOL}
- เรื่อง (คำสั่ง): {SUBJECT}
- ประเด็น/รายละเอียด (เหตุผล วัตถุประสงค์ ผู้ได้รับมอบหมาย หน้าที่ วันเวลา ฯลฯ): {POINTS}

ตอบกลับเป็น JSON เท่านั้น:
{
 "subject": "เรื่อง (ขึ้นต้นด้วยคำกริยา เช่น แต่งตั้ง.../มอบหมาย.../ให้...)",
 "body": "เนื้อความคำสั่ง ขึ้นต้นด้วย 'ด้วย...' หรือ 'เพื่อให้...' อธิบายเหตุและอำนาจ แล้วระบุการสั่ง (เช่น จึงแต่งตั้ง.../มอบหมายให้...) ปิดท้ายด้วย 'ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป' เว้นบรรทัดว่างคั่นย่อหน้า ไม่ต้องมีหัวครุฑ/เลขที่/ลายเซ็น/สั่ง ณ วันที่"
}
- คงข้อเท็จจริงตามที่ให้มา อย่าแต่งข้อมูลเท็จ (ที่ไม่ทราบให้เว้น ...)
ตอบเป็น JSON เท่านั้น:"""


def write_memo(info: dict, api_key: str) -> dict:
    """ให้ AI ร่างบันทึกข้อความ คืน {'subject':..., 'body':..., 'ok':True} หรือ {'error':...}"""
    prompt = (_MEMO_PROMPT
              .replace("{SCHOOL}", (info.get("school") or "")[:120])
              .replace("{FROM}", (info.get("from_dept") or "")[:120])
              .replace("{TO}", (info.get("to") or "")[:200])
              .replace("{SUBJECT}", (info.get("subject") or "")[:300])
              .replace("{POINTS}", (info.get("points") or "")[:2500]))
    return _ai_write_json(prompt, api_key)


def write_order(info: dict, api_key: str) -> dict:
    """ให้ AI ร่างคำสั่งโรงเรียน คืน {'subject':..., 'body':..., 'ok':True} หรือ {'error':...}"""
    prompt = (_ORDER_PROMPT
              .replace("{SCHOOL}", (info.get("school") or "")[:120])
              .replace("{SUBJECT}", (info.get("subject") or "")[:300])
              .replace("{POINTS}", (info.get("points") or "")[:2500]))
    return _ai_write_json(prompt, api_key)
