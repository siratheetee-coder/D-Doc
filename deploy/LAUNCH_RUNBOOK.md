# คู่มือก่อนเปิดใช้จริง (Launch Runbook) — Easy Ekkasan

รวมขั้นตอนที่ **เจ้าของต้องทำบน VPS เอง** (โค้ด/คอนฟิกที่ทำได้ในระบบ ทำให้แล้ว)
ทุกคำสั่งรันบน VPS ในฐานะ root/sudo · โฟลเดอร์แอป = `/opt/ddoc`

> Deploy ปกติ: `cd /opt/ddoc && sudo -u ddoc git pull && sudo systemctl restart ddoc`
> ถ้าแก้ไฟล์ `deploy/ddoc.service` ต้อง `sudo systemctl daemon-reload` ก่อน restart

---

## 1) ตั้งค่า env จริง (`/etc/ddoc.env`)  ★ ต้องทำ

คัดลอกจากตัวอย่างถ้ายังไม่มี แล้วแก้ค่า:
```bash
sudo cp /opt/ddoc/deploy/ddoc.env.example /etc/ddoc.env   # ถ้ายังไม่มี
sudo nano /etc/ddoc.env
sudo chmod 600 /etc/ddoc.env    # กันคนอื่นอ่านรหัส
```
ค่าที่ **ต้อง** ตั้ง:
- `DDOC_SUPERADMIN_PW=` ← ตั้งรหัสยาว ๆ ของจริง (ห้ามใช้ `admin123`)
  - ระบบบังคับเปลี่ยนรหัสตอนล็อกอินครั้งแรกอยู่แล้ว แต่อย่าปล่อยค่า default
  - ถ้าเคยสร้าง superadmin ไปแล้วด้วยรหัส default ให้ล็อกอินเปลี่ยนรหัสทันที (ค่า env มีผลเฉพาะตอน "สร้างครั้งแรก")
- `DDOC_HTTPS=1` ← ตั้ง **หลังจากมีโดเมน + ใบรับรอง** (ดูข้อ 4) · ถ้ายังเข้าด้วย http/IP อยู่ให้คงเป็น `0` ก่อน ไม่งั้นคุกกี้ Secure จะทำให้ล็อกอินไม่ได้
- ตรวจ `DDOC_AUTO_BACKUP=1` + `BACKUP_S3_*` ให้เป็นชุดจริง (ใช้ชุดเดียวกับที่เคยตั้ง เพื่อให้กู้ข้อมูลอัตโนมัติตอนเปิดเครื่องครั้งแรก)

```bash
sudo systemctl restart ddoc
```

**ตรวจว่ามี superadmin อยู่แล้วหรือยัง** (สำคัญ: `DDOC_SUPERADMIN_PW` มีผลเฉพาะตอน "สร้างครั้งแรก")
ใช้ Python ของแอป (ไม่ต้องติดตั้ง sqlite3 CLI):
```bash
sudo -u ddoc /opt/ddoc/.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect('/opt/ddoc/data/accounts.db')
print(c.execute("SELECT username, role FROM account WHERE role='superadmin'").fetchall() or "ยังไม่มี superadmin")
PY
```
- **ยังไม่มี** → ตั้ง `DDOC_SUPERADMIN_PW` ใน env แล้ว restart จะสร้างให้ด้วยรหัสใหม่ (บังคับเปลี่ยนตอนล็อกอินครั้งแรก)
- **มีแล้ว** (เคย start ด้วย default) → env ไม่ช่วย ให้ล็อกอินเปลี่ยนรหัสที่ `/account/password` ทันที
- อยากรีเซ็ตด้วย env (ขั้นสูง): `stop` → ลบแถว superadmin → `start` (สร้างใหม่จาก env; ไม่กระทบบัญชีโรงเรียน)
  ```bash
  sudo systemctl stop ddoc
  sudo -u ddoc /opt/ddoc/.venv/bin/python -c "import sqlite3;d=sqlite3.connect('/opt/ddoc/data/accounts.db');d.execute(\"DELETE FROM account WHERE role='superadmin'\");d.commit()"
  sudo systemctl start ddoc
  ```

## 2) อัปเดต systemd ให้ rate-limit เห็น IP จริง  ★ ทำครั้งเดียว

ไฟล์ `deploy/ddoc.service` เพิ่ม `--proxy-headers --forwarded-allow-ips=127.0.0.1` แล้ว (มากับ git pull)
ติดตั้งทับของเดิม + reload:
```bash
sudo cp /opt/ddoc/deploy/ddoc.service /etc/systemd/system/ddoc.service
sudo systemctl daemon-reload
sudo systemctl restart ddoc
```
ตรวจว่า nginx ส่ง header ครบ (มีอยู่แล้วใน `deploy/nginx-ddoc.conf`: `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`).
**ทดสอบ:** ลองใส่รหัสผิดจากเครื่องนอก 8 ครั้งเร็ว ๆ ต้องโดนบล็อก 429 "พยายามเข้าระบบบ่อยเกินไป" (ถ้ายังไม่บล็อก แปลว่ายังนับรวมเป็น 127.0.0.1 — ตรวจ proxy-headers/nginx)

