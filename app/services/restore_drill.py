# -*- coding: utf-8 -*-
"""ซ้อมกู้ข้อมูลจากไฟล์สำรอง โดย "ไม่แตะข้อมูลจริงเลย"

    sudo /opt/ddoc/deploy/restore-drill.sh              # ไฟล์สำรองล่าสุด
    sudo /opt/ddoc/deploy/restore-drill.sh <ไฟล์>       # ระบุไฟล์
    sudo /opt/ddoc/deploy/restore-drill.sh --no-email   # ไม่ต้องส่งอีเมลสรุป

ทำอะไร (ทั้งหมดเกิดในโฟลเดอร์ชั่วคราวที่สร้างใหม่ ไม่ใช่ /opt/ddoc/data)
  1) ถอดรหัส + แตกไฟล์สำรองลงโฟลเดอร์ชั่วคราว (สิทธิ์ 700 เพราะมีข้อมูลนักเรียน)
  2) ตรวจทุกฐานข้อมูลในไฟล์สำรอง: integrity_check + เปิดอ่านทุกตาราง
  3) เทียบกับระบบจริงแบบ "อ่านอย่างเดียว": โรงเรียนที่มีก่อนเวลาสำรองต้องอยู่ในไฟล์สำรองครบ
  4) ลบโฟลเดอร์ชั่วคราวทิ้งทุกครั้ง (สำเร็จหรือไม่ก็ตาม) แล้วอีเมลสรุปผลให้เจ้าของระบบ

ไม่หยุดบริการ · ไม่เขียนอะไรลง data/ · ไม่เปิดฐานข้อมูลจริงตรง ๆ เลย: คัดลอก accounts.db (+ -wal) ไปไว้ในโฟลเดอร์
ชั่วคราวแล้วอ่านจากสำเนา (เปิด WAL แบบ mode=ro ตรง ๆ ยังสร้างไฟล์ -wal/-shm ของ root ไว้ข้างฐานจริงได้
ซึ่งทำให้บริการที่รันด้วยผู้ใช้ ddoc เขียนไม่ได้)
สรุปผลมีแต่ตัวเลข ไม่มีข้อมูลส่วนบุคคล
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path(os.environ.get("DDOC_BACKUP_DIR", "/var/backups/ddoc"))
KEYFILE = Path(os.environ.get("DDOC_BACKUP_KEYFILE", "/etc/ddoc-backup.key"))
WORK_ROOT = os.environ.get("DDOC_DRILL_DIR", "/var/tmp")
KEY_TABLES = ("student", "person", "finance_txn", "procurement", "asset", "document")
GRACE_SEC = 3600      # โรงเรียนที่สมัครภายใน 1 ชม. ก่อนเวลาสำรอง อาจยังไม่ทันเข้าไฟล์สำรอง


def latest_backup(backup_dir: Path = None):
    d = backup_dir or BACKUP_DIR
    files = list(d.glob("ddoc-backup-*.tar.gz.enc")) + list(d.glob("ddoc-backup-*.tar.gz"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def _extract(backup: Path, keyfile: Path, dest: Path) -> None:
    """ถอดรหัส (ถ้าเป็น .enc) แล้วแตก tar ลง dest · กันไฟล์ใน tar ที่พยายามเขียนออกนอก dest"""
    def safe_extract(tf: tarfile.TarFile):
        for m in tf:
            target = (dest / m.name).resolve()
            if not _inside(target, dest) or m.issym() or m.islnk() or m.isdev():
                raise ValueError(f"ไฟล์สำรองมีรายการผิดรูปแบบ: {m.name}")
            tf.extract(m, dest)

    if backup.name.endswith(".enc"):
        if not keyfile.is_file():
            raise ValueError(f"ไม่พบรหัสลับ {keyfile} (ไฟล์สำรองเข้ารหัสไว้)")
        p = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                              "-pass", f"file:{keyfile}", "-in", str(backup)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=p.stdout, mode="r|gz") as tf:
                safe_extract(tf)
        except (tarfile.TarError, OSError, EOFError) as e:
            p.kill()
            raise ValueError(f"ถอดรหัส/แตกไฟล์ไม่สำเร็จ (รหัสลับไม่ตรงหรือไฟล์เสีย): {e}") from e
        finally:
            p.stdout.close()
            err = p.stderr.read().decode(errors="replace").strip()
            p.stderr.close()
            rc = p.wait()
        if rc != 0:
            raise ValueError(f"ถอดรหัสไม่สำเร็จ (รหัสลับไม่ตรงหรือไฟล์เสีย): {err[:200]}")
    else:
        try:
            with tarfile.open(backup, mode="r:gz") as tf:
                safe_extract(tf)
        except (tarfile.TarError, OSError, EOFError) as e:
            raise ValueError(f"แตกไฟล์ไม่สำเร็จ: {e}") from e


def _ro(path: Path) -> sqlite3.Connection:
    """เปิดอ่านอย่างเดียว · ใช้กับไฟล์ในโฟลเดอร์ชั่วคราวเท่านั้น (ฐาน WAL อาจสร้าง -wal/-shm ข้าง ๆ)"""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _db_check(path: Path) -> tuple[bool, str, dict]:
    """(ใช้ได้ไหม, เหตุผล, {ตาราง: จำนวนแถว})"""
    try:
        con = _ro(path)
        try:
            res = con.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                return False, f"integrity_check: {res[:120]}", {}
            counts = {}
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                counts[t] = con.execute(f'SELECT count(*) FROM "{t}" NOT INDEXED').fetchone()[0]
            return True, "", counts
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return False, str(e)[:160], {}


def _tenants(accounts_db: Path) -> dict:
    """{id: (plan, created_at)} ไม่รวมระบบตัวอย่าง"""
    con = _ro(accounts_db)
    try:
        rows = con.execute("SELECT id, plan, created_at FROM tenant").fetchall()
    finally:
        con.close()
    return {r[0]: (r[1] or "", r[2] or "") for r in rows if (r[1] or "") != "sandbox"}


def _created_before(created: str, ts: float) -> bool:
    try:
        return datetime.fromisoformat(str(created)[:19]).timestamp() < ts - GRACE_SEC
    except ValueError:
        return True


def drill(backup: Path, keyfile: Path, live_dir: Path, work_root: str = None) -> dict:
    report = {"backup": backup.name, "backup_time": datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
              "size_mb": round(backup.stat().st_size / 1024 ** 2, 1), "ok": False,
              "problems": [], "warnings": [], "stats": {}}
    t0 = time.time()
    root = work_root or WORK_ROOT
    if not os.path.isdir(root):
        root = None                         # ไม่มีโฟลเดอร์ที่ตั้งไว้ ใช้ temp ของระบบ
    work = Path(tempfile.mkdtemp(prefix="ddoc-drill-", dir=root))
    try:
        if _inside(work, live_dir):
            raise ValueError("โฟลเดอร์ชั่วคราวอยู่ในโฟลเดอร์ข้อมูลจริง ยกเลิกเพื่อความปลอดภัย")
        os.chmod(work, 0o700)
        _extract(backup, keyfile, work)

        dbs = sorted(work.rglob("*.db"))
        acc = work / "accounts.db"
        if not acc.is_file():
            raise ValueError("ไฟล์สำรองไม่มี accounts.db")
        bad = 0
        totals = {t: 0 for t in KEY_TABLES}
        for db in dbs:
            ok, why, counts = _db_check(db)
            if not ok:
                bad += 1
                report["problems"].append(f"ฐานข้อมูลเสีย {db.relative_to(work).as_posix()}: {why}")
            for t in KEY_TABLES:
                totals[t] += counts.get(t, 0)
        if not (work / "secret.key").is_file():
            report["warnings"].append("ไฟล์สำรองไม่มี secret.key (กู้แล้วผู้ใช้ทุกคนต้องล็อกอินใหม่)")

        b_ten = _tenants(acc)
        missing_db = [tid for tid in b_ten if not (work / "schools" / str(tid) / "school.db").is_file()]
        if missing_db:
            report["warnings"].append(f"โรงเรียนในไฟล์สำรองที่ยังไม่มีฐานข้อมูลโรงเรียน {len(missing_db)} แห่ง "
                                      f"(ปกติถ้ายังไม่เคยเปิดใช้งาน) id: {missing_db[:10]}")
        live_acc = live_dir / "accounts.db"
        live_n = None
        if live_acc.is_file():
            snap = work / "_live_copy"
            snap.mkdir()
            for suffix in ("", "-wal"):                 # อ่านอย่างเดียวจากของจริง (คัดลอกไฟล์) ไม่เปิดด้วย sqlite
                src = live_dir / ("accounts.db" + suffix)
                if src.is_file():
                    shutil.copyfile(src, snap / ("accounts.db" + suffix))
            l_ten = _tenants(snap / "accounts.db")
            live_n = len(l_ten)
            lost = [tid for tid, (_plan, created) in l_ten.items()
                    if tid not in b_ten and _created_before(created, backup.stat().st_mtime)]
            if lost:
                report["problems"].append(f"โรงเรียนที่มีอยู่ก่อนเวลาสำรอง แต่ไม่อยู่ในไฟล์สำรอง {len(lost)} แห่ง id: {lost[:10]}")
        else:
            report["warnings"].append(f"ไม่พบ {live_acc} เลยเทียบกับระบบจริงไม่ได้")

        report["stats"] = {"databases": len(dbs), "databases_bad": bad, "schools_in_backup": len(b_ten),
                           "schools_live": live_n, **{f"rows_{t}": n for t, n in totals.items()}}
        report["ok"] = not report["problems"]
    except Exception as e:  # noqa: BLE001  ทุกความผิดพลาด = ซ้อมไม่ผ่าน (ข้อมูลจริงไม่ถูกแตะ)
        report["problems"].append(str(e)[:300])
    finally:
        shutil.rmtree(work, ignore_errors=True)
        report["cleaned"] = not work.exists()
        if not report["cleaned"]:
            report["problems"].append(f"ลบโฟลเดอร์ชั่วคราวไม่หมด {work} (มีข้อมูลนักเรียน ลบเองด้วย)")
            report["ok"] = False
        report["seconds"] = round(time.time() - t0, 1)
    return report


def format_report(r: dict) -> str:
    lines = [f"ซ้อมกู้ข้อมูล: {'ผ่าน' if r['ok'] else 'ไม่ผ่าน'}",
             f"ไฟล์สำรอง: {r['backup']} ({r['backup_time']}, {r['size_mb']} MB) · ใช้เวลา {r.get('seconds')} วินาที"]
    s = r.get("stats") or {}
    if s:
        lines.append(f"ฐานข้อมูล {s['databases']} ไฟล์ (เสีย {s['databases_bad']}) · โรงเรียนในไฟล์สำรอง {s['schools_in_backup']}"
                     f" · ในระบบจริงตอนนี้ {s['schools_live'] if s['schools_live'] is not None else '-'}")
        lines.append("จำนวนแถว: " + " · ".join(f"{k[5:]} {v:,}" for k, v in s.items() if k.startswith("rows_")))
    lines += [f"ปัญหา: {p}" for p in r["problems"]] + [f"หมายเหตุ: {w}" for w in r["warnings"]]
    lines.append("ข้อมูลจริงไม่ถูกแตะ · ลบสำเนาชั่วคราวแล้ว" if r.get("cleaned") else "!! ลบสำเนาชั่วคราวไม่หมด")
    return "\n".join(lines)


def _email(r: dict) -> None:
    try:
        from app.services.mailer import send_email
        from app.services.notifications import notification_email
        to = notification_email()
        if not to:
            return
        body = format_report(r).replace("&", "&amp;").replace("<", "&lt;")
        send_email(to, f"[Easy Ekkasan] ซ้อมกู้ข้อมูล{'ผ่าน' if r['ok'] else 'ไม่ผ่าน'} ({r['backup_time']})",
                   f'<pre style="font-family:sans-serif;font-size:14px;white-space:pre-wrap">{body}</pre>')
    except Exception as e:  # noqa: BLE001
        print("ส่งอีเมลสรุปไม่ได้:", e)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    no_email = "--no-email" in args
    args = [a for a in args if a != "--no-email"]
    from app.database import get_data_dir
    backup = Path(args[0]) if args else latest_backup()
    if backup is None or not backup.is_file():
        r = {"backup": str(backup or BACKUP_DIR), "backup_time": "-", "size_mb": 0, "ok": False,
             "problems": [f"ไม่พบไฟล์สำรองใน {BACKUP_DIR}"], "warnings": [], "stats": {}, "cleaned": True}
    else:
        r = drill(backup, KEYFILE, get_data_dir())
    print(f"[{datetime.now():%F %T}]")
    print(format_report(r))
    if not no_email:
        _email(r)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
