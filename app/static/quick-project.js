/* quick-project.js - เพิ่มโครงการใหม่จากช่องเลือกโครงการ ไม่ต้องออกจากหน้าที่กรอกค้างอยู่
 *
 * <select name="project_id" data-quick-project data-plan-year="2570">
 * - เติมตัวเลือก "+ เพิ่มโครงการใหม่" ท้ายรายการ
 * - เลือกแล้วเปิดกล่องเล็ก (ชื่อโครงการ + งบ) กดเพิ่ม -> POST /finance/projects/quick -> เลือกโครงการใหม่ให้
 * - ส่ง change ต่อให้สคริปต์อื่นที่ฟังช่องนี้ (เช่น project_source.js) ทำงานกับโครงการใหม่ได้
 */
(function () {
  document.querySelectorAll('select[data-quick-project]').forEach(function (sel) {
    var NEW = '__new';
    var opt = document.createElement('option');
    opt.value = NEW; opt.textContent = '+ เพิ่มโครงการใหม่';
    sel.appendChild(opt);
    var prev = sel.value, box = null;

    function close() { if (box) { box.remove(); box = null; } }

    function open() {
      close();
      box = document.createElement('div');
      box.className = 'qp-box';
      box.innerHTML =
        '<div class="qp-title">เพิ่มโครงการใหม่ <span>เข้าแผนปี' + (sel.dataset.planYear ? ' ' + sel.dataset.planYear : 'ปัจจุบัน') + '</span></div>' +
        '<div class="qp-row"><input class="qp-name" placeholder="ชื่อโครงการ" autocomplete="off" aria-label="ชื่อโครงการ">' +
        '<input class="qp-budget" type="number" step="0.01" min="0" placeholder="งบที่ตั้งไว้ (บาท)" aria-label="งบที่ตั้งไว้"></div>' +
        '<div class="qp-row"><button type="button" class="btn sm qp-add" data-no-floating-save>เพิ่มโครงการ</button>' +
        '<button type="button" class="btn sm gray qp-cancel">ยกเลิก</button><span class="qp-msg"></span></div>' +
        '<div class="qp-hint">แก้รายละเอียดอื่น (ผู้รับผิดชอบ แหล่งเงิน) ได้ภายหลังที่หน้าโครงการ</div>';
      sel.parentElement.appendChild(box);
      var name = box.querySelector('.qp-name'), budget = box.querySelector('.qp-budget'),
          add = box.querySelector('.qp-add'), msg = box.querySelector('.qp-msg');
      name.focus();
      // Enter ในกล่องนี้ = เพิ่มโครงการ ไม่ใช่ส่งฟอร์มบันทึกรายการ
      [name, budget].forEach(function (el) {
        el.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add.click(); } });
      });
      box.querySelector('.qp-cancel').addEventListener('click', close);
      add.addEventListener('click', function () {
        var n = name.value.trim();
        if (!n) { msg.textContent = 'กรุณาพิมพ์ชื่อโครงการ'; name.focus(); return; }
        add.disabled = true; msg.textContent = 'กำลังเพิ่ม...';
        var fd = new FormData();
        fd.append('name', n); fd.append('budget', budget.value || '0');
        fd.append('plan_year', sel.dataset.planYear || '');
        fetch('/finance/projects/quick', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' } })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (res) {
            if (!res.ok) { throw new Error(res.d.detail || 'เพิ่มโครงการไม่สำเร็จ'); }
            var o = sel.querySelector('option[value="' + res.d.id + '"]');
            if (!o) {
              o = document.createElement('option');
              o.value = res.d.id; o.textContent = res.d.label;
              sel.insertBefore(o, sel.querySelector('option[value="' + NEW + '"]'));
            }
            sel.value = String(res.d.id); prev = sel.value;
            close();
            sel.dispatchEvent(new Event('change', { bubbles: true }));
          })
          .catch(function (e) { add.disabled = false; msg.textContent = e.message || 'เพิ่มโครงการไม่สำเร็จ'; });
      });
    }

    // capture: ทำงานก่อนสคริปต์อื่นที่ฟังช่องเดียวกัน จะได้ไม่มีใครเห็นค่า "__new"
    sel.addEventListener('change', function (e) {
      if (sel.value === NEW) {
        e.stopImmediatePropagation();
        sel.value = prev;
        open();
        return;
      }
      prev = sel.value;
    }, true);
  });
})();
