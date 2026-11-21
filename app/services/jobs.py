"""งานอัตโนมัติรายวัน รันในโปรเซสแอปหลัก (แทน cron ที่เป็นโปรเซสแยก)

เดิม cron 4 งานเปิดฐานข้อมูลจากโปรเซสแยก ร่วมกับการที่แอปเคยเปิด/คัดลอกไฟล์ .db เอง (ล็อกหลุด)
ทำให้ไฟล์ -wal หาย 2 ครั้ง (26 ต.ค. / 14 พ.ย. 2569) ดู app/services/db_snapshot.py
ตอนนี้: ตัวจับเวลาในแอป (worker เดียวที่จับ file lock ได้) รันงานตามเวลา เฉพาะงานที่เจ้าของเปิดไว้
ทุกงานเริ่มต้น "ปิด" เจ้าของต้องกดดูผลแบบไม่ทำจริงในคอนโซลก่อน แล้วค่อยเปิดทีละงาน

ตัวเฝ้า -wal: ทุก 5 นาที ถ้าไฟล์ -wal ของฐานที่แอปเปิดอยู่หายไป อีเมลแจ้งเจ้าของทันที (ชั่วโมงละครั้ง)
"""
import contextlib
import io
import json
import os
import threading
import time
from datetime import datetime

_RUN_LOCK = threading.Lock()


def _log(*a):
    """พิมพ์ log แบบไม่มีวันทำให้แอปพัง (คอนโซล Windows พิมพ์ภาษาไทยไม่ได้)"""
    try:
        print(*a)
    except Exception:  # noqa: BLE001
        pass
_LOCK_FD = None


def _job_trial(dry):
    from app.services import trial_notice, trial_nurture
    trial_notice.run(dry_run=dry)
    trial_nurture.run(dry_run=dry)


def _job_member(dry):
    from app.services import member_notice
    member_notice.run(dry_run=dry)


def _job_retention(dry):
    from app.services import retention
    retention.run(dry_run=dry)


def _job_finance(dry):
    from app.services import finance_health
    if dry:
        print("ตรวจอย่างเดียว ไม่แก้ข้อมูล โหมดดูก่อนกับรันจริงจึงเหมือนกัน (บันทึกผลลงหน้าข้อมูลการเงินทุกโรงเรียน)")
    d = finance_health.scan_all()
    bad = [r for r in d["schools"] if (r.get("counts") or {}).get("fix")]
    print(f"ตรวจ {len(d['schools'])} โรงเรียน มีสิ่งที่ควรแก้ {len(bad)} โรงเรียน")


# key: (ชื่อ, เวลา HH:MM, คำอธิบาย, ฟังก์ชัน)  เรียงตามความเสี่ยง น้อยไปมาก
JOBS = {
    "finance_health": ("ตรวจข้อมูลการเงินทุกโรงเรียน", "05:00", "อ่านอย่างเดียว ไม่แก้ข้อมูล", _job_finance),
    "member_notice": ("อีเมลเตือนสมาชิกใกล้หมดอายุ", "08:00", "ส่งอีเมลหาโรงเรียน", _job_member),
    "trial_notice": ("อีเมลเตือนช่วงทดลองใช้ + อีเมลแนะนำการใช้งาน", "09:00", "ส่งอีเมลหาโรงเรียน", _job_trial),
    "retention": ("ล้างข้อมูลโรงเรียนที่หมดอายุนานแล้ว", "03:30", "ลบข้อมูล (เตือนก่อนลบตามนโยบาย)", _job_retention),
}


def _state_path():
    from app.database import get_data_dir
    return get_data_dir() / "jobs.json"


def load_state() -> dict:
    try:
        st = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    for k in JOBS:
        st.setdefault(k, {"enabled": False})
    return st


def _save_state(st: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def set_enabled(key: str, on: bool) -> None:
    if key not in JOBS:
        raise KeyError(key)
    st = load_state()
    st[key]["enabled"] = bool(on)
    _save_state(st)


def run_job(key: str, dry_run: bool) -> str:
    """รันงานเดียว คืนข้อความผล (ที่งานพิมพ์ออกมา) · รันพร้อมกันได้ทีละงาน"""
    if key not in JOBS:
        raise KeyError(key)
    fn = JOBS[key][3]
    buf = io.StringIO()
    with _RUN_LOCK:
        t0 = time.time()
        try:
            with contextlib.redirect_stdout(buf):
                fn(dry_run)
            ok = True
        except Exception as e:  # noqa: BLE001  งานพังต้องไม่ทำให้แอปพัง
            buf.write(f"\nผิดพลาด: {e!r}")
            ok = False
        out = buf.getvalue().strip()[-6000:] or "(ไม่มีรายการที่ต้องทำ)"
        st = load_state()
        rec = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "ok": ok, "secs": round(time.time() - t0, 1),
               "out": out}
        st[key]["last_dry" if dry_run else "last_run"] = rec
        _save_state(st)
    _log(f"[jobs] {key} {'ดูก่อน' if dry_run else 'รันจริง'} {'สำเร็จ' if ok else 'ผิดพลาด'}")
    return out


