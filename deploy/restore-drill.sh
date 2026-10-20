#!/usr/bin/env bash
# ============================================================================
# restore-drill.sh - ซ้อมกู้ข้อมูลจากไฟล์สำรอง โดยไม่แตะข้อมูลจริง (ดูรายละเอียดใน app/services/restore_drill.py)
#
#   sudo /opt/ddoc/deploy/restore-drill.sh               # ไฟล์สำรองล่าสุด + อีเมลสรุปผล
#   sudo /opt/ddoc/deploy/restore-drill.sh <ไฟล์>
#   sudo /opt/ddoc/deploy/restore-drill.sh --no-email
#
# ปลอดภัย: แตกไฟล์ลงโฟลเดอร์ชั่วคราวใหม่ (ไม่ใช่ data/) · เปิดฐานข้อมูลจริงแบบอ่านอย่างเดียว
#          ไม่หยุดบริการ · ลบสำเนาชั่วคราวทุกครั้ง · รันแบบ nice ไม่แย่งเครื่องกับเว็บ
# ============================================================================
set -uo pipefail
APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
ENVFILE="${DDOC_ENV_FILE:-/etc/ddoc.env}"
[ -f "$ENVFILE" ] && { set -a; . "$ENVFILE"; set +a; }
if [ "$(id -u)" -ne 0 ]; then echo "ต้องรันด้วย sudo (อ่านรหัสลับไฟล์สำรองได้เฉพาะ root): sudo $0" >&2; exit 1; fi
PY="$APP_DIR/.venv/bin/python"
[ -x "$PY" ] || { echo "ไม่พบ python ของแอปที่ $PY" >&2; exit 2; }
cd "$APP_DIR" || exit 2
NICE=(nice -n 19)
command -v ionice >/dev/null 2>&1 && NICE+=(ionice -c3)
exec "${NICE[@]}" "$PY" -m app.services.restore_drill "$@"
