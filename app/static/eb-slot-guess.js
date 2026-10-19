/* eb-slot-guess.js - ฟอร์มสร้างบัญชี/หมวด: พิมพ์ชื่อแล้วเลือกช่อง e-Budget ที่ระบบเดาไว้ให้ก่อน
 *
 * <select data-eb-guess data-name-input="#accName" [data-account-id="12"]> + <div class="eb-guess-hint">
 * - เดาได้   -> เลือกให้ (ถ้าผู้ใช้ยังไม่ได้เลือกเอง) และบอกว่า "ระบบเลือกให้จากชื่อ"
 * - เดาไม่ได้ -> บอกให้เลือกเอง (เงินจะไม่ไปกองที่ "อื่น ๆ" โดยไม่รู้ตัว)
 */
(function () {
  document.querySelectorAll('select[data-eb-guess]').forEach(function (sel) {
    var input = document.querySelector(sel.dataset.nameInput);
    var hint = sel.parentElement.querySelector('.eb-guess-hint');
    if (!input) return;
    var timer = null, touched = false;
    sel.addEventListener('change', function () { touched = true; if (hint) hint.textContent = ''; });
    function guess() {
      var name = input.value.trim();
      if (!name) { if (hint) hint.textContent = ''; return; }
      var q = '/finance/ebudget/guess?name=' + encodeURIComponent(name) +
              (sel.dataset.accountId ? '&account_id=' + sel.dataset.accountId : '');
      fetch(q, { headers: { 'X-Requested-With': 'fetch' } }).then(function (r) { return r.json(); }).then(function (g) {
        if (touched) return;
        if (g.other) {
          sel.value = '';                      // ล้างค่าที่ระบบเดาไว้รอบก่อน (ผู้ใช้ยังไม่ได้เลือกเอง)
          if (hint) hint.textContent = 'ระบบดูจากชื่อแล้วบอกไม่ได้ว่าลงช่องไหน กรุณาเลือกเอง';
        } else {
          sel.value = g.slot;
          if (hint) hint.textContent = 'ระบบเลือกให้จากชื่อ ตรวจแล้วเปลี่ยนได้';
        }
      }).catch(function () {});
    }
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(guess, 300); });
  });
})();