def due(now: datetime, st: dict):
    """งานที่ถึงเวลารันวันนี้แล้วและยังไม่ได้รัน"""
    today = now.strftime("%Y-%m-%d")
    for k, (_n, hhmm, _d, _f) in JOBS.items():
        s = st.get(k) or {}
        if not s.get("enabled"):
            continue
        if now.strftime("%H:%M") < hhmm:
            continue
        if (s.get("last_run") or {}).get("at", "")[:10] == today:
            continue
        yield k


# ---------------- ตัวเฝ้า -wal ----------------
_wal_alerted = {}


def missing_wal() -> list:
    """ฐานที่แอปเปิดค้างอยู่ แต่ไฟล์ -wal หายไป (อาการก่อนข้อมูลแตกสองชุด)"""
    from pathlib import Path
    out = []
    try:
        from app import accounts
        if accounts._engine is not None:
            p = accounts.get_data_dir() / "accounts.db"
            if p.exists() and not Path(str(p) + "-wal").exists():
                out.append(str(p))
    except Exception:
        pass
    try:
        from app import tenancy
        for sid, (engine, _SL) in list(tenancy._engines.items()):
            pool = engine.pool
            try:
                n_open = pool.checkedin() + pool.checkedout()
            except Exception:
                n_open = 1
            if not n_open:
                continue
            p = tenancy.school_db_path(sid)
            if Path(p).exists() and not Path(str(p) + "-wal").exists():
                out.append(str(p))
    except Exception:
        pass
    return out


def check_wal() -> list:
    bad = missing_wal()
    now = time.time()
    fresh = [p for p in bad if now - _wal_alerted.get(p, 0) > 3600]
    if fresh:
        for p in fresh:
            _wal_alerted[p] = now
        try:
            from app.seller_config import SELLER
            from app.services.mailer import send_email, smtp_configured
            to = (SELLER.get("notify_email") or SELLER.get("email") or "").strip()
            if to and smtp_configured():
                send_email(to, "[Easy Ekkasan] ด่วน: ไฟล์ -wal ของฐานข้อมูลหายขณะระบบทำงาน",
                           "<p><b>ไฟล์ -wal หายไปขณะแอปเปิดฐานข้อมูลอยู่</b> ข้อมูลอาจแตกเป็นสองชุด</p><ul>"
                           + "".join(f"<li>{p}</li>" for p in fresh)
                           + "</ul><p><b>ห้ามรีสตาร์ทระบบ</b> ให้ดึงไฟล์คืนด้วย deploy/rescue_deleted_wal.sh ก่อน</p>")
        except Exception as e:
            _log("[jobs] ส่งอีเมลเตือน -wal ไม่สำเร็จ:", e)
        _log("[jobs] !! ไฟล์ -wal หาย:", fresh)
    return bad


# ---------------- ตัวจับเวลา ----------------
def start() -> bool:
    """เริ่มตัวจับเวลา (เรียกตอนแอปเริ่ม) · หลาย worker: ตัวที่จับ file lock ได้ตัวเดียวทำงาน
    ปิดได้ด้วย DDOC_JOBS=0 (เทสต์ปิดไว้)"""
    global _LOCK_FD
    if os.environ.get("DDOC_JOBS", "1") == "0":
        return False
    from app.database import get_data_dir
    try:
        import fcntl
        _LOCK_FD = os.open(str(get_data_dir() / ".jobs.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(_LOCK_FD)
            _LOCK_FD = None
            return False
    except ImportError:
        pass                # Windows (เครื่องพัฒนา) โปรเซสเดียว

    def loop():
        time.sleep(60)
        tick = 0
        while True:
            try:
                for k in list(due(datetime.now(), load_state())):
                    run_job(k, dry_run=False)
            except Exception as e:  # noqa: BLE001
                _log("[jobs] ผิดพลาด:", e)
            if tick % 5 == 0:
                try:
                    check_wal()
                except Exception as e:  # noqa: BLE001
                    _log("[jobs] ตรวจ -wal ผิดพลาด:", e)
            tick += 1
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="ddoc-jobs").start()
    _log("[Easy Ekkasan] เปิดตัวจับเวลางานอัตโนมัติในแอป")
    return True
