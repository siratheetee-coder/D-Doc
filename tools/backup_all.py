# -*- coding: utf-8 -*-
"""
backup_all.py — สำรองข้อมูลทุกโรงเรียน (สำหรับตั้ง cron บน VPS)

เป็นตัวห่อบาง ๆ ของ app/services/backup.py (logic เดียวกับที่แอปใช้สำรองอัตโนมัติ)
ตั้งค่าอัปขึ้นคลาวด์ผ่าน env: BACKUP_S3_ENDPOINT/BUCKET/KEY_ID/SECRET/REGION (ดู DEPLOY.md)

ใช้:        python tools/backup_all.py
cron (ตี 2): 0 2 * * *  cd /opt/ddoc && /opt/ddoc/.venv/bin/python tools/backup_all.py >> data/backups/backup.log 2>&1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.backup import run_backup

if __name__ == "__main__":
    sys.exit(0 if run_backup() else 1)
