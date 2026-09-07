#!/usr/bin/env bash
# ============================================================================
# setup-cron.sh - ติดตั้งงานอัตโนมัติ (สำรองข้อมูล + ตรวจสุขภาพระบบ) ให้ครบในคำสั่งเดียว
#
#   sudo /opt/ddoc/deploy/setup-cron.sh
#
# ปลอดภัย: รันซ้ำได้ไม่เพิ่มรายการซ้ำ · ไม่ลบ cron อื่นที่มีอยู่เดิม
# ถอนออก:  sudo /opt/ddoc/deploy/setup-cron.sh --remove
# ============================================================================
set -uo pipefail

APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
BACKUP_SH="$APP_DIR/deploy/backup.sh"
HEALTH_SH="$APP_DIR/deploy/healthcheck.sh"
MARK="# ddoc-auto"          # ป้ายกำกับ ไว้หาบรรทัดของเราเวลารันซ้ำ/ถอนออก

if [ "$(id -u)" -ne 0 ]; then
  echo "ต้องรันด้วย sudo: sudo $0" >&2
  exit 1
fi

for f in "$BACKUP_SH" "$HEALTH_SH"; do
  if [ ! -f "$f" ]; then
    echo "ไม่พบไฟล์ $f (ได้ git pull ล่าสุดแล้วหรือยัง)" >&2
    exit 1
  fi
done

chmod +x "$BACKUP_SH" "$HEALTH_SH"

# เก็บ cron เดิมไว้ แล้วตัดเฉพาะบรรทัดที่เราเคยใส่ (กันซ้ำ)
CURRENT="$(crontab -l 2>/dev/null | grep -v "$MARK" || true)"

if [ "${1:-}" = "--remove" ]; then
  printf '%s\n' "$CURRENT" | crontab -
  echo "ถอนงานอัตโนมัติของ ddoc ออกจาก cron แล้ว"
  crontab -l | grep -E "ddoc|^\*|^0" || echo "(cron ว่าง)"
  exit 0
fi

NEW="$(cat <<EOF
$CURRENT
0 2 * * * $BACKUP_SH >> /var/log/ddoc-backup.log 2>&1 $MARK
*/15 * * * * $HEALTH_SH >> /var/log/ddoc-health.log 2>&1 $MARK
EOF
)"

printf '%s\n' "$NEW" | sed '/^$/d' | crontab -

echo "ติดตั้ง cron เรียบร้อย:"
echo "  - สำรองข้อมูล      ทุกวันตี 2      -> /var/log/ddoc-backup.log"
echo "  - ตรวจสุขภาพระบบ  ทุก 15 นาที    -> /var/log/ddoc-health.log"
echo ""
crontab -l | grep "$MARK"
echo ""
echo "ทดสอบเลยตอนนี้ (ไม่ต้องรอ cron):"
echo "  sudo $HEALTH_SH"
echo "  sudo $BACKUP_SH"