## 3) Backup อัตโนมัติ + ซ้อมกู้คืน  ★★ สำคัญสุด

**ติดตั้ง sqlite3 CLI ก่อน** (backup.sh ใช้ `sqlite3 .backup` ทำ snapshot ปลอดภัยขณะแอปเขียนอยู่ · ถ้าไม่มีจะ fallback เป็น cp ที่อาจได้ไฟล์ไม่สมบูรณ์):
```bash
sudo apt update && sudo apt install -y sqlite3
```

**ตั้ง cron สำรองรายคืน** (เก็บนอก `data/`):
```bash
sudo crontab -e
# เพิ่มบรรทัด (ตี 2 ทุกคืน):
0 2 * * * /opt/ddoc/deploy/backup.sh >> /var/log/ddoc-backup.log 2>&1
```
รันมือ 1 ครั้งเพื่อทดสอบ + ดูผล:
```bash
sudo /opt/ddoc/deploy/backup.sh
ls -lh /var/backups/ddoc/          # ต้องเห็นไฟล์ ddoc-backup-*.tar.gz
```

**ซ้อมกู้คืนจริง (drill) — ทำบนเครื่องทดสอบ/สำเนา ห้ามทำทับ production ครั้งแรก:**
```bash
# 1) หยุดแอป
sudo systemctl stop ddoc
# 2) สำรอง data ปัจจุบันไว้ก่อน (กันพลาด)
sudo mv /opt/ddoc/data /opt/ddoc/data.pre-drill
sudo mkdir /opt/ddoc/data
# 3) แตกไฟล์สำรองลง data
sudo tar -xzf /var/backups/ddoc/ddoc-backup-YYYYmmdd-HHMMSS.tar.gz -C /opt/ddoc/data
sudo chown -R ddoc:ddoc /opt/ddoc/data
# 4) เปิดแอป แล้วล็อกอินตรวจว่าข้อมูลครบ (โรงเรียน/นักเรียน/เอกสาร)
sudo systemctl start ddoc
# 5) ถ้าครบดี ลบสำเนาเดิม; ถ้าผิดให้สลับกลับ data.pre-drill
```
> กลไกกู้คืนระดับแอป (อัปโหลดไฟล์ .db ในหน้าตั้งค่า) ทดสอบ round-trip แล้วทำงานถูกต้อง — แต่ **การกู้จาก tar.gz บน VPS ต้องซ้อมเองอย่างน้อย 1 ครั้ง** ให้มั่นใจก่อนเปิดจริง

## 4) HTTPS (โดเมน + certbot) แล้วเปิด `DDOC_HTTPS=1`

```bash
# ตั้งโดเมนชี้มาที่ IP เครื่องก่อน จากนั้น:
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
# แก้ /etc/ddoc.env -> DDOC_HTTPS=1  แล้ว
sudo systemctl restart ddoc
```
ตรวจ: เข้า `https://your-domain.com` ได้ + ล็อกอินได้ (คุกกี้ Secure ทำงาน)

## 5) PDPA / นโยบายความเป็นส่วนตัว

หน้า `/privacy` เติมข้อมูลจริงแล้ว (ผู้ควบคุมข้อมูล ชื่อ/อีเมล/โทร, สิทธิเจ้าของข้อมูล, ระยะเก็บ 60 วัน ฯลฯ)
**เหลือ:** ให้ทนาย/ผู้เชี่ยวชาญ PDPA ตรวจข้อความก่อนเปิดจริง (เก็บข้อมูลนักเรียน = ข้อมูลอ่อนไหว) และทำ "ข้อตกลงประมวลผลข้อมูล (DPA)" กับโรงเรียนที่ใช้บริการ

## 6) ทดสอบจ่ายเงินจริง (end-to-end)  — เจ้าของทำ

สมัคร → เลือกแพ็กเกจ → จ่ายจริง (ยอดจริง) → ตรวจว่าโรงเรียนถูกเปิดสิทธิ์งานที่ซื้อ + ใบเสร็จ/สถานะถูกต้อง
(ผมทดสอบแทนไม่ได้ เพราะเป็นธุรกรรมเงินจริง)

---

## เช็กหลัง deploy ทุกครั้ง
```bash
sudo systemctl status ddoc --no-pager       # active (running)
curl -s http://127.0.0.1:8000/healthz        # {"ok":true}
sudo journalctl -u ddoc -n 50 --no-pager      # ไม่มี error แดง
```

## สถานะปัจจุบัน (ทำแล้วในโค้ด)
- ความปลอดภัย baseline ผ่าน + smoke test 29/29 ผ่าน
- proxy-headers ในไฟล์ service (ข้อ 2) — เพิ่มแล้ว รอ deploy
- backup.sh + restore ทดสอบ round-trip แล้ว
- /privacy เติมเนื้อหาจริงแล้ว (รอทนายตรวจ)
