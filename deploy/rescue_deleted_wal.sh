#!/usr/bin/env bash
# rescue_deleted_wal.sh - กู้ข้อมูลจากไฟล์ -wal ที่ถูกลบไปแล้วแต่แอปยังเปิดค้างอยู่
#
# อาการ: ls -l /proc/<pid>/fd มี ".../school.db-wal (deleted)" หรือ "accounts.db-wal (deleted)"
# ข้อมูลที่บันทึกหลังไฟล์ -wal ถูกลบ อยู่ในไฟล์ที่ถูกลบนั้นเท่านั้น รีสตาร์ทแอป = หายถาวร
#
# ขั้น 1 (ไม่หยุดอะไร ไม่แก้ data/):  sudo bash rescue_deleted_wal.sh copy
#    คัดลอก .db + -wal ที่ถูกลบ (ผ่าน /proc) ไปไว้ /root/ddoc-rescue-<เวลา>/ แล้วรวมเป็นไฟล์เดียว ตรวจ integrity
# ขั้น 2 (หยุดบริการชั่วคราว):          sudo bash rescue_deleted_wal.sh install /root/ddoc-rescue-<เวลา>
#    ใช้หลังจากรันขั้น 1 ซ้ำตอนปิด nginx แล้ว (ไม่มีการเขียนใหม่ระหว่างคัดลอก)
#    สำรองไฟล์เดิมไว้ที่ <ไฟล์>.before-rescue แล้ววางไฟล์ที่รวมแล้วแทน
set -euo pipefail
DATA=/opt/ddoc/data
MODE="${1:-}"

if [ "$MODE" = "copy" ]; then
  PIDS=$(pgrep -f "uvicorn app.main" || true)
  [ -n "$PIDS" ] || { echo "ไม่พบโปรเซสแอป"; exit 1; }
  OUT=/root/ddoc-rescue-$(date +%Y%m%d-%H%M%S)
  mkdir -p "$OUT"
  for PID in $PIDS; do
    for fd in /proc/$PID/fd/*; do
      t=$(readlink "$fd" 2>/dev/null) || continue
      case "$t" in
        *"-wal (deleted)")
          db="${t%-wal (deleted)}"
          rel="${db#$DATA/}"
          d="$OUT/$rel.d"
          mkdir -p "$d"
          ino=$(stat -L -c %i "$fd")
          [ -f "$d/wal.$ino" ] || cp "$fd" "$d/wal.$ino"
          ;;
      esac
    done
  done
  echo "โฟลเดอร์: $OUT"
  find "$OUT" -name '*.d' -type d | sort | while read -r d; do
    rel="${d#$OUT/}"; rel="${rel%.d}"
    n=$(ls "$d"/wal.* | wc -l)
    wal=$(ls -t "$d"/wal.* | head -1)          # มีหลายไฟล์ = ถูกลบหลายรอบ ใช้ไฟล์ล่าสุด
    mkdir -p "$d/merged"
    cp "$DATA/$rel" "$d/merged/db"
    cp "$wal" "$d/merged/db-wal"
    sqlite3 "$d/merged/db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
    sqlite3 "$d/merged/db" "PRAGMA integrity_check;" > "$d/merged/integrity.txt" || true
    chk=$(head -1 "$d/merged/integrity.txt")
    [ "$chk" = "ok" ] || chk="เสีย $(wc -l < "$d/merged/integrity.txt") บรรทัด ดู $d/merged/integrity.txt"
    note=""
    if [ "$n" -gt 1 ]; then note="  (มี -wal ถูกลบ $n รุ่น ใช้รุ่นล่าสุด)"; fi
    echo "$rel: wal $(stat -c %s "$wal") ไบต์ ตรวจ=$chk$note"
  done
  echo
  echo "ตรวจโรงเรียนที่หายไปในไฟล์บนดิสก์:"
  sqlite3 "$OUT/accounts.db.d/merged/db" "select id,name,plan from tenant order by id desc limit 8" 2>/dev/null || true
  exit 0
fi

if [ "$MODE" = "install" ]; then
  OUT="${2:?ระบุโฟลเดอร์จากขั้น copy}"
  if pgrep -f "uvicorn app.main" >/dev/null; then echo "หยุดบริการก่อน: systemctl stop ddoc"; exit 1; fi
  find "$OUT" -path '*.d/merged/db' | while read -r f; do
    rel="${f#$OUT/}"; rel="${rel%.d/merged/db}"
    ok=$(sqlite3 "$f" "PRAGMA integrity_check;" | head -1)
    [ "$ok" = "ok" ] || { echo "ข้าม $rel: integrity=$ok"; continue; }
    dst="$DATA/$rel"
    cp -p "$dst" "$dst.before-rescue"
    rm -f "$dst-wal" "$dst-shm"
    cp "$f" "$dst"
    chown ddoc:ddoc "$dst"
    echo "วางแล้ว: $rel"
  done
  exit 0
fi

echo "ใช้: $0 copy | $0 install <โฟลเดอร์>"
exit 2
