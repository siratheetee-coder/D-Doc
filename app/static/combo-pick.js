/* ช่องพิมพ์ค้นหา + เลือกจากรายการ (แนะนำชื่อที่คล้าย แม้พิมพ์ไม่ตรงทั้งหมด)
 * - select[data-combo]: ซ่อน select เดิมไว้ (ค่าที่ส่งฟอร์มยังมาจาก select) แล้ววางช่องพิมพ์ค้นหาแทน
 *   เลือกแล้วส่ง change ให้สคริปต์อื่นที่ฟัง select นี้ (quick-project.js, project_source.js) เหมือนเลือกเอง
 * - input[data-suggest=กลุ่ม]: พิมพ์ชื่อใหม่เองได้ มีรายชื่อแนะนำจาก window.SUGGEST_NAMES[กลุ่ม]
 */
(function () {
  var PREFIX = /^(นางสาว|นาง|นาย|น\.ส\.|ด\.ช\.|ด\.ญ\.|ร้าน|บริษัท|หจก\.?|ห้างหุ้นส่วนจำกัด|โครงการ|กิจกรรม)/;

  function norm(s) {
    s = String(s || '').toLowerCase().replace(/[\s​.\-(),"']/g, '');
    for (var i = 0; i < 2; i++) s = s.replace(PREFIX, '');
    return s.replace(/จำกัด(มหาชน)?$/, '');
  }
  function grams(s) {
    var g = {};
    for (var i = 0; i < s.length - 1; i++) g[s.substr(i, 2)] = (g[s.substr(i, 2)] || 0) + 1;
    return g;
  }
  function dice(a, b) {
    if (a.length < 2 || b.length < 2) return 0;
    var ga = grams(a), gb = grams(b), hit = 0, na = a.length - 1, nb = b.length - 1;
    for (var k in ga) if (gb[k]) hit += Math.min(ga[k], gb[k]);
    return 2 * hit / (na + nb);
  }
  function subseq(q, t) {
    var j = 0;
    for (var i = 0; i < t.length && j < q.length; i++) if (t[i] === q[j]) j++;
    return j === q.length;
  }
  // คะแนนความคล้าย 0 = ไม่แสดง · ตรงต่อกันมาก่อน > มีทุกคำ > ตัวอักษรเรียงตาม > คล้าย (พิมพ์ผิดบางตัว)
  function score(q, text) {
    var qn = norm(q), tn = norm(text);
    if (!qn) return 1;
    var at = tn.indexOf(qn);
    if (at === 0) return 100;
    if (at > 0) return 90;
    var words = String(q).toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length > 1 && words.every(function (w) { return tn.indexOf(norm(w) || w) >= 0; })) return 80;
    if (qn.length >= 3 && subseq(qn, tn)) return 60;
    var d = qn.length >= 3 ? Math.max(dice(qn, tn), dice(qn, tn.substr(0, qn.length + 2))) : 0;
    return d >= 0.4 ? 40 * d : 0;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  // กล่องรายการใต้ช่องพิมพ์ · items() คืน [{v, label, sub, fixed}] · fixed = แสดงเสมอ (เช่น "+ เพิ่มโครงการใหม่")
  function attach(input, items, onPick, opts) {
    opts = opts || {};
    var wrap = document.createElement('div');
    wrap.className = 'cp-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var box = document.createElement('div');
    box.className = 'cp-box'; box.hidden = true;
    wrap.appendChild(box);
    var shown = [], act = -1;

    function render() {
      var q = input.value, all = items(), list = [];
      all.forEach(function (it, i) {
        if (it.fixed || (it.none && !opts.showAll)) return;
        var s = opts.showAll ? 1 : score(q, it.search || it.label);
        if (s > 0) list.push({ it: it, s: s, i: i });
      });
      if (!opts.showAll) list.sort(function (a, b) { return b.s - a.s || a.i - b.i; });
      shown = list.slice(0, 40).map(function (x) { return x.it; });
      // ตรงกับที่พิมพ์ทุกตัวอักษรแล้ว และมีชื่อเดียว ไม่ต้องเปิดรายการ
      if (shown.length === 1 && !opts.combo && shown[0].label === q) shown = [];
      all.forEach(function (it) { if (it.fixed) shown.push(it); });
      act = -1;
      if (!shown.length) { box.hidden = true; return; }
      box.innerHTML = shown.map(function (it, i) {
        return '<div class="cp-item' + (it.fixed ? ' cp-fixed' : '') + '" data-i="' + i + '">' + esc(it.label) +
          (it.sub ? ' <span class="cp-sub">' + esc(it.sub) + '</span>' : '') + '</div>';
      }).join('') + (list.length > 40 ? '<div class="cp-more">พิมพ์เพิ่มเพื่อหาชื่ออื่น (มีอีก ' + (list.length - 40) + ' รายการ)</div>' : '');
      box.hidden = false;
    }
    function hl() {
      box.querySelectorAll('.cp-item').forEach(function (el, i) { el.classList.toggle('cp-act', i === act); });
      var el = box.querySelector('.cp-act');
      if (el) el.scrollIntoView({ block: 'nearest' });
    }
    function pick(i) { var it = shown[i]; box.hidden = true; if (it) onPick(it); }

    input.addEventListener('focus', function () { opts.showAll = !!opts.combo; render(); if (opts.combo) input.select(); });
    input.addEventListener('input', function () { opts.showAll = false; render(); });
    input.addEventListener('keydown', function (e) {
      if (box.hidden) { if (e.key === 'ArrowDown') { opts.showAll = !input.value; render(); e.preventDefault(); } return; }
      var n = box.querySelectorAll('.cp-item').length;
      if (e.key === 'ArrowDown') { act = (act + 1) % n; hl(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { act = (act - 1 + n) % n; hl(); e.preventDefault(); }
      else if (e.key === 'Enter' && (act >= 0 || opts.combo)) { e.preventDefault(); pick(act >= 0 ? act : 0); }
      else if (e.key === 'Escape') { box.hidden = true; }
    });
    // mousedown: เลือกก่อนช่องพิมพ์หลุดโฟกัส
    box.addEventListener('mousedown', function (e) {
      var el = e.target.closest('.cp-item');
      e.preventDefault();
      if (el) pick(+el.dataset.i);
    });
    input.addEventListener('blur', function () { box.hidden = true; if (opts.onBlur) opts.onBlur(); });
  }

  // ---- select ที่มีรายการเยอะ (โครงการ) ----
  document.querySelectorAll('select[data-combo]').forEach(function (sel) {
    var input = document.createElement('input');
    input.type = 'text'; input.autocomplete = 'off'; input.className = 'cp-input';
    input.placeholder = 'พิมพ์ชื่อเพื่อค้นหา หรือคลิกเพื่อเลือก';
    sel.parentNode.insertBefore(input, sel);
    sel.hidden = true; sel.style.display = 'none';
    function label(o) { return o && o.value ? o.textContent.trim() : ''; }
    function sync() { input.value = label(sel.options[sel.selectedIndex]); }
    sync();
    sel.addEventListener('change', sync);
    function items() {
      return Array.prototype.map.call(sel.options, function (o) {
        var t = o.textContent.trim(), cut = t.indexOf(' · ');
        return { v: o.value, label: cut > 0 ? t.slice(0, cut) : t, sub: cut > 0 ? t.slice(cut + 3) : '',
                 search: t, none: o.value === '', fixed: o.value === '__new' };   // ค้นหาปีแผนได้ด้วย (เช่น 2568)
      });
    }
    attach(input, items, function (it) {
      var typed = input.value.trim(), cur = label(sel.options[sel.selectedIndex]);
      sel.value = it.v;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      sync();   // "+ เพิ่มโครงการใหม่" ถูก quick-project.js คืนค่าเดิมไว้ก่อน จนกว่าจะบันทึกโครงการ
      // ค้นไม่เจอแล้วกดเพิ่มใหม่: เติมชื่อที่พิมพ์ค้นไว้ในการ์ดเพิ่มโครงการให้
      var qn = document.getElementById('qpName');
      if (it.fixed && qn && !qn.value && typed && typed !== cur) qn.value = typed;
    }, {
      combo: true,
      onBlur: function () {
        if (!input.value.trim() && sel.value) { sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })); }
        sync();
      },
    });
  });

  // ---- ช่องชื่อที่พิมพ์เองได้ (จ่ายให้ / ชื่อผู้รับเงิน) ----
  var NAMES = window.SUGGEST_NAMES || {};
  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    var list = NAMES[input.dataset.suggest] || [];
    if (!list.length) return;
    attach(input, function () {
      return list.map(function (n) { return { v: n, label: n }; });
    }, function (it) {
      input.value = it.v;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });

  var css = document.createElement('style');
  css.textContent =
    '.cp-wrap{position:relative;}' +
    '.cp-wrap>input{width:100%;}' +
    '.cp-box{position:absolute;left:0;right:0;top:100%;z-index:60;margin-top:4px;max-height:280px;overflow-y:auto;' +
    'background:#fff;border-radius:12px;box-shadow:0 10px 30px rgba(15,23,42,.18);padding:4px;}' +
    '.cp-box[hidden]{display:none;}' +
    '.cp-item{padding:8px 10px;border-radius:8px;cursor:pointer;font-size:14px;line-height:1.4;}' +
    '.cp-item:hover,.cp-act{background:linear-gradient(120deg,#eef4ff,#e0e9ff);}' +
    '.cp-sub{color:#64748b;font-size:12.5px;white-space:nowrap;}' +
    '.cp-fixed{color:#3568e0;font-weight:600;}' +
    '.cp-more{padding:6px 10px;color:#94a3b8;font-size:12.5px;}';
  document.head.appendChild(css);
})();
