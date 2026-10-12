# หน้าแจ้งระบบไม่พร้อมใช้งาน

หน้า HTML โลโก้ และฟอนต์ให้ Nginx อ่านจาก `/var/www/ddoc-errors` โดยตรง
ไม่เรียกแอปหรือ CDN จึงแสดงได้ขณะ ddoc หยุด/รีสตาร์ท
รองรับ 502, 503, 504 และตอบสถานะ 503 พร้อม Retry-After 120 วินาที ไม่ cache หน้าขัดข้อง

## VPS เดิม: ติดตั้งครั้งแรก

```bash
cd /opt/ddoc
sudo -u ddoc git pull
sudo bash deploy/install-error-pages.sh
sudo cp -a /etc/nginx/sites-available/ddoc /etc/nginx/sites-available/ddoc.before-error-page
sudo nano /etc/nginx/sites-available/ddoc
```

เพิ่มบรรทัดต่อไปนี้ **ภายใน `server { ... }` ที่ให้บริการแอป** แต่ให้อยู่นอก `location { ... }`:

```nginx
include /etc/nginx/snippets/ddoc-error-pages.conf;
```

ถ้าใช้ HTTPS ให้ใส่ใน server ที่มี `listen 443 ssl` และ proxy ไปแอปด้วย
ไม่ต้องใส่ซ้ำถ้ามีอยู่แล้ว หากไฟล์จริงชื่ออื่นให้แก้ไฟล์ที่เปิดใช้งานจริง
ห้ามคัดลอก nginx-ddoc.conf ทับไฟล์จริง เพราะอาจทำให้โดเมนและ SSL เดิมหาย
หาก location ของแอปตั้ง `proxy_intercept_errors off` หรือ `error_page` ไว้เอง ให้ตรวจการ override ก่อน

```bash
sudo nginx -t && sudo systemctl reload nginx
```

ขั้นตอนนี้ไม่ต้องหยุดแอป ติดตั้งใหม่ด้วย setup_vps.sh จะติดตั้งหน้าและ include ให้แล้ว
การ git pull และ restart ddoc เพียงอย่างเดียว **ไม่เปิดใช้** หน้าใหม่ใน Nginx เดิม

## ตรวจและย้อนกลับ

หลัง `nginx -t` ผ่าน ตรวจเว็บไซต์ปกติยังเข้าได้ ทดสอบหน้า 503 ในช่วงรีสตาร์ทที่วางแผนไว้
โดยไม่หยุดระบบเพิ่มเพื่อทดสอบ ระหว่าง upstream ไม่พร้อม การเปิดหน้าเดิมควรเห็นหน้าแจ้งเตือน
ตรวจ Network ว่า status เป็น 503 และโหลดโลโก้/ฟอนต์ได้ หลังแอปกลับมา ปุ่มลองอีกครั้งควรเปิดหน้าได้
ไม่ใช้การเรียก `/_ddoc-unavailable.html` ตรง ๆ เป็นตัวทดสอบ เพราะเป็น internal location และต้องได้ 404

หากตั้งค่าผิดและ nginx -t ไม่ผ่าน ให้แก้/นำ include ที่เพิ่งเพิ่มออกก่อน reload
หรือคืนไฟล์สำรองที่สร้างไว้ แล้วทดสอบและ reload อีกครั้ง
อัปเดตดีไซน์ในอนาคตให้รัน install-error-pages.sh อีกครั้งหลัง pull

ปุ่มลองอีกครั้งเปิด URL เดิมแบบ GET ไม่ส่งฟอร์ม POST ซ้ำอัตโนมัติ
ถ้า URL เดิมเป็นจุดบันทึกที่ไม่รับ GET ให้ใช้ปุ่มกลับหน้าหลักและตรวจรายการล่าสุดก่อนทำต่อ
ข้อความไม่ยืนยันว่ากำลังอัปเดตเสมอ เพราะ gateway error อาจเกิดจากระบบขัดข้องอื่นได้

อ้างอิง: https://nginx.org/en/docs/http/ngx_http_core_module.html#error_page
และ https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_intercept_errors
