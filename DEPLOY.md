# คู่มือนำ D-Doc ขึ้นคลาวด์ (SaaS)

ระบบรันบนเซิร์ฟเวอร์ของผู้ขาย ลูกค้าเข้าใช้ผ่านเบราว์เซอร์ด้วยลิงก์ + รหัสผ่าน
ข้อมูลแต่ละโรงเรียนแยกเป็นไฟล์ DB ของตัวเองใน `data/schools/<id>/school.db`

## สิ่งที่ต้องเตรียม
- โดเมน (เช่น `app.dexample.com`) — ไม่บังคับแต่ควรมี
- คำสั่งรัน: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **พื้นที่เก็บข้อมูลถาวร (persistent disk)** ผูกกับโฟลเดอร์ `data/` — สำคัญมาก ไม่งั้นข้อมูลหายเมื่อ redeploy
- ตัวแปรสภาพแวดล้อม (env):
  - `DDOC_HTTPS=1` (บังคับคุกกี้ Secure เมื่อใช้ HTTPS)
  - `DDOC_SUPERADMIN`, `DDOC_SUPERADMIN_PW` (ตั้งรหัสผู้ดูแลระบบครั้งแรก — อย่าใช้ค่า default)

---

## ตัวเลือก A — Render (แนะนำ) — มีไฟล์ Blueprint ให้แล้ว (กดทีเดียวจบ)
มีไฟล์ [render.yaml](render.yaml) เตรียมไว้: web service แผน **starter** + **persistent disk 1 GB ที่ `data/`** + env ครบ
1. push โค้ดขึ้น GitHub (ไฟล์ `data/` ไม่ถูก commit เพราะอยู่ใน .gitignore แล้ว)
2. Render -> **New -> Blueprint** -> เชื่อม repo นี้ -> **Apply** (Render อ่าน render.yaml เอง)
3. ไปที่ **Environment** ของ service กรอกค่าที่ตั้ง `sync: false`:
   - `DDOC_SUPERADMIN`, `DDOC_SUPERADMIN_PW` (ชื่อ/รหัสผู้ดูแลระบบของคุณ)
   - (ไว้ทำทีหลัง) `BACKUP_S3_*` สำหรับสำรองขึ้นคลาวด์
4. Render ออก HTTPS + โดเมนให้อัตโนมัติ · มี health check ที่ `/healthz`
5. เปิด `https://<โดเมน>/login` -> ล็อกอิน superadmin -> `/admin-console` -> สร้างโรงเรียน

> หมายเหตุ: แผน **starter เสียเงิน** เท่านั้นจึงต่อ persistent disk ได้ (ฟรีไม่ได้ -> ข้อมูลหาย)
> Railway/Fly.io ใช้หลักเดียวกัน: Start Command + persistent volume ที่ `data/` + env

---

## ตัวเลือก B — VPS (ยืดหยุ่น/ถูกระยะยาว): Ubuntu
```bash
sudo apt update && sudo apt install -y python3-venv nginx
git clone <repo> /opt/ddoc && cd /opt/ddoc
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# ทดสอบรัน
DDOC_HTTPS=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```
- ทำ systemd service ให้รันอัตโนมัติ + ตั้ง env (`DDOC_HTTPS`, `DDOC_SUPERADMIN*`)
- nginx เป็น reverse proxy ส่งต่อ -> 127.0.0.1:8000 และต้องส่ง header `Host` ตามจริง
- ออก TLS ฟรีด้วย Let's Encrypt (`certbot --nginx`)
- โฟลเดอร์ `data/` อยู่ในดิสก์ของเครื่อง (สำรองสม่ำเสมอ)

ตัวอย่าง nginx (ย่อ):
```
server {
  server_name app.example.com;
  location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
}
```

---

## สำรองข้อมูลอัตโนมัติ (สำคัญที่สุด — กันข้อมูลหาย)
สำรอง `data/` ทั้งหมด (ทุกโรงเรียน + บัญชีผู้ใช้) เป็น zip รายวัน เก็บย้อนหลัง 14 ชุด
- **บน Render:** เปิดในตัวแอปแล้วผ่าน env `DDOC_AUTO_BACKUP=1` (ตั้งไว้ใน render.yaml) — ไม่ต้องตั้ง cron
- **บน VPS:** ใช้ [tools/backup_all.py](tools/backup_all.py) + cron (ตี 2 ทุกวัน):
```
0 2 * * *  cd /opt/ddoc && /opt/ddoc/.venv/bin/python tools/backup_all.py >> data/backups/backup.log 2>&1
```

### อัปสำรองขึ้นคลาวด์อีกที่ (off-site) — เกราะกันข้อมูลหายชั้นที่ 2 ⭐
ต่อให้เซิร์ฟเวอร์พังทั้งเครื่อง ก็ยังกู้คืนได้ ใช้ที่เก็บแบบ S3 เจ้าไหนก็ได้ (ราคาถูก/มีฟรีทีเออร์):
- **Cloudflare R2** (แนะนำ — ฟรี 10 GB, ไม่มีค่า egress) หรือ **Backblaze B2** (ฟรี 10 GB)
ขั้นตอน:
1. สมัคร R2/B2 -> สร้าง bucket -> สร้าง API key (Access Key ID + Secret)
2. ติดตั้งบนเซิร์ฟเวอร์: `pip install boto3`
3. ตั้ง env (ค่าเหล่านี้):
```
BACKUP_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com   # R2
BACKUP_S3_BUCKET=ddoc-backups
BACKUP_S3_KEY_ID=<access key id>
BACKUP_S3_SECRET=<secret>
BACKUP_S3_REGION=auto
```
4. cron เดิมจะอัป zip ขึ้นคลาวด์ให้อัตโนมัติทุกวัน (และลบของเก่าให้เหลือ 14 ชุด)
> ถ้าไม่ตั้ง env เหล่านี้ สคริปต์จะสำรองแค่ในเครื่อง (ข้ามการอัป) ไม่ error

---

## หลังติดตั้งครั้งแรก — ต้องทำทันที
1. ล็อกอิน superadmin -> **เปลี่ยนรหัสผ่าน** (อย่าใช้ค่า default `admin/admin123`)
2. โรงเรียนแรก (ย้ายจากข้อมูลเดิม) ผู้ใช้ `school/school123` -> **เปลี่ยนรหัสผ่าน** ผ่าน `/admin-console` (รีเซ็ตรหัส)
3. ตรวจว่า `data/` ผูกกับ persistent disk แล้วจริง (ทดสอบ redeploy แล้วข้อมูลยังอยู่)
4. ตรวจว่าเปิดผ่าน **https** ได้ และคุกกี้เป็น Secure

## การขายจริง (workflow)
- ลูกค้าใหม่ -> superadmin สร้างโรงเรียน + ผู้ใช้ -> ส่งลิงก์ + รหัสให้ลูกค้า
- ต่ออายุ/ระงับ: ตั้ง "วันหมดอายุ" หรือกด "ระงับ" ใน `/admin-console` (มีผลทันที)
- จำกัดจำนวนผู้ใช้ต่อโรงเรียนได้ (เช่น 3 ฝ่าย) ตอนสร้าง
