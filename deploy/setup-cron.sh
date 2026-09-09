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
[ -f "$APP_DIR/deploy/restore.sh" ] && chmod +x "$APP_DIR/deploy/restore.sh"

# backup.sh เข้ารหัสไฟล์สำรองเสมอ ถ้ายังไม่มีกุญแจจะล้มเหลวทุกคืนแบบเงียบ ๆ
KEYFILE="${DDOC_BACKUP_KEYFILE:-/etc/ddoc-backup.key}"
if [ ! -f "$KEYFILE" ]; then
  echo "!! ยังไม่มีรหัสลับสำหรับเข้ารหัสไฟล์สำรอง ($KEYFILE)" >&2
  echo "   สร้างก่อนด้วย: sudo $BACKUP_SH --init" >&2
  echo "   (ติดตั้ง cron ต่อได้ แต่การสำรองจะยังไม่ทำงานจนกว่าจะสร้างกุญแจ)" >&2
  echo >&2
fi

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
30 3 * * * cd $APP_DIR && $APP_DIR/.venv/bin/python -m app.services.retention >> /var/log/ddoc-retention.log 2>&1 $MARK
EOF
)"

printf '%s\n' "$NEW" | sed '/^$/d' | crontab -

echo "ติดตั้ง cron เรียบร้อย:"
echo "  - สำรองข้อมูล      ทุกวันตี 2      -> /var/log/ddoc-backup.log"
echo "  - ตรวจสุขภาพระบบ  ทุก 15 นาที    -> /var/log/ddoc-health.log"
echo "  - ลบข้อมูลที่ไม่ใช้งาน ทุกวัน ตี 3:30 -> /var/log/ddoc-retention.log"
echo ""
crontab -l | grep "$MARK"
echo ""
echo "ทดสอบเลยตอนนี้ (ไม่ต้องรอ cron):"
echo "  sudo $HEALTH_SH"
echo "  sudo $BACKUP_SH"
echo ""
echo "ดูไฟล์สำรองที่กู้ได้:  sudo $APP_DIR/deploy/restore.sh --list"
echo "ดูว่าจะลบโรงเรียนไหนบ้าง (ไม่แตะข้อมูลจริง):"
echo "  cd $APP_DIR && $APP_DIR/.venv/bin/python -m app.services.retention --dry-run"
