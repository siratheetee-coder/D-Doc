"""Conservative email checks and shared, transactional signup limits."""
import hashlib
import time
from sqlalchemy import text


def email_problem(email):
    email = (email or "").strip().lower()
    if len(email) > 254 or email.count("@") != 1:
        return "กรุณากรอกอีเมลให้ถูกต้อง"
    local, domain = email.rsplit("@", 1)
    if not local or any(c.isspace() for c in email):
        return "กรุณากรอกอีเมลให้ถูกต้อง"
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return "กรุณากรอกอีเมลให้ถูกต้อง"
    if any(domain == d or domain.endswith("." + d) for d in
           ("example.com", "example.net", "example.org", "invalid", "localhost", "test")):
        return "กรุณาใช้อีเมลจริงที่สามารถรับข้อความได้ ไม่ใช่อีเมลตัวอย่าง"
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        # Server missing dnspython (requirements not installed yet): skip only the MX lookup.
        # Registration must never 500 because of an optional check.
        return None
    resolver = dns.resolver.Resolver()
    resolver.timeout = 1
    resolver.lifetime = 2
    try:
        records = resolver.resolve(domain, "MX")
        if all(str(r.exchange) == "." for r in records):
            return "โดเมนของอีเมลนี้ไม่รองรับการรับข้อความ กรุณาตรวจสอบอีกครั้ง"
    except dns.resolver.NXDOMAIN:
        return "ไม่พบโดเมนของอีเมลนี้ กรุณาตรวจสอบส่วนหลัง @ อีกครั้ง"
    except dns.resolver.NoAnswer:
        # No MX alone is not proof: SMTP allows fallback to A/AAAA.
        pass
    except dns.exception.DNSException:
        # DNS outages must not reject real applicants.
        pass
    return None


def throttle(request, email):
    from app.accounts import acc_session, SignupThrottle
    # Only ASGI's trusted-proxy-resolved address; never arbitrary forwarded headers.
    ip = request.client.host if request.client else "unknown"
    now = int(time.time())
    limits = [("ip:" + ip, 900, 30), ("email:" + email.strip().lower(), 120, 1)]
    db = acc_session()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        db.query(SignupThrottle).filter(SignupThrottle.started < now - 86400).delete()
        rows = []
        for identity, window, maximum in limits:
            key = hashlib.sha256(identity.encode()).hexdigest()
            row = db.get(SignupThrottle, key)
            if row is None:
                row = SignupThrottle(key=key, started=now, count=0)
                db.add(row)
            elif now - row.started >= window:
                row.started, row.count = now, 0
            if row.count >= maximum:
                wait = max(1, window - (now - row.started))
                db.rollback()
                return wait
            rows.append(row)
        for row in rows:
            row.count += 1
        db.commit()
        return 0
    finally:
        db.close()
