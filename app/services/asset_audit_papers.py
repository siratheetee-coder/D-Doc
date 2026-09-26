# -*- coding: utf-8 -*-
"""
asset_audit_papers.py - กระดาษทำการของผู้ตรวจสอบพัสดุ + บัญชีพัสดุชำรุดแยกตามสภาพ

อิงแบบฟอร์มใน "แนวทางการตรวจสอบพัสดุประจำปีและการจำหน่ายพัสดุสำหรับสถานศึกษา"
(ฉบับปรับปรุง พ.ศ. 2563 หน่วยตรวจสอบภายใน สพป.นครราชสีมา เขต 1)

กระดาษทำการ 4 ชุด - เป็นหลักฐานว่าคณะกรรมการตรวจอะไรไปบ้าง ซึ่ง สตง. ขอดู
  ชุด ก  รายละเอียดการตรวจสอบการรับจ่ายพัสดุ - วัสดุ      (เทียบเอกสารกับบัญชีวัสดุ)
  ชุด ข  รายละเอียดการตรวจสอบการรับจ่ายพัสดุ - ครุภัณฑ์   (เทียบเอกสารกับทะเบียนคุมทรัพย์สิน)
  ชุด ค  รายละเอียดการตรวจสอบพัสดุ ณ 30 ก.ย. - วัสดุคงเหลือและสภาพการใช้งาน
  ชุด ง  รายละเอียดการตรวจสอบพัสดุ ณ 30 ก.ย. - ครุภัณฑ์คงเหลือและสภาพการใช้งาน

บัญชีพัสดุที่ต้องจำหน่าย ฉบับ 2563 แยกเป็น 4 บัญชีตามสภาพ (ของเดิมในระบบเป็นใบรวม
14 คอลัมน์ ซึ่งเป็นแบบเก่า - เก็บไว้ทั้งคู่ให้โรงเรียนเลือกตามที่เขตขอ)

หนังสือแจ้งผลการตรวจสอบ ต้องส่ง 2 ทาง: สำนักงานเขตพื้นที่การศึกษา และ สตง.
"""
from docx import Document
from docx.shared import Cm

from app.database import get_data_dir
from app.services.doc_page import set_a4, tidy
from app.thai_utils import thai_date
from app.services.build_templates import (
    _font, _krut_center, _p, _p_runs, _sign_table, _set_cell, _hr,
    _repeat_header_row, _no_split_row, _no_borders, _fixed_cols,
)
from app.services.asset_audit_doc import (
    _safe, _save, _thai_be, _office, _director_line, _members, _center_table,
    _blank_doc_or_break, _landscape_section, _BLANK,
)
from app.services.asset_utils import material_balance

BOX = "☐"          # ☐ ช่องติ๊ก
TICK = "☑"         # ☑ ช่องที่ระบบติ๊กให้แล้ว

# สภาพครุภัณฑ์ -> ช่องที่ต้องติ๊กในกระดาษทำการชุด ง
_COND_COL = {"ใช้งาน": "ใช้การได้", "ชำรุด": "ชำรุด", "เสื่อมสภาพ": "เสื่อมสภาพ",
             "ไม่ใช้": "ไม่ใช้งาน", "สูญไป": None, "จำหน่ายแล้ว": None}

# บัญชีพัสดุที่ต้องจำหน่าย แยก 4 ฉบับตามสภาพ (ชื่อบัญชี, สถานะที่เข้าข่าย, ชื่อช่องเหตุผล)
LEDGERS = [
    ("damaged", "บัญชีรายการครุภัณฑ์ที่ชำรุด", ["ชำรุด"], "รายละเอียดการชำรุด"),
    ("worn", "บัญชีรายการครุภัณฑ์เสื่อมสภาพ", ["เสื่อมสภาพ"], "รายละเอียดการเสื่อมสภาพ"),
    ("lost", "บัญชีรายการครุภัณฑ์ที่สูญไป", ["สูญไป"], "รายละเอียดการสูญไป"),
    ("idle", "บัญชีรายการครุภัณฑ์ไม่จำเป็นต้องใช้ในหน่วยงานของรัฐ", ["ไม่ใช้"],
     "เหตุผลที่ไม่จำเป็นต้องใช้ในโรงเรียนแล้ว"),
]


def _new(landscape=False):
    doc = Document()
    set_a4(doc, landscape=landscape)
    _font(doc)
    return doc


def _land(doc):
    """ขึ้นหน้านอนสำหรับฉบับถัดไป · ถ้าเอกสารยังว่าง (ฉบับแรกของชุด) ไม่ต้องขึ้น section ใหม่
    ไม่งั้นจะได้หน้าแรกเปล่าติดมาทุกครั้ง"""
    if doc.paragraphs or doc.tables:
        _landscape_section(doc)


def _head(doc, school, title, sub=None, year=None):
    name = (school.name or "").strip() or _BLANK
    _p(doc, name, align="center", bold=True, size=16, after=0)
    _p(doc, title, align="center", bold=True, size=17, after=0)
    if sub:
        _p(doc, sub, align="center", size=15, after=0)
    _p(doc, "", after=4)


