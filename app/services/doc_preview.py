# -*- coding: utf-8 -*-
"""ดูตัวอย่างเอกสาร Word บนหน้าเว็บ (ไม่ต้องดาวน์โหลด)

ขั้นตอน: .docx -> PDF (LibreOffice บนเซิร์ฟเวอร์ / Word บนเครื่องพัฒนา Windows) -> ภาพ PNG ทีละหน้า (PyMuPDF)
ภาพเป็น <img> ธรรมดา จึงดูได้ทุกเครื่อง รวม iPhone ที่ไม่แสดง PDF ในกรอบ

กันเซิร์ฟเวอร์ช้า
  - แปลงเฉพาะตอนมีคนกดดู และแปลงได้ครั้งละ 1 ไฟล์ (_LOCK) รอคิวเกิน _WAIT วินาที = บอกให้ลองใหม่
  - เก็บผลไว้ใช้ซ้ำ คีย์ = แฮชเนื้อไฟล์ (ไม่นับ docProps ที่มีเวลาสร้าง) เอกสารไม่ถูกแก้ = ไม่แปลงซ้ำ
  - ตัดเวลาแปลง _TIMEOUT วินาที ภาพเกิน _MAX_PAGES หน้าไม่ทำต่อ ไฟล์เก่าเกิน 1 วันลบเอง
ไม่มีตัวแปลงในเครื่อง available() = False หน้าเว็บซ่อนปุ่มดูตัวอย่าง (ยังดาวน์โหลดได้ตามเดิม)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

_LOCK = threading.Lock()
_WAIT = 25
_TIMEOUT = 60
_MAX_PAGES = 30
_DPI = 130
_KEEP_SEC = 24 * 3600
_KEY_RX = re.compile(r"^[0-9a-f]{40}$")


class PreviewBusy(Exception):
    """มีคนกำลังแปลงอยู่นานเกิน รอคิวไม่ไหว"""


class PreviewFailed(Exception):
    pass


# ---------------------------------------------------------------- ตัวแปลง
def _soffice():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.exists(p):
            return p
    return None


def _has_word() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application"))
        return True
    except Exception:
        return False


_AVAIL = None


def available() -> bool:
    """มีตัวแปลง + PyMuPDF ไหม (DDOC_PREVIEW=0 ปิดได้)"""
    global _AVAIL
    if os.environ.get("DDOC_PREVIEW", "1") == "0":
        return False
    if _AVAIL is None:
        try:
            import pymupdf  # noqa: F401
            ok = True
        except Exception:
            try:
                import fitz  # noqa: F401
                ok = True
            except Exception:
                ok = False
        _AVAIL = bool(ok and (_soffice() or _has_word()))
    return _AVAIL


def _to_pdf(docx: Path, out_dir: Path) -> Path:
    soffice = _soffice()
    if soffice:
        prof = Path(tempfile.mkdtemp(prefix="lo_prof_"))
        try:
            subprocess.run([soffice, f"-env:UserInstallation={prof.as_uri()}", "--headless", "--norestore",
                            "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=_TIMEOUT, check=False)
        finally:
            shutil.rmtree(prof, ignore_errors=True)
    elif _has_word():                       # เครื่องพัฒนา Windows ที่ไม่มี LibreOffice
        pdf = out_dir / (docx.stem + ".pdf")
        ps = ("$w=New-Object -ComObject Word.Application;$w.Visible=$false;"
              "try{$d=$w.Documents.Open($env:DP_IN,$false,$true);$d.SaveAs2($env:DP_OUT,17);$d.Close($false)}"
              "finally{$w.Quit()}")
        env = dict(os.environ, DP_IN=str(docx), DP_OUT=str(pdf))
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=_TIMEOUT, check=False)
    pdf = out_dir / (docx.stem + ".pdf")
    if not pdf.exists():
        raise PreviewFailed("แปลงเอกสารไม่สำเร็จ")
    return pdf


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _fix_tables(docx: Path):
    """ความกว้างคอลัมน์: Word ใช้ tcW ของเซลล์ LibreOffice ใช้ gridCol ของตาราง
    แม่แบบหลายไฟล์ gridCol เท่ากันหมด (เช่น ตารางรายชื่อกรรมการ) LibreOffice เลยบีบช่องชื่อจนตัดบรรทัด
    แก้เฉพาะสำเนาที่ใช้ทำตัวอย่าง ให้ gridCol = tcW ของแถวแรก (ไฟล์ Word ที่ดาวน์โหลดไม่เปลี่ยน)"""
    from lxml import etree
    with zipfile.ZipFile(docx) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    changed = False
    out = []
    for info, data in items:
        if info.filename == "word/document.xml":
            root = etree.fromstring(data)
            for tbl in root.iter(_W + "tbl"):
                grid = tbl.find(_W + "tblGrid")
                tr = tbl.find(_W + "tr")
                if grid is None or tr is None:
                    continue
                cols = grid.findall(_W + "gridCol")
                widths = []
                for tc in tr.findall(_W + "tc"):
                    pr = tc.find(_W + "tcPr")
                    w = pr.find(_W + "tcW") if pr is not None else None
                    span = pr.find(_W + "gridSpan") if pr is not None else None
                    n = int(span.get(_W + "val", "1")) if span is not None else 1
                    if w is None or w.get(_W + "type") != "dxa":
                        widths = None
                        break
                    each = int(int(w.get(_W + "w", "0")) / n)
                    widths += [each] * n
                if not widths or len(widths) != len(cols) or not all(widths):
                    continue
                for c, w in zip(cols, widths):
                    if c.get(_W + "w") != str(w):
                        c.set(_W + "w", str(w))
                        changed = True
            data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        out.append((info, data))
    if changed:
        with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as z:
            for info, data in out:
                z.writestr(info, data)


# ---------------------------------------------------------------- แคช
def _root(tid) -> Path:
    from app.database import get_data_dir
    p = get_data_dir() / "preview" / str(int(tid or 0))
    p.mkdir(parents=True, exist_ok=True)
    return p


_FIX_VER = b"grid1"      # เปลี่ยนเมื่อแก้ _fix_tables ภาพเก่าในแคชจะไม่ถูกใช้


def content_key(docx_path) -> str:
    """แฮชเนื้อเอกสาร ไม่นับ docProps (เวลาสร้างไฟล์เปลี่ยนทุกครั้ง)"""
    h = hashlib.sha1(_FIX_VER)
    with zipfile.ZipFile(docx_path) as z:
        for n in sorted(z.namelist()):
            if n.startswith("docProps/"):
                continue
            h.update(n.encode())
            h.update(z.read(n))
    return h.hexdigest()


def _cleanup(root: Path):
    now = time.time()
    for d in root.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > _KEEP_SEC:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _meta(d: Path):
    try:
        return json.loads((d / "meta.json").read_text("utf-8"))
    except Exception:
        return None


def build(docx_path, tid) -> dict:
    """คืน {key, pages, total, cut} สร้างภาพถ้ายังไม่มีในแคช"""
    docx_path = Path(docx_path)
    key = content_key(docx_path)
    root = _root(tid)
    d = root / key
    m = _meta(d)
    if m:
        os.utime(d, None)
        return m
    if not _LOCK.acquire(timeout=_WAIT):
        raise PreviewBusy("มีคนกำลังเปิดดูตัวอย่างหลายเรื่อง ลองใหม่อีกครั้งในไม่กี่วินาที")
    try:
        m = _meta(d)                        # คนก่อนหน้าในคิวอาจทำไฟล์เดียวกันไว้แล้ว
        if m:
            return m
        try:
            import pymupdf
        except Exception:
            import fitz as pymupdf
        tmp = Path(tempfile.mkdtemp(prefix="dp_"))
        try:
            src = tmp / "doc.docx"
            shutil.copyfile(docx_path, src)
            try:
                _fix_tables(src)
            except Exception:
                pass
            pdf = _to_pdf(src, tmp)
            work = root / (key + ".part")
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir()
            with pymupdf.open(str(pdf)) as doc:
                total = doc.page_count
                n = min(total, _MAX_PAGES)
                for i in range(n):
                    doc[i].get_pixmap(dpi=_DPI).save(str(work / f"{i + 1}.png"))
            m = {"key": key, "pages": n, "total": total, "cut": total > n}
            (work / "meta.json").write_text(json.dumps(m), "utf-8")
            shutil.rmtree(d, ignore_errors=True)
            work.rename(d)
        except subprocess.TimeoutExpired:
            raise PreviewFailed("เอกสารนี้ใหญ่เกินไป แปลงไม่ทัน ดาวน์โหลดไปเปิดแทน")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _cleanup(root)
        return m
    finally:
        _LOCK.release()


def page_file(tid, key: str, n: int):
    if not _KEY_RX.match(key or "") or n < 1 or n > _MAX_PAGES:
        return None
    p = _root(tid) / key / f"{n}.png"
    return p if p.exists() else None
