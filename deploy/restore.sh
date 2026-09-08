#!/usr/bin/env bash
# ============================================================================
# restore.sh - กู้คืนข้อมูล Easy Ekkasan จากไฟล์สำรองที่เข้ารหัสไว้
#
#   sudo /opt/ddoc/deploy/restore.sh                  # เลือกจากไฟล์ล่าสุดในเครื่อง
#   sudo /opt/ddoc/deploy/restore.sh <ไฟล์.tar.gz.enc>
#   sudo /opt/ddoc/deploy/restore.sh --from-cloud     # ดึงชุดล่าสุดจากคลาวด์มาก่อน
#   sudo /opt/ddoc/deploy/restore.sh --list           # ดูรายการที่กู้ได้ (ในเครื่อง + คลาวด์)
#
# ปลอดภัย: ย้าย data เดิมไปเก็บไว้เป็น data.before-restore-<เวลา> ก่อนเสมอ
#          ถ้ากู้แล้วข้อมูลไม่ถูก สลับกลับได้
# ============================================================================
set -uo pipefail

APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
DATA_DIR="$APP_DIR/data"
DEST="${DDOC_BACKUP_DIR:-/var/backups/ddoc}"
KEYFILE="${DDOC_BACKUP_KEYFILE:-/etc/ddoc-backup.key}"
ENVFILE="${DDOC_ENV_FILE:-/etc/ddoc.env}"
SERVICE="${DDOC_SERVICE:-ddoc}"

[ -f "$ENVFILE" ] && { set -a; . "$ENVFILE"; set +a; }

if [ "$(id -u)" -ne 0 ]; then echo "ต้องรันด้วย sudo: sudo $0" >&2; exit 1; fi

PY="$APP_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

cloud_list() {
  [ -n "${BACKUP_S3_BUCKET:-}" ] && [ -n "$PY" ] || return 0
  "$PY" - <<'PYEOF' 2>/dev/null
import os
try:
    import boto3
    c = boto3.client("s3", endpoint_url=os.environ.get("BACKUP_S3_ENDPOINT") or None,
                     aws_access_key_id=os.environ.get("BACKUP_S3_KEY_ID"),
                     aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET"),
                     region_name=os.environ.get("BACKUP_S3_REGION", "auto"))
    objs = c.list_objects_v2(Bucket=os.environ["BACKUP_S3_BUCKET"],
                             Prefix="ddoc-backups/").get("Contents", [])
    for o in sorted(objs, key=lambda x: x["Key"], reverse=True)[:20]:
        print(f"  {o['Key']}  ({o['Size'] // 1024} KB)")
except Exception as e:
    print("  (อ่านรายการบนคลาวด์ไม่ได้:", e, ")")
PYEOF
}

# ---------------------------------------------------------------- --list ----
if [ "${1:-}" = "--list" ]; then
  echo "ไฟล์สำรองในเครื่อง ($DEST):"
  ls -1t "$DEST"/ddoc-backup-* 2>/dev/null | head -20 | sed 's/^/  /' || echo "  (ไม่มี)"
  echo
  echo "ไฟล์สำรองบนคลาวด์:"
  cloud_list
  exit 0
fi

# ---------------------------------------------------------- เลือกไฟล์ที่จะกู้ ----
SRC=""
if [ "${1:-}" = "--from-cloud" ]; then
  [ -n "${BACKUP_S3_BUCKET:-}" ] || { echo "ยังไม่ได้ตั้ง BACKUP_S3_*" >&2; exit 1; }
  [ -n "$PY" ] || { echo "ไม่พบ python" >&2; exit 1; }
  mkdir -p "$DEST"
  SRC="$("$PY" - <<'PYEOF'
import os
import boto3
c = boto3.client("s3", endpoint_url=os.environ.get("BACKUP_S3_ENDPOINT") or None,
                 aws_access_key_id=os.environ.get("BACKUP_S3_KEY_ID"),
                 aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET"),
                 region_name=os.environ.get("BACKUP_S3_REGION", "auto"))
b = os.environ["BACKUP_S3_BUCKET"]
objs = c.list_objects_v2(Bucket=b, Prefix="ddoc-backups/ddoc-backup-").get("Contents", [])
if not objs:
    raise SystemExit("ไม่พบไฟล์สำรองบนคลาวด์")