def _inspector_sign(doc, ctx, *, single=None):
    """ลงชื่อท้ายกระดาษทำการ - คนเดียวหรือคณะกรรมการตามที่โรงเรียนแต่งตั้ง"""
    mem = _members(ctx)
    if single is None:
        single = bool(ctx.get("single"))
    _p(doc, "", after=6)
    if single or len(mem) <= 1:
        m = mem[0] if mem else {}
        _sign_table(doc, [[
            ("ลงชื่อ ...................................... ผู้ตรวจสอบพัสดุประจำปี", "center"),
            (f"( {(m.get('name') or '').strip() or _BLANK} )", "center"),
            (f"ตำแหน่ง {(m.get('position') or '').strip() or '..................'}", "center"),
            (f"วันที่ {_BLANK}", "center"),
        ]], gap=False)
        return
    cols = []
    roles = ["ประธานกรรมการ", "กรรมการ", "กรรมการ"]
    for i, m in enumerate(mem[:3]):
        cols.append([
            ("ลงชื่อ ..................................", "center"),
            (f"( {(m.get('name') or '').strip() or _BLANK} )", "center"),
            ((m.get("role") or roles[min(i, 2)]).strip(), "center"),
        ])
    _sign_table(doc, cols, gap=False)


def _tick_cell(cell, on):
    _set_cell(cell, TICK if on else BOX, align="center", size=13)


# ==================================================== ชุด ก  วัสดุ รับ-จ่าย
_WP_A_W = [Cm(1.2), Cm(5.4), Cm(2.0), Cm(2.6), Cm(2.6), Cm(2.6), Cm(2.6), Cm(2.6), Cm(2.6)]


def render_wp_material_flow(school, ctx, materials, doc=None):
    """ชุด ก - เทียบเอกสารฝ่ายรับ/ฝ่ายจ่าย กับการบันทึกในบัญชีวัสดุ

    ดึงการเคลื่อนไหววัสดุในปีงบที่ตรวจมาเรียงให้ ผู้ตรวจสอบแค่ติ๊กว่าตรงหรือไม่ตรง
    """
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _head(doc, school, "รายละเอียดการตรวจสอบการรับจ่ายพัสดุ",
          f"ชุดที่ 1  วัสดุ  ประจำปีงบประมาณ พ.ศ. {year}")

    heads1 = ["ลำดับ\nที่", "รายการ", "จำนวน", "ราคา", "วันที่", "อ้างอิงเอกสาร",
              "ถูกต้อง", "ไม่ถูกต้อง", "หมายเหตุ"]
    rows = []
    for m in materials or []:
        for t in sorted(m.txns, key=lambda x: (x.date or _MIN, x.id)):
            if (t.kind or "in") != "in":
                continue
            rows.append((m.name or "", f"{(t.qty or 0):g} {m.unit or ''}",
                         f"{(t.unit_price or 0) * (t.qty or 0):,.2f}",
                         thai_date(t.date) if t.date else "", (t.ref or "").strip()))
    _flow_table(doc, "1. เอกสารฝ่ายรับ เทียบกับการบันทึกในบัญชีวัสดุ", heads1, rows)

    heads2 = ["ลำดับ\nที่", "รายการ", "จำนวน", "ผู้เบิก", "วันที่", "อ้างอิงเอกสาร",
              "ถูกต้อง", "ไม่ถูกต้อง", "หมายเหตุ"]
    rows2 = []
    for m in materials or []:
        for t in sorted(m.txns, key=lambda x: (x.date or _MIN, x.id)):
            if (t.kind or "in") == "in":
                continue
            rows2.append((m.name or "", f"{(t.qty or 0):g} {m.unit or ''}",
                          (t.note or "").strip(),
                          thai_date(t.date) if t.date else "", (t.ref or "").strip()))
    _p(doc, "", after=6)
    _flow_table(doc, "2. เอกสารฝ่ายจ่าย เทียบกับการบันทึกในบัญชีวัสดุ", heads2, rows2)
    _inspector_sign(doc, ctx)
    return _save(doc, f"กระดาษทำการ ชุด1 รับจ่ายวัสดุ_ปีงบ{year}") if own else doc


from datetime import datetime as _dtm
_MIN = _dtm(1, 1, 1)


