/* quick-project.js - เพิ่มโครงการใหม่จากช่องเลือกโครงการ เป็น pop-up การ์ด (ไม่ต้องออกจากหน้าที่กรอกค้างอยู่)
 *
 * <select name="project_id" data-quick-project>
 * - เติมตัวเลือก "+ เพิ่มโครงการใหม่" ท้ายรายการ
 * - เลือกแล้วเปิดการ์ด: ชื่อ งบ ฝ่าย ปีแผน + "ใช้งบจากรายการใดในแผน" (ดึงจากหน้างบที่ใช้จัดทำแผน)
 *   GET /finance/projects/quick-form?year=  ->  POST /finance/projects/quick
 * - บันทึกแล้วเลือกโครงการใหม่ให้ และส่ง change ต่อให้สคริปต์อื่นที่ฟังช่องนี้ (เช่น project_source.js)
 */
(function () {
  var sels = document.querySelectorAll('select[data-quick-project]');
  if (!sels.length) return;
  var NEW = '__new';
  var CSS =
    '.qp-ov{position:fixed;inset:0;z-index:1000;background:rgba(15,23,42,.45);display:flex;align-items:flex-start;justify-content:center;padding:6vh 16px;overflow-y:auto}' +
    '.qp-card{width:100%;max-width:640px;background:#fff;border-radius:18px;box-shadow:0 24px 60px rgba(15,23,42,.28);overflow:hidden}' +
    '.qp-head{padding:16px 20px;color:#fff;background:linear-gradient(120deg,#4f46e5,#7c3aed);display:flex;justify-content:space-between;align-items:center;gap:10px}' +
    '.qp-head h3{margin:0;font-size:19px}.qp-x{border:0;background:rgba(255,255,255,.18);color:#fff;border-radius:10px;width:34px;height:34px;font-size:20px;cursor:pointer;line-height:1}' +
    '.qp-body{padding:16px 20px 6px}.qp-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 14px}.qp-grid .qp-full{grid-column:1/-1}' +
    '.qp-grid label{display:block;font-weight:600;font-size:14px;margin-bottom:4px;white-space:nowrap}.qp-grid input,.qp-grid select{width:100%}' +
    '.qp-sec{margin:16px 0 4px;padding:12px 14px;border-radius:14px;background:linear-gradient(120deg,#eef2ff,#f5f3ff)}' +
    '.qp-sec h4{margin:0 0 4px;font-size:15px}.qp-sec p{margin:0 0 8px;font-size:13px;color:#64748b}' +
    '.qp-src{display:grid;grid-template-columns:1fr 150px;gap:8px;align-items:center;padding:6px 0}' +
    '.qp-src b{font-weight:600;font-size:14px;display:block}.qp-src small{color:#64748b;font-size:12.5px}.qp-src input{text-align:right}' +
    '.qp-sum{font-size:13.5px;margin-top:6px}.qp-sum.over{color:#b91c1c;font-weight:600}' +
    '.qp-foot{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 20px 18px}.qp-msg{flex:1;min-width:160px;font-size:13.5px;color:#b91c1c}' +
    '.qp-links{font-size:13px;margin-top:8px}.qp-links a{margin-right:12px}' +
    '@media(max-width:560px){.qp-grid{grid-template-columns:1fr}.qp-src{grid-template-columns:1fr 120px}.qp-ov{padding:12px 10px}}';
  var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);

  function esc(t) {
    return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function money(n) { return (Math.round(n * 100) / 100).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function num(v) { var n = parseFloat(String(v || '').replace(/,/g, '')); return isFinite(n) && n > 0 ? n : 0; }

  function openCard(sel, onDone) {
    var lastFocus = document.activeElement;
    var ov = document.createElement('div');
    ov.className = 'qp-ov';
    ov.innerHTML =
      '<div class="qp-card" role="dialog" aria-modal="true" aria-labelledby="qpTitle">' +
      '<div class="qp-head"><h3 id="qpTitle">เพิ่มโครงการใหม่</h3><button type="button" class="qp-x" aria-label="ปิด">&times;</button></div>' +
      '<div class="qp-body">' +
      '<div class="qp-grid">' +
      '<div class="qp-full"><label for="qpName">ชื่อโครงการ *</label><input id="qpName" autocomplete="off" placeholder="เช่น โครงการวันสำคัญทางวิชาการ"></div>' +
      '<div><label for="qpBudget">งบที่ตั้งไว้ (บาท)</label><input id="qpBudget" type="number" step="0.01" min="0" value="0"></div>' +
      '<div><label for="qpYear" id="qpYearLab">ปีแผน</label><select id="qpYear"></select></div>' +
      '<div class="qp-full"><label for="qpResp">ฝ่าย/ผู้รับผิดชอบ</label><select id="qpResp"><option value="">- เลือกฝ่าย -</option></select></div>' +
      '</div>' +
      '<div class="qp-sec"><h4>ใช้งบจากรายการใดในแผน</h4><div id="qpSrc"><p>กำลังโหลด...</p></div></div>' +
      '<div class="qp-links"><a id="qpPlanLink" target="_blank" rel="noopener">เปิดหน้างบที่ใช้จัดทำแผน</a>' +
      '<a href="/masters" target="_blank" rel="noopener">เพิ่มฝ่าย</a></div>' +
      '</div>' +
      '<div class="qp-foot"><span class="qp-msg" role="alert"></span>' +
      '<button type="button" class="btn gray qp-cancel">ยกเลิก</button>' +
      '<button type="button" class="btn qp-save" data-no-floating-save>บันทึกโครงการ</button></div>' +
      '</div>';
    document.body.appendChild(ov);
    var $ = function (s) { return ov.querySelector(s); };
    var name = $('#qpName'), budget = $('#qpBudget'), year = $('#qpYear'), resp = $('#qpResp'),
        src = $('#qpSrc'), msg = $('.qp-msg'), save = $('.qp-save'), planLink = $('#qpPlanLink');

    function close() {
      document.removeEventListener('keydown', onKey, true);
      ov.remove();
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); save.click(); }
    }
    document.addEventListener('keydown', onKey, true);
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
    $('.qp-x').addEventListener('click', close);
    $('.qp-cancel').addEventListener('click', close);

    function sum() {
      var tot = 0, over = false;
      src.querySelectorAll('input[data-fund]').forEach(function (i) {
        var v = num(i.value); tot += v;
        if (v > parseFloat(i.max) + 0.001) over = true;
      });
      var b = num(budget.value), el = src.querySelector('.qp-sum');
      if (!el) return;
      var tooMuch = tot > b + 0.001;
      el.className = 'qp-sum' + (tooMuch || over ? ' over' : '');
      el.textContent = 'ระบุที่มาของงบแล้ว ' + money(tot) + ' จากงบโครงการ ' + money(b) + ' บาท' +
        (tooMuch ? ' (เกินงบโครงการ)' : over ? ' (เกินเงินที่เหลือให้จัดสรร)' : '');
    }
    budget.addEventListener('input', sum);

    function load(y) {
      src.innerHTML = '<p>กำลังโหลด...</p>';
      fetch('/finance/projects/quick-form' + (y ? '?year=' + encodeURIComponent(y) : ''), { headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          $('#qpYearLab').textContent = (d.year_label || 'ปี') + ' (ปีแผน)';
          if (!year.options.length) {
            year.innerHTML = d.years.map(function (v) { return '<option value="' + v + '"' + (v === d.plan_year ? ' selected' : '') + '>' + v + '</option>'; }).join('');
            resp.innerHTML = '<option value="">- เลือกฝ่าย -</option>' + d.departments.map(function (n) { return '<option>' + esc(n) + '</option>'; }).join('');
          }
          planLink.href = d.plan_link;
          planLink.textContent = 'เปิดหน้างบที่ใช้จัดทำแผน ' + d.plan_year;
          if (!d.has_plan) {
            src.innerHTML = '<p>ยังไม่ได้กำหนดงบที่ใช้จัดทำแผน ปี ' + d.plan_year + ' บันทึกโครงการได้เลย แล้วค่อยจัดสรรงบทีหลังที่หน้าโครงการ</p>';
          } else if (!d.sources.length) {
            src.innerHTML = '<p>แผนงบปี ' + d.plan_year + ' ไม่มีเงินที่ยังเหลือให้จัดสรร บันทึกโครงการได้เลย หรือนำเงินเข้าแผนเพิ่มที่หน้างบที่ใช้จัดทำแผน</p>';
          } else {
            src.innerHTML = '<p>กรอกส่วนที่จัดสรรให้โครงการนี้ (เว้นว่างได้ จัดสรรทีหลังที่หน้าโครงการ)</p>' +
              d.sources.map(function (s) {
                return '<div class="qp-src"><div><b>' + esc(s.name) + '</b><small>' + esc(s.kind) + ' เหลือให้จัดสรร ' + money(s.available) + '</small></div>' +
                  '<input type="number" min="0" step="0.01" max="' + s.available + '" data-fund="' + s.id + '" placeholder="0.00" aria-label="จัดสรรจาก ' + esc(s.name) + '"></div>';
              }).join('') + '<div class="qp-sum"></div>';
            src.querySelectorAll('input[data-fund]').forEach(function (i) { i.addEventListener('input', sum); });
            sum();
          }
        })
        .catch(function () { src.innerHTML = '<p>โหลดรายการงบไม่สำเร็จ แต่บันทึกโครงการได้ แล้วจัดสรรงบทีหลังที่หน้าโครงการ</p>'; });
    }
    year.addEventListener('change', function () { load(year.value); });
    load('');
    name.focus();

    save.addEventListener('click', function () {
      var n = name.value.trim();
      if (!n) { msg.textContent = 'กรุณาพิมพ์ชื่อโครงการ'; name.focus(); return; }
      if (src.querySelector('.qp-sum.over')) { msg.textContent = 'ยอดจัดสรรเกิน กรุณาตรวจตัวเลข'; return; }
      save.disabled = true; msg.textContent = '';
      var fd = new FormData();
      fd.append('name', n); fd.append('budget', budget.value || '0');
      fd.append('plan_year', year.value || ''); fd.append('responsible', resp.value || '');
      src.querySelectorAll('input[data-fund]').forEach(function (i) { if (num(i.value)) fd.append('fund_' + i.dataset.fund, i.value); });
      fetch('/finance/projects/quick', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error(res.d.detail || 'บันทึกโครงการไม่สำเร็จ');
          close();
          onDone(res.d);
        })
        .catch(function (e) { save.disabled = false; msg.textContent = e.message || 'บันทึกโครงการไม่สำเร็จ'; });
    });
  }

  sels.forEach(function (sel) {
    var opt = document.createElement('option');
    opt.value = NEW; opt.textContent = '+ เพิ่มโครงการใหม่';
    sel.appendChild(opt);
    var prev = sel.value;
    // capture: ทำงานก่อนสคริปต์อื่นที่ฟังช่องเดียวกัน จะได้ไม่มีใครเห็นค่า "__new"
    sel.addEventListener('change', function (e) {
      if (sel.value !== NEW) { prev = sel.value; return; }
      e.stopImmediatePropagation();
      sel.value = prev;
      openCard(sel, function (d) {
        var o = sel.querySelector('option[value="' + d.id + '"]');
        if (!o) {
          o = document.createElement('option');
          o.value = d.id; o.textContent = d.label;
          sel.insertBefore(o, sel.querySelector('option[value="' + NEW + '"]'));
        }
        sel.value = String(d.id); prev = sel.value;
        var note = sel.parentElement.querySelector('.qp-note');
        if (!note) { note = document.createElement('div'); note.className = 'qp-note hint'; sel.parentElement.appendChild(note); }
        note.innerHTML = (d.message ? esc(d.message) + ' ' : 'เพิ่มโครงการแล้ว ') +
          '<a href="' + esc(d.link) + '" target="_blank" rel="noopener">ดู/แก้ที่หน้าโครงการ</a>';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }, true);
  });
})();
