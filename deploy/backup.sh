#!/usr/bin/env bash
# ============================================================================
# backup.sh - สำรองข้อมูล Easy Ekkasan (เข้ารหัส + ส่งออกนอกเครื่อง)
#
# ทำอะไรบ้าง
#   1) snapshot ฐานข้อมูลด้วย sqlite ".backup" (ข้อมูลครบแม้แอปกำลังเขียนอยู่)
#   2) รวมไฟล์แนบ (uploads) + secret.key
#   3) บีบเป็น .tar.gz แล้ว "เข้ารหัส AES-256" -> .tar.gz.enc
#   4) ส่งขึ้นคลาวด์ (S3/R2/B2) ถ้าตั้งค่าไว้  <-- กันเครื่องพังแล้วหายพร้อมกัน
#   5) เก็บเฉพาะ N ชุดล่าสุด ทั้งในเครื่องและบนคลาวด์
#
# ตั้งค่าครั้งแรก:
#   sudo /opt/ddoc/deploy/backup.sh --init      # สร้างรหัสลับสำหรับเข้ารหัส
#   sudo /opt/ddoc/deploy/setup-cron.sh         # ตั้งให้ทำทุกคืนตี 2
#
# กู้คืน:  sudo /opt/ddoc/deploy/restore.sh
#
# !! สำคัญ !! ไฟล์รหัสลับ /etc/ddoc-backup.key คือกุญแจเดียวที่เปิดไฟล์สำรองได้
#             ทำหาย = กู้ข้อมูลไม่ได้ตลอดกาล ให้ก๊อปเก็บนอกเครื่องด้วย
# ============================================================================
set -uo pipefail

APP_DIR="${DDOC_APP_DIR:-/opt/ddoc}"
DATA_DIR="$APP_DIR/data"
DEST="${DDOC_BACKUP_DIR:-/var/backups/ddoc}"    # ควรเป็นดิสก์/พาร์ทิชันอื่น หรือ mount ภายนอก
KEEP="${DDOC_BACKUP_KEEP:-14}"                  # เก็บกี่ชุดล่าสุด
KEYFILE="${DDOC_BACKUP_KEYFILE:-/etc/ddoc-backup.key}"
ENVFILE="${DDOC_ENV_FILE:-/etc/ddoc.env}"

# cron ไม่ได้อ่าน /etc/ddoc.env ให้เอง จึงต้องโหลดเองเพื่อให้ได้ค่า BACKUP_S3_*
if [ -f "$ENVFILE" ]; then
  set -a; . "$ENVFILE"; set +a
fi

log() { echo "[$(date '+%F %T')] $*"; }

# ---------------------------------------------------------------- --init ----
if [ "${1:-}" = "--init" ]; then
  if [ "$(id -u)" -ne 0 ]; then echo "ต้องรันด้วย sudo" >&2; exit 1; fi
  if [ -f "$KEYFILE" ]; then
    echo "มีรหัสลับอยู่แล้วที่ $KEYFILE (ไม่สร้างทับ กันไฟล์สำรองเก่าเปิดไม่ได้)"
  else
    umask 077
    openssl rand -base64 48 > "$KEYFILE"
    chmod 600 "$KEYFILE"
    echo "สร้างรหัสลับแล้ว: $KEYFILE"
  fi
  echo
  echo "=============================================================="
  echo " ก๊อปข้อความข้างล่างนี้เก็บไว้นอกเครื่องด้วย (เช่น โปรแกรมจัดการรหัสผ่าน)"
  echo " ถ้าเครื่องพังและไม่มีบรรทัดนี้ = เปิดไฟล์สำรองไม่ได้เลย"
  echo "=============================================================="
  cat "$KEYFILE"
  echo "=============================================================="
  exit 0
fi

# ------------------------------------------------------------ ตรวจก่อนทำ ----
if [ ! -d "$DATA_DIR" ]; then
  log "ไม่พบโฟลเดอร์ข้อมูล: $DATA_DIR" >&2
  exit 1
fi
if [ ! -f "$KEYFILE" ]; then
  log "ยังไม่มีรหัสลับสำหรับเข้ารหัส -> รัน: sudo $0 --init" >&2
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

