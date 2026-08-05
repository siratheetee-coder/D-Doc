#!/usr/bin/env bash
# ============================================================================
# backup.sh - สำรองข้อมูล Easy Ekkasan บน VPS (ทำงานแยกจากแอป เหมาะกับ cron)
#
# ใช้ sqlite ".backup" เพื่อ snapshot ที่สอดคล้อง แม้แอปกำลังเขียนอยู่ (WAL-safe)
# แล้วบีบเป็น .tar.gz เก็บไว้คนละที่กับ data/ (กันดิสก์เดียวพังแล้วหายหมด)
#
# ตั้ง cron (สำรองทุกคืนตี 2):
#   sudo crontab -e
#   0 2 * * * /opt/ddoc/deploy/backup.sh >> /var/log/ddoc-backup.log 2>&1
#
# กู้คืน:
#   systemctl stop ddoc
#   tar -xzf /var/backups/ddoc/ddoc-backup-YYYYmmdd-HHMMSS.tar.gz -C /opt/ddoc/data
#   chown -R ddoc:ddoc /opt/ddoc/data && systemctl start ddoc
# ============================================================================
set -euo pipefail

APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
DATA_DIR="$APP_DIR/data"
DEST="${DDOC_BACKUP_DIR:-/var/backups/ddoc}"   # ควรเป็นดิสก์/พาร์ทิชันอื่น หรือ mount ภายนอก
KEEP="${DDOC_BACKUP_KEEP:-14}"                  # เก็บกี่ชุดล่าสุด

if [ ! -d "$DATA_DIR" ]; then
  echo "ไม่พบโฟลเดอร์ข้อมูล: $DATA_DIR" >&2
  exit 1
fi

mkdir -p "$DEST"
TS="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# 1) snapshot ทุกไฟล์ .db ด้วย sqlite .backup (สอดคล้องแม้กำลังเขียน) - fallback เป็น cp
while IFS= read -r db; do
  rel="${db#"$DATA_DIR"/}"
  mkdir -p "$STAGE/$(dirname "$rel")"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db" ".backup '$STAGE/$rel'" 2>/dev/null || cp "$db" "$STAGE/$rel"
  else
    cp "$db" "$STAGE/$rel"
  fi
done < <(find "$DATA_DIR" -type f -name '*.db')

# 2) ไฟล์แนบ (uploads) - ข้อมูลจริงที่ generate ใหม่ไม่ได้
if [ -d "$DATA_DIR/uploads" ]; then
  cp -a "$DATA_DIR/uploads" "$STAGE/uploads"
fi

# 3) secret.key (คีย์เซ็น session) - ถ้าหายผู้ใช้จะถูกเด้งออกทั้งหมด
[ -f "$DATA_DIR/secret.key" ] && cp -a "$DATA_DIR/secret.key" "$STAGE/secret.key"

# 4) บีบ + เก็บนอก data/
OUT="$DEST/ddoc-backup-$TS.tar.gz"
tar -czf "$OUT" -C "$STAGE" .

# 5) เก็บเฉพาะ KEEP ชุดล่าสุด
ls -1t "$DEST"/ddoc-backup-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

echo "[$(date '+%F %T')] สำรองสำเร็จ -> $OUT ($(du -h "$OUT" | cut -f1))"
