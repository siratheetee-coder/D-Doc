# -*- coding: utf-8 -*-
"""
marketing.py - รู้ว่าลูกค้ามาจากช่องทางไหน และหลุดที่ขั้นไหน (หน้า /admin-console/marketing)

  ช่องทางมี 2 แบบ
  - "รู้จักเราจากไหน": ปุ่มที่ผู้สมัครกดเองในหน้าสมัคร (Tenant.signup_source)
  - ลิงก์ที่มา: ?ref=ชื่อ ในลิงก์ที่เจ้าของแชร์ ระบบจำไว้ในคุกกี้ 60 วัน (Tenant.signup_ref)

  ขั้นของลูกค้า: สมัคร -> ยืนยันอีเมล -> ใช้งานจริง (ออกเอกสารอย่างน้อย 1 ฉบับ) -> จ่ายเงิน
"""
from datetime import date, datetime, timedelta

SOURCES = ["Facebook", "LINE", "YouTube", "TikTok", "ค้นหาใน Google",
           "เพื่อนครูแนะนำ", "เขตพื้นที่ / งานอบรม", "อื่น ๆ"]
OTHER = "อื่น ๆ"
NONE_LABEL = "ไม่ระบุ"
RANGES = [(30, "30 วัน"), (90, "90 วัน"), (365, "1 ปี"), (0, "ทั้งหมด")]
REF_COOKIE = "ee_ref"
SANDBOX_COOKIE = "ee_sbx"
COOKIE_AGE = 60 * 24 * 3600


def read_ref(request) -> str:
    """ชื่อลิงก์ที่มาจากคุกกี้ (เก็บแบบ URL-encode เพราะชื่อภาษาไทยใส่ในคุกกี้ตรง ๆ ไม่ได้)"""
    from urllib.parse import unquote
    from app.services.sandbox import clean_ref
    return clean_ref(unquote(request.cookies.get(REF_COOKIE, "") or ""))


def normalize_source(choice: str, other: str = "") -> str:
    choice = (choice or "").strip()
    if choice not in SOURCES:
        return ""
    if choice == OTHER:
        other = " ".join((other or "").split())[:60]
        return f"{OTHER}: {other}" if other else OTHER
    return choice


def record_signup(tenant_id, source: str = "", ref: str = "", from_sandbox: bool = False) -> None:
    from app.accounts import acc_session, Tenant
    from app.services.sandbox import clean_ref
    if not tenant_id:
        return
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return
        if source and not t.signup_source:
            t.signup_source = source
        if ref and not t.signup_ref:
            t.signup_ref = clean_ref(ref)
        if from_sandbox:
            t.from_sandbox = True
        db.commit()
    finally:
        db.close()


def _group(src: str) -> str:
    """'อื่น ๆ: ครูในกลุ่ม' นับรวมใน 'อื่น ๆ' (รายละเอียดดูในรายการด้านล่าง)"""
    if not src:
        return NONE_LABEL
    return OTHER if src.startswith(OTHER) else src


def summary(days: int = 90, today: date | None = None) -> dict:
    from app.accounts import acc_session, Tenant, Account, SandboxVisit, UsageDay
    from sqlalchemy import func
    today = today or date.today()
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time()) if days else None
    db = acc_session()
    try:
        q = db.query(Tenant).filter(Tenant.plan != "sandbox")
        if start:
            q = q.filter(Tenant.created_at >= start)
        tenants = q.all()
        ids = [t.id for t in tenants]
        verified = {tid for (tid,) in db.query(Account.tenant_id)
                    .filter(Account.tenant_id.in_(ids), Account.is_owner.is_(True),
                            Account.verified.is_(True))} if ids else set()
        used = {tid for (tid,) in db.query(UsageDay.tenant_id).filter(UsageDay.tenant_id.in_(ids))
                .group_by(UsageDay.tenant_id).having(func.sum(UsageDay.docs) > 0)} if ids else set()
        vq = db.query(SandboxVisit)
        if start:
            vq = vq.filter(SandboxVisit.created_at >= start)
        visits = vq.all()
    finally:
        db.close()

    def row(label):
        return {"label": label, "signup": 0, "verified": 0, "used": 0, "paid": 0, "sandbox": 0}

    by_src = {s: row(s) for s in SOURCES}
    by_src[NONE_LABEL] = row(NONE_LABEL)
    by_ref, others = {}, []
    tot = row("รวม")
    for t in tenants:
        flags = {"signup": True, "verified": t.id in verified, "used": t.id in used,
                 "paid": (t.plan or "member") == "member"}
        src = t.signup_source or ""
        if src.startswith(OTHER + ":"):
            others.append(src[len(OTHER) + 1:].strip())
        targets = [by_src[_group(src)], tot]
        if t.signup_ref:
            targets.append(by_ref.setdefault(t.signup_ref, row(t.signup_ref)))
        for r in targets:
            for k, v in flags.items():
                r[k] += 1 if v else 0
            r["sandbox"] += 1 if t.from_sandbox else 0
    ref_visits = {}
    for v in visits:
        if v.ref:
            ref_visits[v.ref] = ref_visits.get(v.ref, 0) + 1
    for ref, n in ref_visits.items():
        by_ref.setdefault(ref, row(ref))["visits"] = n
    for r in by_ref.values():
        r.setdefault("visits", 0)
    for r in list(by_src.values()) + list(by_ref.values()) + [tot]:
        r["rate"] = round(r["paid"] * 100 / r["signup"]) if r["signup"] else None
    src_rows = [r for r in by_src.values() if r["signup"]]
    src_rows.sort(key=lambda r: (-r["signup"], r["label"] == NONE_LABEL))
    return {
        "sources": src_rows, "refs": sorted(by_ref.values(), key=lambda r: (-r["signup"], -r["visits"])),
        "total": tot, "others": others, "visits": len(visits),
        "after_sandbox": sum(1 for t in tenants if t.from_sandbox),
    }