# 4) บีบ + เข้ารหัส AES-256 (pbkdf2 200k รอบ) เก็บนอก data/
#    เข้ารหัสเพราะไฟล์สำรองมีข้อมูลนักเรียนทุกโรงเรียนรวมกัน ใครได้ไฟล์ไปต้องอ่านไม่ได้
OUT="$DEST/ddoc-backup-$TS.tar.gz.enc"
if ! tar -czf - -C "$STAGE" . \
     | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEYFILE" -out "$OUT"; then
  log "สำรองไม่สำเร็จ (บีบ/เข้ารหัสล้มเหลว)" >&2
  rm -f "$OUT"
  exit 1
fi
chmod 600 "$OUT"
SIZE="$(du -h "$OUT" | cut -f1)"
log "สำรอง + เข้ารหัสสำเร็จ -> $OUT ($SIZE)"

# 5) เก็บเฉพาะ KEEP ชุดล่าสุดในเครื่อง (ครอบคลุมไฟล์รูปแบบเก่าที่ยังไม่เข้ารหัสด้วย)
ls -1t "$DEST"/ddoc-backup-*.tar.gz.enc "$DEST"/ddoc-backup-*.tar.gz 2>/dev/null \
  | tail -n +"$((KEEP + 1))" | xargs -r rm -f

# ------------------------------------------------- 6) ส่งขึ้นคลาวด์ (off-site) ----
# ถ้าไม่ได้ตั้ง BACKUP_S3_BUCKET จะข้ามขั้นนี้ แต่เตือนไว้ เพราะสำรองในเครื่องเดียว
# ไม่ช่วยอะไรถ้าเครื่องหาย (โดนลบ/ดิสก์พัง/ผู้ให้บริการปิด)
if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  log "เตือน: ยังไม่ได้ตั้ง BACKUP_S3_* -> ไฟล์สำรองอยู่แต่ในเครื่องนี้เท่านั้น"
  exit 0
fi

PY="$APP_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  log "ไม่พบ python สำหรับอัปขึ้นคลาวด์ (ข้าม)" >&2
  exit 0
fi

# อัปคลาวด์ล้มเหลวต้องไม่ทำให้ทั้งงานถือว่าล้มเหลว (ไฟล์ในเครื่องสำรองสำเร็จไปแล้ว)
# cron จะได้ไม่ส่งอีเมล error ทุกคืนถ้าเน็ต/คลาวด์มีปัญหาชั่วคราว
if ! BACKUP_FILE="$OUT" BACKUP_KEEP="$KEEP" "$PY" - <<'PYEOF'
import os
import sys

path = os.environ["BACKUP_FILE"]
keep = int(os.environ.get("BACKUP_KEEP", "14"))
prefix = "ddoc-backups/"

try:
    import boto3
except ImportError:
    print("    ยังไม่ได้ติดตั้ง boto3 -> ข้ามการอัปขึ้นคลาวด์", file=sys.stderr)
    sys.exit(0)

try:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("BACKUP_S3_ENDPOINT") or None,
        aws_access_key_id=os.environ.get("BACKUP_S3_KEY_ID"),
        aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET"),
        region_name=os.environ.get("BACKUP_S3_REGION", "auto"),
    )
    bucket = os.environ["BACKUP_S3_BUCKET"]
    key = prefix + os.path.basename(path)
    client.upload_file(path, bucket, key)
    print(f"    อัปขึ้นคลาวด์แล้ว: {key} ({os.path.getsize(path) // 1024} KB)")

    # ตัดชุดเก่าบนคลาวด์ให้เหลือ keep ล่าสุด (ชื่อไฟล์มี timestamp จึงเรียงตามชื่อได้)
    objs = client.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    names = sorted((o["Key"] for o in objs if o["Key"].startswith(prefix + "ddoc-backup-")),
                   reverse=True)
    for old in names[keep:]:
        client.delete_object(Bucket=bucket, Key=old)
        print("    ลบชุดเก่าบนคลาวด์:", old)
except Exception as e:
    # อัปไม่ขึ้นต้องไม่ทำให้ทั้งงานล้มเหลว - ไฟล์ในเครื่องสำรองสำเร็จไปแล้ว
    print(f"    อัปขึ้นคลาวด์ไม่สำเร็จ: {e}", file=sys.stderr)
    sys.exit(0)
PYEOF
then
  log "เตือน: อัปขึ้นคลาวด์ไม่สำเร็จรอบนี้ (ไฟล์ในเครื่องสำรองแล้ว)"
fi
exit 0
