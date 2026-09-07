#!/usr/bin/env bash
# ============================================================================
# healthcheck.sh - ตรวจสุขภาพระบบ Easy Ekkasan (เหมาะกับ cron)
#
# ตรวจ: service ทำงานไหม · เว็บตอบสนองไหม · ดิสก์เหลือพอไหม · สำรองข้อมูลล่าสุดเมื่อไหร่
# ถ้าพบปัญหา -> ส่งอีเมลแจ้งผู้ขาย (ส่งเมื่อ "สถานะเปลี่ยน" เท่านั้น ไม่สแปมทุกรอบ)
#
# ตั้ง cron (เช็กทุก 15 นาที):
#   sudo crontab -e
#   */15 * * * * /opt/ddoc/deploy/healthcheck.sh >> /var/log/ddoc-health.log 2>&1
#
# ทดสอบด้วยมือ (บังคับส่งอีเมลเพื่อดูว่าอีเมลใช้ได้จริง):
#   sudo /opt/ddoc/deploy/healthcheck.sh --always
#
# ปรับค่าได้ด้วย env: DDOC_SERVICE, DDOC_HEALTH_URL, DDOC_BACKUP_DIR, DDOC_BACKUP_MAX_AGE_H
# ============================================================================
set -uo pipefail

APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
PY="$APP_DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "[$(date '+%F %T')] ไม่พบ python ของแอปที่ $PY" >&2
  exit 2
fi

cd "$APP_DIR" || exit 2
exec "$PY" -m app.services.healthcheck "$@"