def _flow_table(doc, caption, heads, rows, *, min_rows=8):
    _p(doc, caption, bold=True, size=15, after=3)
    n = max(len(rows), min_rows)
    t = doc.add_table(rows=1 + n, cols=len(_WP_A_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _WP_A_W)
    _center_table(t)
    hdr = t.rows[0]
    _repeat_header_row(hdr)
    _no_split_row(hdr)
    for c, h, w in zip(hdr.cells, heads, _WP_A_W):
        _set_cell(c, h, bold=True, align="center", size=13)
        c.width = w
    for i in range(n):
        row = t.rows[1 + i]
        _no_split_row(row)
        data = rows[i] if i < len(rows) else None
        vals = ([str(i + 1)] + list(data) if data else [""] * 6)
        aligns = ["center", "left", "center", "right", "center", "left"]
        for c, v, al, w in zip(row.cells, vals, aligns, _WP_A_W):
            _set_cell(c, v, align=al, size=13)
            c.width = w
        _tick_cell(row.cells[6], False)
        _tick_cell(row.cells[7], False)
        _set_cell(row.cells[8], "", size=13)
        for c, w in zip(row.cells, _WP_A_W):
            c.width = w
    return t


# ==================================================== ชุด ข  ครุภัณฑ์ รับ
_WP_B_ITEMS = ["รายการ", "ประเภทครุภัณฑ์", "ลักษณะ", "รหัส", "ประเภทเงิน",
               "วิธีการจัดหา", "ค่าเสื่อมราคา", "สถานที่ตั้ง"]
_WP_B_W = [Cm(1.2), Cm(5.0), Cm(2.0), Cm(2.6), Cm(2.6)] + [Cm(1.55)] * 8


def render_wp_asset_flow(school, ctx, assets, doc=None):
    """ชุด ข - เทียบรายการในเอกสารฝ่ายรับ กับการบันทึกในทะเบียนคุมทรัพย์สิน

    ติ๊ก 8 หัวข้อว่าลงทะเบียนครบถ้วนถูกต้องหรือไม่ (รายการ/ประเภท/ลักษณะ/รหัส/
    ประเภทเงิน/วิธีการจัดหา/ค่าเสื่อมราคา/สถานที่ตั้ง)
    """
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _head(doc, school, "รายละเอียดการตรวจสอบการรับจ่ายพัสดุ",
          f"ชุดที่ 2  ครุภัณฑ์  ประจำปีงบประมาณ พ.ศ. {year}")
    _p(doc, "เทียบรายการในเอกสารฝ่ายรับ กับการบันทึกรายการในทะเบียนคุมทรัพย์สิน "
            f"({TICK} = ถูกต้อง · {BOX} = ยังไม่ได้ตรวจ/ไม่ถูกต้อง)",
       size=13, after=3)

    rows = [a for a in (assets or []) if (a.status or "") != "จำหน่ายแล้ว"]
    n = max(len(rows), 8)
    t = doc.add_table(rows=2 + n, cols=len(_WP_B_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _WP_B_W)
    _center_table(t)
    r0, r1 = t.rows[0], t.rows[1]
    for i, lab in enumerate(["ลำดับ\nที่", "รายการที่จัดซื้อจัดจ้าง", "จำนวน",
                             "ประเภทเงินที่ใช้จัดหา", "วิธีการได้มา"]):
        _set_cell(r0.cells[i].merge(r1.cells[i]), lab, bold=True, align="center", size=13)
    _set_cell(r0.cells[5].merge(r0.cells[12]),
              "การบันทึกรายการในทะเบียนคุมทรัพย์สิน", bold=True, align="center", size=13)
    for i, lab in enumerate(_WP_B_ITEMS, start=5):
        _set_cell(r1.cells[i], lab, bold=True, align="center", size=11)
    _repeat_header_row(r0)
    _repeat_header_row(r1)
    _no_split_row(r0)
    _no_split_row(r1)

    for i in range(n):
        row = t.rows[2 + i]
        _no_split_row(row)
        a = rows[i] if i < len(rows) else None
        if a:
            vals = [str(i + 1), (a.name or ""), f"{(a.quantity or 1):g} {a.unit or ''}",
                    (a.fund_type or ""), (a.acquire_method or "")]
            # ระบบลงทะเบียนให้แล้วช่องไหน ติ๊กช่องนั้นไว้ก่อน ผู้ตรวจสอบตรวจซ้ำได้
            have = [bool((a.name or "").strip()), bool((a.category or "").strip()),
                    bool((a.brand_model or "").strip()), bool((a.asset_code or "").strip()),
                    bool((a.fund_type or "").strip()), bool((a.acquire_method or "").strip()),
                    bool(a.useful_life), bool((a.location or "").strip())]
        else:
            vals = [""] * 5
            have = [False] * 8
        for c, v, al, w in zip(row.cells, vals, ["center", "left", "center", "left", "left"],
                               _WP_B_W):
            _set_cell(c, v, align=al, size=12)
            c.width = w
        for j, on in enumerate(have, start=5):
            _tick_cell(row.cells[j], on)
        for c, w in zip(row.cells, _WP_B_W):
            c.width = w
    _inspector_sign(doc, ctx)
    return _save(doc, f"กระดาษทำการ ชุด2 รับครุภัณฑ์_ปีงบ{year}") if own else doc


# ==================================================== ชุด ค  วัสดุคงเหลือ
_WP_C_W = [Cm(1.2), Cm(3.4), Cm(5.0), Cm(1.8), Cm(2.2), Cm(2.4), Cm(2.2),
           Cm(1.7), Cm(1.7), Cm(3.1)]


def render_wp_material_count(school, ctx, materials, doc=None):
    """ชุด ค - วัสดุคงเหลือและสภาพการใช้งาน ณ 30 กันยายน

    ช่อง "จำนวนตามบัญชี" ระบบคำนวณให้จากบัญชีวัสดุ · ช่องตรวจนับเว้นไว้ให้นับจริง
    """
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _head(doc, school, f"รายละเอียดการตรวจสอบพัสดุ ณ วันที่ 30 กันยายน {year}",
          "ชุดที่ 1  วัสดุคงเหลือและสภาพการใช้งาน")

    rows = [m for m in (materials or []) if material_balance(m)]
    n = max(len(rows), 10)
    t = doc.add_table(rows=2 + n, cols=len(_WP_C_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _WP_C_W)
    _center_table(t)
    r0, r1 = t.rows[0], t.rows[1]
    _set_cell(r0.cells[0].merge(r1.cells[0]), "ลำดับ\nที่", bold=True, align="center", size=12)
    _set_cell(r0.cells[1].merge(r0.cells[2]), "รายละเอียดวัสดุคงเหลือตามบัญชีวัสดุ",
              bold=True, align="center", size=12)
    _set_cell(r1.cells[1], "ประเภทวัสดุ", bold=True, align="center", size=12)
    _set_cell(r1.cells[2], "รายการ", bold=True, align="center", size=12)
    for i, lab in [(3, "หน่วย\nนับ"), (4, "จำนวน\nตามบัญชี"), (5, "จำนวน\nที่ตรวจนับ"),
                   (6, "จำนวน\n- ขาด / + เกิน")]:
        _set_cell(r0.cells[i].merge(r1.cells[i]), lab, bold=True, align="center", size=12)
    _set_cell(r0.cells[7].merge(r0.cells[8]), "สภาพ", bold=True, align="center", size=12)
    _set_cell(r1.cells[7], "ใช้งาน\nได้", bold=True, align="center", size=11)
    _set_cell(r1.cells[8], "ใช้งาน\nไม่ได้", bold=True, align="center", size=11)
    _set_cell(r0.cells[9].merge(r1.cells[9]), "สาเหตุ", bold=True, align="center", size=12)
    _repeat_header_row(r0)
    _repeat_header_row(r1)
    _no_split_row(r0)
    _no_split_row(r1)

    for i in range(n):
        row = t.rows[2 + i]
        _no_split_row(row)
        m = rows[i] if i < len(rows) else None
        if m:
            vals = [str(i + 1), (m.category or "วัสดุทั่วไป"), (m.name or ""),
                    (m.unit or ""), f"{material_balance(m):g}", "", ""]
        else:
            vals = [""] * 7
        for c, v, al, w in zip(row.cells, vals,
                               ["center", "left", "left", "center", "right", "right", "right"],
                               _WP_C_W):
            _set_cell(c, v, align=al, size=12)
            c.width = w
        _tick_cell(row.cells[7], False)
        _tick_cell(row.cells[8], False)
        _set_cell(row.cells[9], "", size=12)
        for c, w in zip(row.cells, _WP_C_W):
            c.width = w
    _p(doc, "", after=2)
    _p(doc, "จำนวนตามบัญชี = ยอดคงเหลือที่ระบบคำนวณจากบัญชีวัสดุ · "
            "ช่องตรวจนับให้กรอกจากการนับจริง ณ วันสิ้นงวด", size=12, after=2)
    _inspector_sign(doc, ctx)
    return _save(doc, f"กระดาษทำการ ชุด3 วัสดุคงเหลือ_ปีงบ{year}") if own else doc


# ==================================================== ชุด ง  ครุภัณฑ์คงเหลือ
_WP_D_W = [Cm(1.2), Cm(3.2), Cm(6.2), Cm(1.6), Cm(1.6), Cm(2.0),
           Cm(1.7), Cm(1.6), Cm(1.9), Cm(1.8), Cm(2.9)]


def render_wp_asset_count(school, ctx, assets, doc=None):
    """ชุด ง - ครุภัณฑ์คงเหลือและสภาพการใช้งาน ณ 30 กันยายน (จัดกลุ่มตามประเภท)

    ระบบเติมรายการจากทะเบียนคุมทรัพย์สินและติ๊กช่องสภาพให้ตามสถานะที่บันทึกไว้
    คณะกรรมการเดินตรวจนับจริงแล้วแก้ช่องที่ไม่ตรงได้
    """
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _head(doc, school, f"รายละเอียดการตรวจสอบพัสดุ ณ วันที่ 30 กันยายน {year}",
          "ชุดที่ 2  ครุภัณฑ์คงเหลือและสภาพการใช้งาน")

    live = [a for a in (assets or []) if (a.status or "") != "จำหน่ายแล้ว"]
    groups = {}
    for a in live:
        groups.setdefault((a.category or "ไม่ระบุประเภท").strip(), []).append(a)
    body_rows = sum(len(v) + 1 for v in groups.values()) or 10

    t = doc.add_table(rows=2 + body_rows, cols=len(_WP_D_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _WP_D_W)
    _center_table(t)
    r0, r1 = t.rows[0], t.rows[1]
    _set_cell(r0.cells[0].merge(r1.cells[0]), "ลำดับ\nที่", bold=True, align="center", size=12)
    _set_cell(r0.cells[1].merge(r0.cells[2]),
              "รายละเอียดครุภัณฑ์คงเหลือตามทะเบียนคุมทรัพย์สิน",
              bold=True, align="center", size=12)
    _set_cell(r1.cells[1], "หมายเลข\nทะเบียนครุภัณฑ์", bold=True, align="center", size=11)
    _set_cell(r1.cells[2], "ประเภท / รายการ / รายละเอียด", bold=True, align="center", size=11)
    _set_cell(r0.cells[3].merge(r1.cells[3]), "หน่วย\nนับ", bold=True, align="center", size=12)
    _set_cell(r0.cells[4].merge(r0.cells[5]), "ความมีอยู่จริง",
              bold=True, align="center", size=12)
    _set_cell(r1.cells[4], "มี", bold=True, align="center", size=11)
    _set_cell(r1.cells[5], "ไม่มี /\nสูญหาย", bold=True, align="center", size=11)
    _set_cell(r0.cells[6].merge(r0.cells[9]), "สภาพของครุภัณฑ์",
              bold=True, align="center", size=12)
    for i, lab in enumerate(["ใช้การได้", "ชำรุด", "เสื่อมสภาพ", "ไม่ใช้งาน"], start=6):
        _set_cell(r1.cells[i], lab, bold=True, align="center", size=11)
    _set_cell(r0.cells[10].merge(r1.cells[10]), "หมายเหตุ", bold=True, align="center", size=12)
    _repeat_header_row(r0)
    _repeat_header_row(r1)
    _no_split_row(r0)
    _no_split_row(r1)

    ri, seq = 2, 0
    for cat in sorted(groups):
        row = t.rows[ri]
        _no_split_row(row)
        _set_cell(row.cells[0].merge(row.cells[10]), f"ประเภท{cat}",
                  bold=True, align="left", size=12)
        ri += 1
        for a in sorted(groups[cat], key=lambda x: ((x.asset_code or "~"), x.id)):
            seq += 1
            row = t.rows[ri]
            _no_split_row(row)
            ri += 1
            desc = " ".join(x for x in [(a.name or "").strip(),
                                        (a.brand_model or "").strip()] if x)
            st = (a.status or "ใช้งาน").strip()
            for c, v, al, w in zip(row.cells,
                                   [str(seq), (a.asset_code or ""), desc,
                                    (a.unit or "")],
                                   ["center", "left", "left", "center"], _WP_D_W):
                _set_cell(c, v, align=al, size=12)
                c.width = w
            _tick_cell(row.cells[4], st != "สูญไป")
            _tick_cell(row.cells[5], st == "สูญไป")
            col = _COND_COL.get(st)
            for j, lab in enumerate(["ใช้การได้", "ชำรุด", "เสื่อมสภาพ", "ไม่ใช้งาน"], start=6):
                _tick_cell(row.cells[j], col == lab)
            _set_cell(row.cells[10], "", size=12)
            for c, w in zip(row.cells, _WP_D_W):
                c.width = w
    while ri < len(t.rows):                 # แถวว่างไว้เขียนมือเพิ่ม
        row = t.rows[ri]
        _no_split_row(row)
        for c, w in zip(row.cells, _WP_D_W):
            _set_cell(c, "", size=12)
            c.width = w
        ri += 1
    _p(doc, "", after=2)
    _p(doc, f"{TICK} = ระบบติ๊กให้ตามสถานะในทะเบียนคุมทรัพย์สิน "
            "คณะกรรมการตรวจนับจริงแล้วแก้ช่องที่ไม่ตรงได้", size=12, after=2)
    _inspector_sign(doc, ctx)
    return _save(doc, f"กระดาษทำการ ชุด4 ครุภัณฑ์คงเหลือ_ปีงบ{year}") if own else doc


# ==================================== บัญชีพัสดุที่ต้องจำหน่าย แยกตามสภาพ
_LG_W = [Cm(1.2), Cm(4.4), Cm(2.8), Cm(2.2), Cm(2.6), Cm(1.5), Cm(1.5),
         Cm(2.3), Cm(2.3), Cm(2.4), Cm(3.5)]


def render_condition_ledger(school, ctx, assets, kind, doc=None):
    """บัญชีรายการครุภัณฑ์แยกตามสภาพ (ชำรุด / เสื่อมสภาพ / สูญไป / ไม่จำเป็นต้องใช้)"""
    spec = next((x for x in LEDGERS if x[0] == kind), None)
    if spec is None:
        raise ValueError("ไม่รู้จักบัญชีนี้")
    _key, title, statuses, reason_head = spec
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _head(doc, school, title, f"ประจำปีงบประมาณ พ.ศ. {year}")

    rows = [a for a in (assets or []) if (a.status or "") in statuses]
    n = max(len(rows), 8)
    t = doc.add_table(rows=2 + n, cols=len(_LG_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _LG_W)
    _center_table(t)
    r0, r1 = t.rows[0], t.rows[1]
    for i, lab in [(0, "ลำดับ\nที่"), (1, "รายการ"), (2, "หมายเลข\nครุภัณฑ์")]:
        _set_cell(r0.cells[i].merge(r1.cells[i]), lab, bold=True, align="center", size=12)
    _set_cell(r0.cells[3].merge(r0.cells[8]), "รายละเอียดการได้มาของครุภัณฑ์",
              bold=True, align="center", size=12)
    for i, lab in enumerate(["ว.ด.ป", "วิธีการได้มา", "จำนวน", "หน่วย",
                             "ราคาต่อหน่วย", "มูลค่า"], start=3):
        _set_cell(r1.cells[i], lab, bold=True, align="center", size=11)
    _set_cell(r0.cells[9].merge(r1.cells[9]), "ประเภท\nงบประมาณ",
              bold=True, align="center", size=12)
    _set_cell(r0.cells[10].merge(r1.cells[10]), reason_head,
              bold=True, align="center", size=12)
    _repeat_header_row(r0)
    _repeat_header_row(r1)
    _no_split_row(r0)
    _no_split_row(r1)

    total = 0.0
    for i in range(n):
        row = t.rows[2 + i]
        _no_split_row(row)
        a = rows[i] if i < len(rows) else None
        if a:
            qty = float(a.quantity or 1)
            unit_cost = float(a.cost or 0)
            value = unit_cost * qty          # แบบฟอร์มกำหนด มูลค่า = ราคาต่อหน่วย x จำนวน
            total += value
            vals = [str(i + 1), (a.name or ""), (a.asset_code or ""),
                    thai_date(a.acquired_date) if a.acquired_date else "",
                    (a.acquire_method or ""), f"{qty:g}", (a.unit or ""),
                    f"{unit_cost:,.2f}", f"{value:,.2f}", (a.fund_type or ""),
                    (a.note or "")]
        else:
            vals = [""] * 11
        aligns = ["center", "left", "left", "center", "left", "center", "center",
                  "right", "right", "left", "left"]
        for c, v, al, w in zip(row.cells, vals, aligns, _LG_W):
            _set_cell(c, v, align=al, size=12)
            c.width = w
        for c, w in zip(row.cells, _LG_W):
            c.width = w
    _p(doc, f"รวม {len(rows)} รายการ มูลค่ารวม {total:,.2f} บาท",
       bold=True, size=14, before=3, after=2)
    _inspector_sign(doc, ctx)
    return _save(doc, f"{_safe(title)}_ปีงบ{year}") if own else doc


# ============================ บัญชีพัสดุที่เหลือไม่ตรงตามบัญชี/ทะเบียน
_MM_W = [Cm(1.8), Cm(5.6), Cm(4.4), Cm(3.6), Cm(6.4)]


def render_mismatch_list(school, ctx, assets, materials=None, doc=None):
    """บัญชีรายการพัสดุที่ตรวจสอบว่าเหลือไม่ตรงตามบัญชีหรือทะเบียน

    แนบท้ายรายงานผลการตรวจสอบเมื่อตรวจนับแล้วไม่ตรง
    ระบบเติมครุภัณฑ์ที่สถานะ "สูญไป" ให้ก่อน (ตามทะเบียนมี 1 ตรวจนับได้ 0)
    ส่วนวัสดุที่นับแล้วขาด/เกิน ต้องกรอกเองเพราะระบบไม่มีผลการนับจริง
    """
    own = doc is None
    if own:
        doc = _new(landscape=True)
    else:
        _land(doc)
    year = ctx.get("year")
    _p(doc, "บัญชีรายการพัสดุที่ตรวจสอบว่าเหลือไม่ตรงตามบัญชีหรือทะเบียน",
       align="center", bold=True, size=17, after=0)
    _p(doc, f"ของ {(school.name or '').strip() or _BLANK}", align="center", size=16, after=0)
    _p(doc, f"ประจำปีงบประมาณ พ.ศ. {year}  (ตรวจนับ ณ วันที่ 30 กันยายน {year})",
       align="center", size=15, after=6)

    lost = [a for a in (assets or []) if (a.status or "") == "สูญไป"]
    n = max(len(lost) + 4, 8)
    t = doc.add_table(rows=1 + n, cols=len(_MM_W))
    t.style = "Table Grid"
    t.autofit = False
    _fixed_cols(t, _MM_W)
    _center_table(t)
    heads = ["เลขที่", "รายการ", "จำนวนพัสดุคงเหลือ\nตามบัญชีหรือทะเบียน",
             "จำนวนพัสดุ\nที่ตรวจสอบ",
             "เหตุที่พัสดุคงเหลือไม่ตรงตามบัญชีหรือทะเบียน"]
    hdr = t.rows[0]
    _repeat_header_row(hdr)
    _no_split_row(hdr)
    for c, h, w in zip(hdr.cells, heads, _MM_W):
        _set_cell(c, h, bold=True, align="center", size=13)
        c.width = w
    for i in range(n):
        row = t.rows[1 + i]
        _no_split_row(row)
        a = lost[i] if i < len(lost) else None
        if a:
            name = " ".join(x for x in [(a.name or "").strip(),
                                        f"({a.asset_code})" if a.asset_code else ""] if x)
            vals = [str(i + 1), name, f"{(a.quantity or 1):g} {a.unit or ''}",
                    f"0 {a.unit or ''}", "สูญไป (รายละเอียดตามรายงานการสอบหาข้อเท็จจริง)"]
        else:
            vals = [""] * 5
        for c, v, al, w in zip(row.cells, vals,
                               ["center", "left", "center", "center", "left"], _MM_W):
            _set_cell(c, v, align=al, size=13)
            c.width = w
        for c, w in zip(row.cells, _MM_W):
            c.width = w
    if not lost:
        _p(doc, "หมายเหตุ  ระบบไม่พบครุภัณฑ์ที่สถานะสูญไป — ถ้าตรวจนับแล้วมีรายการ"
                "ที่ไม่ตรงบัญชี ให้กรอกเพิ่มในตารางข้างต้น", size=12, before=3, after=2)
    _p(doc, "", after=6)

    # ลงนามตามแบบฟอร์ม: หัวหน้าเจ้าหน้าที่ผู้ตรวจสอบ แล้วตามด้วยเจ้าหน้าที่ผู้ตรวจสอบ
    mem = _members(ctx)
    solo = bool(ctx.get("single")) or len(mem) <= 1
    first = (mem or [{}])[0]
    # รวมลายเซ็นทั้งหมดไว้ในตารางเดียว (cantSplit) ไม่งั้นช่องล่างหลุดไปอยู่หน้าใหม่ลำพัง
    rest = [] if solo else (mem[1:3] or [{}, {}])
    st = doc.add_table(rows=2 if rest else 1, cols=max(len(rest), 1))
    _no_borders(st)
    _center_table(st)
    _fixed_cols(st, [Cm(25.5 / max(len(rest), 1))] * max(len(rest), 1))
    top = st.rows[0]
    _no_split_row(top)
    head_cell = top.cells[0]
    if len(rest) > 1:
        head_cell = head_cell.merge(top.cells[len(rest) - 1])
    _set_cell(head_cell,
              "ลงชื่อ ......................................\n"
              f"( {(first.get('name') or '').strip() or _BLANK} )\n"
              + ("ผู้ตรวจสอบพัสดุ" if solo else "หัวหน้าเจ้าหน้าที่ผู้ตรวจสอบ"),
              align="center", size=16)
    # cantSplit กันแถวขาดกลางแถวเท่านั้น ต้องใส่ keepNext ด้วย ไม่งั้นแถวล่าง
    # (ช่องเจ้าหน้าที่ผู้ตรวจสอบ) หลุดไปอยู่หน้าใหม่ลำพัง
    for cell in top.cells:
        for par in cell.paragraphs:
            par.paragraph_format.keep_with_next = True
    if rest:
        row = st.rows[1]
        _no_split_row(row)
        for c, m in zip(row.cells, rest):
            _set_cell(c,
                      "\nลงชื่อ ......................................\n"
                      f"( {(m.get('name') or '').strip() or _BLANK} )\n"
                      "เจ้าหน้าที่ผู้ตรวจสอบ", align="center", size=16)
    return _save(doc, f"บัญชีพัสดุเหลือไม่ตรงตามบัญชี_ปีงบ{year}") if own else doc


# ==================================================== หนังสือแจ้งผลการตรวจสอบ
def _letter_head(doc, school, doc_no, date_txt, subject, to, encl):
    _krut_center(doc, height_cm=2.0)
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    t.autofit = False
    widths = [Cm(8.0), Cm(8.5)]
    _fixed_cols(t, widths)
    _set_cell(t.rows[0].cells[0], "ที่  " + (doc_no or _BLANK), align="left", size=16)
    addr = (getattr(school, "address", "") or "").strip()
    _set_cell(t.rows[0].cells[1],
              (school.name or "โรงเรียน").strip() + (("\n" + addr) if addr else ""),
              align="right", size=16)
    for c, w in zip(t.rows[0].cells, widths):
        c.width = w
    _p(doc, date_txt, align="center", before=4, after=6)
    _p_runs(doc, [("เรื่อง  ", True), (subject, False)])
    _p_runs(doc, [("เรียน  ", True), (to, False)])
    if encl:
        _p_runs(doc, [("สิ่งที่ส่งมาด้วย  ", True), (encl, False)])
    _p(doc, "", after=4)


_AUDIT_ENCL = ["สำเนาคำสั่งแต่งตั้งคณะกรรมการตรวจสอบพัสดุประจำปี",
               "สำเนาคำสั่งแต่งตั้งเจ้าหน้าที่พัสดุ / หัวหน้าเจ้าหน้าที่พัสดุ",
               "สำเนารายงานผลการตรวจสอบพัสดุประจำปีของคณะกรรมการฯ"]


def render_audit_letter(school, ctx, to_kind, doc=None):
    """หนังสือแจ้งผลการตรวจสอบพัสดุประจำปี

    to_kind = 'area' แจ้งสำนักงานเขตพื้นที่การศึกษา · 'sao' แจ้ง สตง.
    ระเบียบฯ ข้อ 213 ให้รายงานผลต่อผู้แต่งตั้ง แล้วส่งสำเนาให้ทั้งสองทาง
    """
    own = doc is None
    doc = doc or _new()
    if not own:
        _blank_doc_or_break(doc)
    year = ctx.get("year")
    clean = ctx.get("all_clean", True)
    sao = _sao_name(ctx)
    area = (school.area_office or "").strip() or "สำนักงานเขตพื้นที่การศึกษา"
    if to_kind == "sao":
        to, no, date = "ผู้อำนวยการ" + sao, ctx.get("sao_no"), ctx.get("sao_date")
        encl = f"สำเนาเอกสารหลักฐานการดำเนินการตรวจสอบพัสดุประจำปี จำนวน 1 ชุด"
    else:
        to, no, date = "ผู้อำนวยการ" + area, ctx.get("area_no"), ctx.get("area_date")
        encl = ("1. สำเนาเอกสารหลักฐานการดำเนินการตรวจสอบพัสดุประจำปี จำนวน 1 ชุด\n"
                f"2. สำเนาหนังสือแจ้ง{sao} จำนวน 1 ฉบับ")
    _letter_head(doc, school, no, _thai_be(date),
                 f"การตรวจสอบพัสดุประจำปี ปีงบประมาณ พ.ศ. {year}", to, encl)
    sname = (school.name or "โรงเรียน").strip()
    found = ("ผลการตรวจสอบพบว่ารายการรับจ่ายตามบัญชีและทะเบียน รวมถึงจำนวนพัสดุคงเหลือ"
             "ถูกต้อง ไม่มีพัสดุชำรุด เสื่อมสภาพ สูญไป หรือไม่จำเป็นต้องใช้ในหน่วยงานของรัฐ"
             if clean else
             "ผลการตรวจสอบพบว่ามีพัสดุชำรุด เสื่อมสภาพ สูญไป หรือไม่จำเป็นต้องใช้"
             f"ในหน่วยงานของรัฐ จำนวน {ctx.get('damaged_count') or _BLANK} รายการ "
             "ซึ่งอยู่ระหว่างดำเนินการจำหน่ายตามระเบียบฯ หมวด 9 ส่วนที่ 4")
    _p(doc, f"ด้วย{sname} ได้ดำเนินการตรวจสอบพัสดุประจำปี ปีงบประมาณ พ.ศ. {year} "
            "ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 มาตรา 112 "
            "และระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
            f"พ.ศ. 2560 ข้อ 213 เสร็จเรียบร้อยแล้ว โดย{found}"
            + (f" ซึ่งได้จัดส่งสำเนารายงานพร้อมเอกสารที่เกี่ยวข้องให้{sao} "
               "เพื่อทราบตามระเบียบดังกล่าวแล้ว" if to_kind == "area" else "")
            + " รายละเอียดตามสิ่งที่ส่งมาด้วยพร้อมนี้",
       align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดทราบ", align="justify", indent=1.25, after=8)
    _p(doc, "ขอแสดงความนับถือ", align="center", after=12)
    _sign_table(doc, [[
        ("", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
        (_director_line(school), "center"),
    ]])
    _p(doc, "งานการเงินและพัสดุ", size=14, before=8, after=0)
    _p(doc, f"โทร. {(ctx.get('phone') or '').strip() or _BLANK}", size=14, after=6)
    if to_kind == "sao":
        _p(doc, "หมายเหตุ  สำเนาเอกสารการตรวจสอบพัสดุประจำปี ประกอบด้วย",
           bold=True, size=14, after=1)
        for i, txt in enumerate(_AUDIT_ENCL, 1):
            _p(doc, f"{i}. {txt}", size=14, indent=1.25, after=1)
    label = "เขตพื้นที่การศึกษา" if to_kind == "area" else "สตง."
    return _save(doc, f"หนังสือแจ้ง{label} ตรวจสอบพัสดุ_ปีงบ{year}") if own else doc


def _sao_name(ctx) -> str:
    kind = (ctx.get("sao_kind") or "จังหวัด").strip()
    region = (ctx.get("sao_region") or "").strip() or ".........."
    if kind.startswith("ภูมิภาค"):
        return f"สำนักงานตรวจเงินแผ่นดินภูมิภาคที่ {region}"
    return f"สำนักงานตรวจเงินแผ่นดินจังหวัด{region}"


# ==================================================== ชุดรวม
PAPERS = {
    "wp_mat_flow": ("กระดาษทำการ ชุด 1 - รับจ่ายวัสดุ", render_wp_material_flow, "mat"),
    "wp_asset_flow": ("กระดาษทำการ ชุด 2 - รับครุภัณฑ์", render_wp_asset_flow, "asset"),
    "wp_mat_count": ("กระดาษทำการ ชุด 3 - วัสดุคงเหลือ", render_wp_material_count, "mat"),
    "wp_asset_count": ("กระดาษทำการ ชุด 4 - ครุภัณฑ์คงเหลือ", render_wp_asset_count, "asset"),
    "mismatch": ("บัญชีพัสดุที่เหลือไม่ตรงตามบัญชี/ทะเบียน", render_mismatch_list, "asset"),
}


def render_papers_bundle(school, ctx, assets, materials) -> str:
    """กระดาษทำการทั้ง 4 ชุดในไฟล์เดียว"""
    doc = _new(landscape=True)
    render_wp_material_flow(school, ctx, materials, doc)
    render_wp_asset_flow(school, ctx, assets, doc)
    render_wp_material_count(school, ctx, materials, doc)
    render_wp_asset_count(school, ctx, assets, doc)
    render_mismatch_list(school, ctx, assets, materials, doc)
    return _save(doc, f"กระดาษทำการตรวจสอบพัสดุ_ปีงบ{ctx.get('year')}")


def render_ledgers_bundle(school, ctx, assets) -> str:
    """บัญชีพัสดุที่ต้องจำหน่าย แยก 4 ฉบับตามสภาพ (ออกเฉพาะฉบับที่มีรายการ)"""
    from app.services.asset_utils import ASSET_BAD_STATUSES
    have = [k for k, _t, sts, _r in LEDGERS
            if any((a.status or "") in sts for a in (assets or []))]
    if not have:
        raise ValueError("ไม่มีครุภัณฑ์ที่ชำรุด เสื่อมสภาพ สูญไป หรือไม่จำเป็นต้องใช้")
    doc = _new(landscape=True)
    for k in have:
        render_condition_ledger(school, ctx, assets, k, doc)
    return _save(doc, f"บัญชีพัสดุที่ต้องจำหน่าย แยกตามสภาพ_ปีงบ{ctx.get('year')}")
