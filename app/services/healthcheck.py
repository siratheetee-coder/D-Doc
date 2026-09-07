# -*- coding: utf-8 -*-
"""
healthcheck.py - ตรวจสุขภาพระบบอัตโนมัติ (รันจาก cron)

ตรวจ 4 อย่างที่ทำให้ระบบ "พังเงียบ" ได้:
  1. service ทำงานอยู่ไหม
  2. เว็บตอบสนองไหม (เรียก /healthz จริง)
  3. พื้นที่ดิสก์เหลือพอไหม
  4. สำรองข้อมูลล่าสุดเมื่อไหร่ (ถ้าเก่าเกินไป = ตาข่ายกันพังหายไปแล้ว)

ใช้:
  /opt/ddoc/.venv/bin/python -m app.services.healthcheck          # ตรวจ + แจ้งเตือนถ้ามีปัญหา
  /opt/ddoc/.venv/bin/python -m app.services.healthcheck --always # ส่งอีเมลทุกครั้ง (ไว้ทดสอบ)

*** ห้าม import app.main ที่นี่ *** เพราะจะไป start thread สำรองข้อมูลซ้ำ
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SERVICE = os.environ.get("DDOC_SERVICE", "ddoc")
HEALTH_URL = os.environ.get("DDOC_HEALTH_URL", "http://127.0.0.1:8000/healthz")
BACKUP_DIR = Path(os.environ.get("DDOC_BACKUP_DIR", "/var/backups/ddoc"))
BACKUP_MAX_AGE_H = float(os.environ.get("DDOC_BACKUP_MAX_AGE_H", "48"))
_STATE = Path(os.environ.get("DDOC_HEALTH_STATE", "/tmp/ddoc-health.state"))


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return p.returncode, (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return 1, str(e)


def check_service() -> dict:
    if not Path("/bin/systemctl").exists() and not Path("/usr/bin/systemctl").exists():
        return {"name": "service", "ok": True, "skip": True, "detail": "ไม่ใช่ระบบ systemd (ข้าม)"}
    code, out = _run(["systemctl", "is-active", SERVICE])
    ok = (out == "active")
    return {"name": "service", "ok": ok,
            "detail": f"{SERVICE} = {out}" + ("" if ok else " (ควรเป็น active)")}


def check_http() -> dict:
    """เรียก /healthz จริง - จับกรณี service ยังขึ้นแต่แอปค้าง/ตอบไม่ได้"""
    try:
        from urllib.request import urlopen
        with urlopen(HEALTH_URL, timeout=10) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
        ok = bool(body.get("ok"))
        return {"name": "http", "ok": ok, "detail": f"{HEALTH_URL} -> ok={body.get('ok')}",
                "body": body}
    except Exception as e:
        return {"name": "http", "ok": False, "detail": f"เรียก {HEALTH_URL} ไม่สำเร็จ: {e}"}


def check_disk() -> dict:
    try:
        from app.services.diskspace import disk_status, status_text
        st = disk_status()
        return {"name": "disk", "ok": st.get("level") in ("ok", "warn"),
                "warn": st.get("level") == "warn",
                "detail": status_text(st) + f" [{st.get('level')}]"}
    except Exception as e:
        return {"name": "disk", "ok": False, "detail": f"อ่านพื้นที่ดิสก์ไม่ได้: {e}"}


def check_backup() -> dict:
    if not BACKUP_DIR.is_dir():
        return {"name": "backup", "ok": False,
                "detail": f"ไม่พบโฟลเดอร์สำรอง {BACKUP_DIR} (ตั้ง cron backup.sh แล้วหรือยัง)"}
    files = sorted(BACKUP_DIR.glob("ddoc-backup-*.tar.gz"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if not files:
        return {"name": "backup", "ok": False, "detail": f"ยังไม่มีไฟล์สำรองใน {BACKUP_DIR}"}
    newest = files[0]
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    size_mb = newest.stat().st_size / (1024 ** 2)
    too_old = age_h > BACKUP_MAX_AGE_H
    too_small = size_mb <= 0.01          # ไฟล์ว่าง/ไม่จบ = สำรองล้มเหลว (มักเกิดตอนดิสก์เต็ม)
    why = ("" if not (too_old or too_small) else
           f" (เก่ากว่า {BACKUP_MAX_AGE_H:.0f} ชม.)" if too_old and not too_small else
           " (ไฟล์ว่าง - การสำรองน่าจะล้มเหลวกลางคัน)" if too_small and not too_old else
           f" (เก่ากว่า {BACKUP_MAX_AGE_H:.0f} ชม. และไฟล์ว่าง)")
    return {"name": "backup", "ok": not (too_old or too_small),
            "detail": f"ล่าสุด {newest.name} · อายุ {age_h:.1f} ชม. · {size_mb:.1f} MB{why}"}


LABEL = {"service": "บริการ (systemd)", "http": "เว็บตอบสนอง",
         "disk": "พื้นที่ดิสก์", "backup": "การสำรองข้อมูล"}


def run_checks() -> list[dict]:
    return [check_service(), check_http(), check_disk(), check_backup()]


def _fingerprint(results: list[dict]) -> str:
    """สถานะรวม (ok/fail ของแต่ละข้อ) ใช้กันส่งอีเมลซ้ำเรื่องเดิม"""
    return ",".join(f"{r['name']}={'1' if r['ok'] else '0'}{'w' if r.get('warn') else ''}"
                    for r in results)


def _alert(results: list[dict], bad: list[dict]) -> None:
    from app.seller_config import SELLER
    from app.services.mailer import send_email, smtp_configured
    to = (SELLER.get("notify_email") or SELLER.get("email") or "").strip()
    if not (to and smtp_configured()):
        print("[healthcheck] ไม่ได้ตั้ง SMTP/อีเมลผู้รับ จึงไม่ส่งอีเมล")
        return
    rows = "".join(
        f"<tr><td>{'❌' if not r['ok'] else ('⚠️' if r.get('warn') else '✅')}</td>"
        f"<td><b>{LABEL.get(r['name'], r['name'])}</b></td><td>{r['detail']}</td></tr>"
        for r in results)
    send_email(to, "[Easy Ekkasan] ตรวจสุขภาพระบบพบปัญหา",
               f"<p><b>พบปัญหา {len(bad)} รายการ</b></p>"
               f"<table cellpadding='6' style='border-collapse:collapse'>{rows}</table>"
               "<p>ตรวจบนเซิร์ฟเวอร์: <code>systemctl status ddoc</code> · "
               "<code>journalctl -u ddoc -n 100</code></p>")
    print(f"[healthcheck] ส่งอีเมลแจ้งเตือนไปที่ {to} แล้ว")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    always = "--always" in argv
    results = run_checks()
    bad = [r for r in results if not r["ok"]]
    stamp = time.strftime("%F %T")
    for r in results:
        icon = "OK  " if r["ok"] else "FAIL"
        print(f"[{stamp}] {icon} {LABEL.get(r['name'], r['name'])}: {r['detail']}")

    fp = _fingerprint(results)
    prev = ""
    try:
        prev = _STATE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    # ส่งอีเมลเมื่อ "สถานะเปลี่ยน" เท่านั้น กันสแปมทุกรอบ cron
    if bad and (always or fp != prev):
        try:
            _alert(results, bad)
        except Exception as e:
            print("[healthcheck] ส่งอีเมลไม่สำเร็จ:", e)
    elif not bad and prev and prev != fp:
        print("[healthcheck] กลับมาปกติแล้ว")
    try:
        _STATE.write_text(fp, encoding="utf-8")
    except OSError:
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