key = sorted((o["Key"] for o in objs), reverse=True)[0]
dest = os.path.join(os.environ["DEST"], os.path.basename(key))
c.download_file(b, key, dest)
print(dest)
PYEOF
)" || { echo "ดึงไฟล์จากคลาวด์ไม่สำเร็จ" >&2; exit 1; }
  echo "ดึงจากคลาวด์แล้ว: $SRC"
elif [ -n "${1:-}" ]; then
  SRC="$1"
else
  SRC="$(ls -1t "$DEST"/ddoc-backup-*.tar.gz.enc "$DEST"/ddoc-backup-*.tar.gz 2>/dev/null | head -1)"
  [ -n "$SRC" ] || { echo "ไม่พบไฟล์สำรองใน $DEST (ดูทั้งหมด: $0 --list)" >&2; exit 1; }
  echo "ใช้ไฟล์ล่าสุด: $SRC"
fi
[ -f "$SRC" ] || { echo "ไม่พบไฟล์: $SRC" >&2; exit 1; }

echo
echo "จะกู้คืนข้อมูลทั้งระบบจากไฟล์นี้ ทับข้อมูลปัจจุบันของทุกโรงเรียน"
echo "  ไฟล์ : $SRC"
echo "  ขนาด : $(du -h "$SRC" | cut -f1)"
printf 'พิมพ์ "yes" เพื่อยืนยัน: '
read -r ans
[ "$ans" = "yes" ] || { echo "ยกเลิก"; exit 0; }

# ---------------------------------------------------------------- กู้คืน ----
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "-> แตกไฟล์..."
case "$SRC" in
  *.enc)
    [ -f "$KEYFILE" ] || { echo "ไม่พบรหัสลับ $KEYFILE (ไฟล์นี้เข้ารหัสไว้ เปิดไม่ได้)" >&2; exit 1; }
    if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEYFILE" -in "$SRC" \
         | tar -xzf - -C "$STAGE"; then
      echo "ถอดรหัส/แตกไฟล์ไม่สำเร็จ - รหัสลับอาจไม่ตรงกับไฟล์นี้ (ข้อมูลเดิมยังอยู่ครบ)" >&2
      exit 1
    fi ;;
  *) tar -xzf "$SRC" -C "$STAGE" || { echo "แตกไฟล์ไม่สำเร็จ" >&2; exit 1; } ;;
esac

# ต้องมีอย่างน้อย accounts.db ไม่งั้นแปลว่าไฟล์ผิด/เสีย - หยุดก่อนแตะข้อมูลจริง
if [ ! -f "$STAGE/accounts.db" ] && [ -z "$(find "$STAGE" -name '*.db' -print -quit)" ]; then
  echo "ไฟล์สำรองนี้ไม่มีฐานข้อมูลเลย ยกเลิกเพื่อความปลอดภัย" >&2
  exit 1
fi

echo "-> หยุดบริการ..."
systemctl stop "$SERVICE" 2>/dev/null || true

BAK="$DATA_DIR.before-restore-$(date +%Y%m%d-%H%M%S)"
if [ -d "$DATA_DIR" ]; then
  echo "-> เก็บข้อมูลปัจจุบันไว้ที่ $BAK"
  mv "$DATA_DIR" "$BAK"
fi
mkdir -p "$DATA_DIR"
cp -a "$STAGE"/. "$DATA_DIR"/
# เอกสารที่ generate ใหม่ได้ ไม่ได้อยู่ในไฟล์สำรอง - ระบบสร้างใหม่เองตอนดาวน์โหลด
chown -R ddoc:ddoc "$DATA_DIR" 2>/dev/null || true

echo "-> เปิดบริการ..."
systemctl start "$SERVICE" 2>/dev/null || true
sleep 2
systemctl is-active "$SERVICE" >/dev/null 2>&1 && echo "   บริการทำงานปกติ" || echo "   !! บริการยังไม่ขึ้น ตรวจ: journalctl -u $SERVICE -n 50"

echo
echo "กู้คืนเสร็จแล้ว"
echo "  ข้อมูลเดิมก่อนกู้ อยู่ที่ : $BAK"
echo "  ให้ล็อกอินตรวจว่าข้อมูลครบ (โรงเรียน/นักเรียน/เอกสาร) ก่อนลบโฟลเดอร์นั้น"
echo "  ถ้าข้อมูลไม่ถูก สลับกลับได้ด้วย:"
echo "    sudo systemctl stop $SERVICE && sudo rm -rf $DATA_DIR && sudo mv $BAK $DATA_DIR && sudo systemctl start $SERVICE"
