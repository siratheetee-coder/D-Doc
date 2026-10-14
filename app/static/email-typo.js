/* email-typo.js - เตือนเมื่อพิมพ์โดเมนอีเมลผิดที่เจอบ่อย (เช่น @hmail.com, @gmial.com, @gmail.con)
 *
 * ใช้กับช่อง <input data-email-typo> (หน้าสมัคร / ขอใบเสนอราคา)
 * - พิมพ์เสร็จ (ออกจากช่อง) -> ถ้าโดเมนใกล้เคียงโดเมนยอดนิยมแต่ไม่ตรง ขึ้นว่า "หมายถึง ... ใช่ไหม"
 *   กด "ใช้อันนี้" แก้ให้ทันที / กด "อีเมลเดิมถูกแล้ว" ไม่ถามอีก
 * - กดส่งฟอร์มโดยยังไม่ได้เลือก -> หยุดไว้ก่อน ให้ตอบคำถามนี้ก่อน (อีเมลผิด = ไม่ได้รับอีเมลยืนยัน)
 * เหตุผล: 2026-10-14 พบครูสมัครด้วย @hmail.com แล้วไม่ได้รับอีเมลยืนยัน
 */
(function () {
  var POPULAR = ['gmail.com', 'hotmail.com', 'hotmail.co.th', 'outlook.com', 'outlook.co.th',
    'live.com', 'yahoo.com', 'yahoo.co.th', 'icloud.com', 'msn.com'];

  // ระยะแก้ไข (สลับตัวอักษรติดกันนับ 1) - พิมพ์ผิด 1-2 ตัว
  function dist(a, b) {
    var d = [], i, j;
    for (i = 0; i <= a.length; i++) { d[i] = [i]; }
    for (j = 0; j <= b.length; j++) { d[0][j] = j; }
    for (i = 1; i <= a.length; i++) {
      for (j = 1; j <= b.length; j++) {
        var c = a[i - 1] === b[j - 1] ? 0 : 1;
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c);
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
          d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
        }
      }
    }
    return d[a.length][b.length];
  }

  // คืนรายการอีเมลที่น่าจะตั้งใจพิมพ์ (มากสุด 2 ตัว) เช่น @hmail.com -> gmail / hotmail
  function suggest(email) {
    email = (email || '').trim().toLowerCase();
    var at = email.lastIndexOf('@');
    if (at < 1 || at === email.length - 1) { return null; }
    var local = email.slice(0, at), dom = email.slice(at + 1);
    if (POPULAR.indexOf(dom) >= 0) { return null; }
    if (dom.indexOf('.') < 0 && POPULAR.indexOf(dom + '.com') >= 0) { return [local + '@' + dom + '.com']; }
    var limit = dom.length <= 6 ? 1 : 2;      // โดเมนสั้นเกินไป ห้ามเดากว้าง (กันเดาผิดกับโดเมนโรงเรียน)
    var scored = POPULAR.map(function (p) { return [dist(dom, p), p]; })
      .filter(function (x) { return x[0] > 0 && x[0] <= limit; })
      .sort(function (a, b) { return a[0] - b[0]; });
    if (!scored.length) { return null; }
    var bestD = scored[0][0];
    return scored.filter(function (x) { return x[0] <= bestD + 1; }).slice(0, 2)
      .map(function (x) { return local + '@' + x[1]; });
  }
  window.emailTypoSuggest = suggest;           // ให้เทสต์เรียกตรวจได้

  function setup(input) {
    var box = document.createElement('div');
    box.className = 'etypo';
    box.hidden = true;
    box.setAttribute('role', 'alert');
    input.insertAdjacentElement('afterend', box);
    var okFor = '';                            // อีเมลที่ผู้ใช้ยืนยันว่าถูกแล้ว

    function check() {
      var s = suggest(input.value);
      if (!s || input.value.trim().toLowerCase() === okFor) { box.hidden = true; box.dataset.pending = ''; return null; }
      box.innerHTML = '';
      var t = document.createElement('span');
      t.textContent = 'อีเมลนี้อาจพิมพ์ผิด กดเลือกอีเมลที่ถูกต้อง:';
      box.appendChild(t);
      s.forEach(function (opt) {
        var use = document.createElement('button');
        use.type = 'button'; use.className = 'etypo-use'; use.textContent = opt;
        use.onclick = function () { input.value = opt; box.hidden = true; box.dataset.pending = ''; input.focus(); };
        box.appendChild(use);
      });
      var keep = document.createElement('button');
      keep.type = 'button'; keep.className = 'etypo-keep'; keep.textContent = 'อีเมลเดิมถูกแล้ว';
      keep.onclick = function () { okFor = input.value.trim().toLowerCase(); box.hidden = true; box.dataset.pending = ''; };
      box.appendChild(keep);
      box.hidden = false;
      box.dataset.pending = '1';
      return s;
    }
    input.addEventListener('blur', check);
    input.addEventListener('input', function () { if (!box.hidden) { check(); } });
    // ก่อนส่งฟอร์ม (capture = ทำงานก่อนตัวตรวจอื่นของหน้า เช่น ป๊อปอัปนโยบาย)
    if (input.form) {
      input.form.addEventListener('submit', function (e) {
        if (check()) {
          e.preventDefault();
          e.stopImmediatePropagation();
          box.classList.remove('etypo-shake'); void box.offsetWidth; box.classList.add('etypo-shake');
          box.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      }, true);
    }
  }

  var css = document.createElement('style');
  css.textContent =
    '.etypo{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:6px;padding:9px 12px;border-radius:10px;' +
    'font-size:14px;line-height:1.5;color:#92400e;background:linear-gradient(120deg,#fffbeb,#fef3c7);}' +
    '.etypo[hidden]{display:none;}' +
    '.etypo button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:8px;padding:5px 12px;cursor:pointer;}' +
    '.etypo-use{color:#fff;background:linear-gradient(120deg,#2563eb,#6366f1);}' +
    '.etypo-keep{color:#475569;background:#fff;}' +
    '@keyframes etypoShake{0%,100%{transform:none}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}' +
    '.etypo-shake{animation:etypoShake .3s 2;}';
  document.head.appendChild(css);
  document.querySelectorAll('input[data-email-typo]').forEach(setup);
})();
