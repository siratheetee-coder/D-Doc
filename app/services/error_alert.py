# -*- coding: utf-8 -*-
"""แจ้งเจ้าของระบบทางอีเมลทันทีเมื่อมี error 500 (บัคที่ผู้ใช้เจอ) ไม่ต้องรอให้ผู้ใช้ทักมา

- ส่งไปที่อีเมลรับแจ้งเตือนของผู้ขาย (notifications.notification_email)
- error แบบเดียวกัน (ชนิด + หน้า + บรรทัดในโค้ด) ส่งไม่เกิน 1 ครั้ง/ชั่วโมง และรวมไม่เกิน 20 ฉบับ/ชั่วโมง
  ครั้งถัดไปบอกด้วยว่าระหว่างนั้นเกิดซ้ำอีกกี่ครั้ง
- ไม่แนบข้อมูลที่ผู้ใช้กรอก (PDPA) มีแค่ หน้า · โรงเรียน · ชนิด error · traceback
- ส่งในเธรดแยก หน้าเว็บที่ error ไม่ต้องรอ SMTP · บันทึกลง data/error-log.jsonl ด้วย (ดูย้อนหลังได้)
"""
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime

PER_SIGNATURE_SEC = 3600
MAX_PER_HOUR = 20
LOG_KEEP = 500

_lock = threading.Lock()
_last_sent: dict = {}        # signature -> เวลาส่งล่าสุด
_suppressed: dict = {}       # signature -> จำนวนครั้งที่เกิดซ้ำแต่ยังไม่ได้แจ้ง
_sent_times: list = []       # เวลาส่งทุกฉบับในชั่วโมงล่าสุด


def enabled() -> bool:
    return os.environ.get("DDOC_ERROR_ALERT", "1") != "0"


def signature(path: str, exc: BaseException) -> str:
    """error เดียวกัน = ชนิดเดียวกัน หน้าเดียวกัน (ไม่สนเลข id) บรรทัดสุดท้ายในโค้ดของเราเดียวกัน"""
    where = ""
    for fr in traceback.extract_tb(exc.__traceback__):
        if "app" + os.sep in fr.filename or "/app/" in fr.filename:
            where = f"{os.path.basename(fr.filename)}:{fr.lineno}"
    page = re.sub(r"/\d+", "/N", path)
    return f"{type(exc).__name__}|{page}|{where}"


def should_send(sig: str, now: float | None = None) -> tuple[bool, int]:
    """(ส่งไหม, จำนวนครั้งที่เกิดซ้ำก่อนหน้านี้ที่ยังไม่ได้แจ้ง)"""
    now = time.time() if now is None else now
    with _lock:
        _sent_times[:] = [t for t in _sent_times if now - t < 3600]
        last = _last_sent.get(sig)
        if (last is not None and now - last < PER_SIGNATURE_SEC) or len(_sent_times) >= MAX_PER_HOUR:
            _suppressed[sig] = _suppressed.get(sig, 0) + 1
            return False, 0
        _last_sent[sig] = now
        _sent_times.append(now)
        return True, _suppressed.pop(sig, 0)


def _school_name(tid) -> str:
    if not tid:
        return "-"
    try:
        from app.accounts import acc_session, Tenant
        db = acc_session()
        try:
            t = db.get(Tenant, tid)
            return f"{t.name} (id {tid}{', ระบบตัวอย่าง' if t and t.plan == 'sandbox' else ''})" if t else f"id {tid}"
        finally:
            db.close()
    except Exception:
        return f"id {tid}"


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _write_log(entry: dict) -> None:
    try:
        from app.database import get_data_dir
        p = get_data_dir() / "error-log.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        lines = (lines + [json.dumps(entry, ensure_ascii=False)])[-LOG_KEEP:]
        tmp = p.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(p)
    except Exception as e:  # noqa: BLE001  บันทึกไม่ได้ต้องไม่ทำให้หน้า error พังซ้ำ
        print("[error-alert] เขียน error-log ไม่ได้:", e)


def build_email(entry: dict, repeats: int) -> tuple[str, str]:
    subject = f"[Easy Ekkasan] error 500 ที่ {entry['path']} ({entry['type']})"
    rep = f"<p>ระหว่างชั่วโมงที่ผ่านมา error นี้เกิดซ้ำอีก <b>{repeats}</b> ครั้ง (ไม่ได้ส่งแยก)</p>" if repeats else ""
    html = f"""<div style="font-family:sans-serif;font-size:15px;line-height:1.6">
<h3 style="margin:0 0 8px">ระบบขึ้น error ที่ผู้ใช้เจอ</h3>
<table style="border-collapse:collapse">
<tr><td style="padding:2px 12px 2px 0;color:#666">เวลา</td><td>{_esc(entry['time'])}</td></tr>
<tr><td style="padding:2px 12px 2px 0;color:#666">หน้า</td><td>{_esc(entry['method'])} {_esc(entry['path'])}</td></tr>
<tr><td style="padding:2px 12px 2px 0;color:#666">โรงเรียน</td><td>{_esc(entry['school'])}</td></tr>
<tr><td style="padding:2px 12px 2px 0;color:#666">ผู้ใช้</td><td>{_esc(entry['user'])}</td></tr>
<tr><td style="padding:2px 12px 2px 0;color:#666">error</td><td>{_esc(entry['type'])}: {_esc(entry['message'])}</td></tr>
</table>{rep}
<pre style="background:#f6f8fa;padding:10px;border-radius:8px;font-size:12.5px;white-space:pre-wrap">{_esc(entry['trace'])}</pre>
<p style="color:#666;font-size:13px">error แบบเดียวกันจะแจ้งไม่เกินชั่วโมงละ 1 ครั้ง · ดูย้อนหลังได้ที่ data/error-log.jsonl บนเซิร์ฟเวอร์</p>
</div>"""
    return subject, html


def report(request, exc: BaseException) -> None:
    """เรียกจากตัวจัดการ error 500 · ห้ามโยน error ออกไปเด็ดขาด"""
    try:
        if not enabled():
            return
        from app.tenancy import current_school_id
        path = request.url.path
        sig = signature(path, exc)
        tid = current_school_id.get()
        sess = getattr(request, "session", None) or {}
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "method": request.method, "path": path,
            "query_keys": sorted(request.query_params.keys()),       # ไม่เก็บค่า กันข้อมูลส่วนตัวหลุด
            "school": _school_name(tid), "user": f"uid {sess.get('uid')}" if sess.get("uid") else "ยังไม่ล็อกอิน",
            "type": type(exc).__name__, "message": str(exc)[:300], "sig": sig,
            "trace": "\n".join(tb.strip().splitlines()[-25:]),
        }
        send, repeats = should_send(sig)
        entry["emailed"] = send
        _write_log(entry)
        if send:
            threading.Thread(target=_send, args=(entry, repeats), daemon=True).start()
    except Exception as e:  # noqa: BLE001
        print("[error-alert] แจ้งเตือนไม่สำเร็จ:", e)


def _send(entry: dict, repeats: int) -> None:
    try:
        from app.services.mailer import send_email
        from app.services.notifications import notification_email
        to = notification_email()
        if to:
            subject, html = build_email(entry, repeats)
            send_email(to, subject, html)
    except Exception as e:  # noqa: BLE001
        print("[error-alert] ส่งอีเมลไม่ได้:", e)
