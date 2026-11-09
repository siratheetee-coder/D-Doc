/* stay-form.js - ฟอร์มที่ติด data-stay บันทึกเบื้องหลัง ไม่รีโหลดทั้งหน้า
 * ใช้กับการแก้ค่าเล็ก ๆ ในแถวตาราง (เลือกหมวด เปิด/ปิด ย้ายปี) ที่รีโหลดแล้วเสียตำแหน่งและเสียเวลา
 *
 * <tr id="acc-5"> ... <form method="post" data-stay> ... </form>
 *   ส่งฟอร์มด้วย fetch (ตาม redirect ของเซิร์ฟเวอร์ตามเดิม) แล้วเอาแถวที่ id เดียวกันจากหน้าใหม่มาแทน
 *   ถ้าหน้าใหม่ไม่มีแถวนั้นแล้ว (เช่น ย้ายไปปีอื่น/ลบ) เอาแถวออก
 *   ปลายทางมี ?err= = แจ้งข้อความ ไม่เปลี่ยนอะไร
 * data-stay="#sel" ระบุกล่องที่จะแทนเอง (ไม่ระบุ = แถว/กล่องที่ใกล้ที่สุดที่มี id)
 * ทำงานไม่ได้ (เบราว์เซอร์เก่า/เน็ตหลุด) ส่งฟอร์มแบบเดิม
 */
(function () {
  if (!window.fetch || !window.DOMParser) return;

  function toast(msg) {
    if (window.showToast) { window.showToast(msg); return; }
    var t = document.createElement('div');
    t.className = 'stay-toast'; t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add('out'); }, 1400);
    setTimeout(function () { t.remove(); }, 1800);
  }

  function errOf(url) {
    try { return new URL(url).searchParams.get('err') || ''; } catch (e) { return ''; }
  }

  function submit(form) {
    var sel = form.getAttribute('data-stay');
    var box = sel ? document.querySelector(sel) : form.closest('[id]');
    if (!box || !box.id) { window.__staySubmitNative(form); return; }
    if (form.dataset.busy) return;
    form.dataset.busy = '1';
    box.classList.add('stay-busy');
    var body = new FormData(form);
    fetch(form.action || location.href, { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (r) {
        return r.text().then(function (html) { return { r: r, html: html }; });
      })
      .then(function (x) {
        var err = errOf(x.r.url);
        if (!x.r.ok || err) throw new Error(err || 'บันทึกไม่สำเร็จ ลองใหม่');
        var doc = new DOMParser().parseFromString(x.html, 'text/html');
        var fresh = doc.getElementById(box.id);
        if (fresh) {
          box.replaceWith(fresh);
          fresh.classList.add('stay-done');
          setTimeout(function () { fresh.classList.remove('stay-done'); }, 900);
          document.dispatchEvent(new CustomEvent('stay:updated', { detail: fresh }));
        } else {
          box.classList.add('stay-gone');
          setTimeout(function () { box.remove(); }, 260);
        }
        toast(form.getAttribute('data-stay-msg') || 'บันทึกแล้ว');
      })
      .catch(function (e) {
        box.classList.remove('stay-busy');
        delete form.dataset.busy;
        alert(e.message || 'บันทึกไม่สำเร็จ ลองใหม่');
      });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[data-stay]')) return;
    e.preventDefault();
    submit(form);
  });

  // onchange="this.form.submit()" เรียก submit() ตรง ไม่ผ่าน event submit จึงดักที่นี่
  var native = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    if (this.hasAttribute('data-stay') && !this.dataset.stayNative) { submit(this); return; }
    return native.call(this);
  };
  // ส่งแบบเดิมเมื่อหาแถวไม่เจอ
  var fallback = function (f) { f.dataset.stayNative = '1'; native.call(f); };
  window.__staySubmitNative = fallback;
})();
