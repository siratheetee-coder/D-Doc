#!/usr/bin/env bash
# ===== ติดตั้ง D-Doc บน Ubuntu VPS (รันด้วย sudo) =====
# วิธีใช้:  sudo bash deploy/setup_vps.sh
# ก่อนรัน: ต้อง git clone โปรเจกต์ไว้ที่ /opt/ddoc และเตรียม /etc/ddoc.env แล้ว
set -e

APP_DIR=/opt/ddoc

echo "[1/6] ติดตั้งแพ็กเกจระบบ..."
apt update
apt install -y python3-venv python3-pip nginx git \
    tesseract-ocr tesseract-ocr-tha

echo "[2/6] สร้างผู้ใช้ ddoc + สิทธิ์โฟลเดอร์..."
id ddoc >/dev/null 2>&1 || useradd --system --home "$APP_DIR" ddoc
mkdir -p "$APP_DIR/data"
chown -R ddoc:ddoc "$APP_DIR"

echo "[3/6] สร้าง virtualenv + ติดตั้ง dependency..."
cd "$APP_DIR"
sudo -u ddoc python3 -m venv .venv
sudo -u ddoc .venv/bin/pip install --upgrade pip
sudo -u ddoc .venv/bin/pip install -r requirements.txt

echo "[4/6] ติดตั้ง systemd service..."
cp deploy/ddoc.service /etc/systemd/system/ddoc.service
systemctl daemon-reload
systemctl enable ddoc
systemctl restart ddoc

echo "[5/6] ตั้งค่า nginx..."
cp deploy/nginx-ddoc.conf /etc/nginx/sites-available/ddoc
ln -sf /etc/nginx/sites-available/ddoc /etc/nginx/sites-enabled/ddoc
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "[6/6] เปิด firewall..."
ufw allow OpenSSH || true
ufw allow 'Nginx Full' || true
ufw --force enable || true

echo ""
echo "เสร็จ! เปิดดู log การกู้ข้อมูลครั้งแรก:  journalctl -u ddoc -f"
echo "ควรเห็นบรรทัด [restore] กู้คืนข้อมูลจากคลาวด์: ... (ดึงข้อมูลจาก R2 มาให้)"
echo "เข้าเว็บ: http://<IP ของ VPS>/  (ถ้ามีโดเมน ทำ HTTPS ต่อด้วย: certbot --nginx)"
