# -*- coding: utf-8 -*-
"""
restore_tenants.py - กู้คืน "เฉพาะโรงเรียนที่ถูกลบ" จากไฟล์สำรอง โดยไม่แตะข้อมูลโรงเรียนอื่น

ใช้เมื่อ: โรงเรียนบางแห่งถูกลบไป (เช่น 2026-10-14 ระบบลบการสมัครที่ยังไม่ยืนยันอีเมล 20 แห่งตอนเปิดเซิร์ฟเวอร์)
แต่โรงเรียนอื่นมีข้อมูลใหม่หลังวันสำรองแล้ว จึงกู้ทั้งระบบทับไม่ได้

กู้อะไรบ้าง (เฉพาะโรงเรียนที่ "มีในไฟล์สำรอง แต่ไม่มีในระบบตอนนี้")
  - แถว tenant (id เดิม) + บัญชีผู้ใช้ทุกบัญชีของโรงเรียนนั้น + คำขอจากเว็บ (lead) ที่ผูกโรงเรียนนั้น
  - ไฟล์ฐานข้อมูลของโรงเรียน (schools/<id>/school.db) ถ้ามีในไฟล์สำรองและยังไม่มีในระบบ
ไม่กู้ถ้าชน: id โรงเรียนถูกใช้ไปแล้ว หรือชื่อผู้ใช้ (อีเมล) ถูกสมัครใหม่ไปแล้ว -> ข้ามและแจ้ง

วิธีใช้บนเซิร์ฟเวอร์
  1) แตกไฟล์สำรองก่อนวันที่ลบ ไปไว้ที่โฟลเดอร์ชั่วคราว (ไม่ทับของจริง)
  2) ดูก่อน:   sudo -u ddoc .venv/bin/python tools/restore_tenants.py --from /tmp/ddoc-old
  3) กู้จริง:  sudo -u ddoc .venv/bin/python tools/restore_tenants.py --from /tmp/ddoc-old --confirm
  เลือกเฉพาะบาง id:  --ids 7,10,16
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _rows(con, sql, args=()):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, args)]


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def plan(old_dir: Path, only_ids=None) -> dict:
    """ดูว่าจะกู้อะไร ชนอะไร (ไม่แก้ข้อมูล)"""
    from app.database import get_data_dir
    old = sqlite3.connect(f"file:{old_dir / 'accounts.db'}?mode=ro", uri=True)
    cur = sqlite3.connect(f"file:{get_data_dir() / 'accounts.db'}?mode=ro", uri=True)
    try:
        now_ids = {r[0] for r in cur.execute("SELECT id FROM tenant")}
        now_users = {(r[0] or "").lower() for r in cur.execute("SELECT username FROM account")}
        out, skipped = [], []
        for t in _rows(old, "SELECT * FROM tenant ORDER BY id"):
            if only_ids is not None and t["id"] not in only_ids:
                continue
            if t["id"] in now_ids or (t.get("plan") or "") == "sandbox":
                continue
            accs = _rows(old, "SELECT * FROM account WHERE tenant_id=?", (t["id"],))
            clash = [a["username"] for a in accs if (a["username"] or "").lower() in now_users]
            if clash:
                skipped.append((t["id"], t["name"], "อีเมลนี้สมัครใหม่ไปแล้ว: " + ", ".join(clash)))
                continue
            leads = _rows(old, "SELECT * FROM lead WHERE tenant_id=?", (t["id"],))
            out.append({"tenant": t, "accounts": accs, "leads": leads})
        return {"restore": out, "skipped": skipped}
    finally:
        old.close()
        cur.close()


def apply(old_dir: Path, p: dict) -> int:
    from app.accounts import acc_session, audit
    from app.database import get_data_dir
    db = acc_session()
    try:
        con = db.connection().connection          # sqlite3 ของระบบ (ล็อกเดียวกับแอป)
        cols = {t: set(_cols(con, t)) for t in ("tenant", "account", "lead")}
        live_lead_ids = {r[0] for r in con.execute("SELECT id FROM lead")}

        def insert(table, row, keep_id=True):
            row = {k: v for k, v in row.items() if k in cols[table] and (keep_id or k != "id")}
            names = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            con.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(row.values()))

        for item in p["restore"]:
            insert("tenant", item["tenant"])
            for a in item["accounts"]:
                insert("account", a, keep_id=False)       # id บัญชีอาจถูกใช้ไปแล้ว ให้ระบบออกใหม่
            for l in item["leads"]:
                insert("lead", l, keep_id=l["id"] not in live_lead_ids)
        con.commit()
    finally:
        db.close()
    for item in p["restore"]:
        tid = item["tenant"]["id"]
        src = old_dir / "schools" / str(tid) / "school.db"
        dst = get_data_dir() / "schools" / str(tid) / "school.db"
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    if p["restore"]:
        audit("tenant.restored", tenant_id=None, uid=None, target=f"{len(p['restore'])} โรงเรียน",
              detail=", ".join(i["tenant"]["name"] for i in p["restore"])[:400])
    return len(p["restore"])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="โฟลเดอร์ที่แตกไฟล์สำรองไว้ (มี accounts.db)")
    ap.add_argument("--ids", default="", help="เฉพาะ id เหล่านี้ คั่นด้วย ,")
    ap.add_argument("--confirm", action="store_true", help="กู้จริง (ไม่ใส่ = ดูอย่างเดียว)")
    a = ap.parse_args()
    src = Path(a.src)
    if not (src / "accounts.db").exists():
        raise SystemExit(f"ไม่พบ {src / 'accounts.db'} (แตกไฟล์สำรองถูกที่หรือยัง)")
    ids = {int(x) for x in a.ids.split(",") if x.strip().isdigit()} or None
    p = plan(src, ids)
    print(f"จะกู้ {len(p['restore'])} โรงเรียน" + ("" if a.confirm else " (ดูอย่างเดียว ยังไม่กู้)"))
    for item in p["restore"]:
        t = item["tenant"]
        print(f"  + #{t['id']} {t['name']} · {', '.join(x['username'] for x in item['accounts'])}"
              f" · คำขอ {len(item['leads'])}")
    for tid, name, why in p["skipped"]:
        print(f"  ! ข้าม #{tid} {name}: {why}")
    if a.confirm:
        print(f"กู้แล้ว {apply(src, p)} โรงเรียน")


if __name__ == "__main__":
    main()
