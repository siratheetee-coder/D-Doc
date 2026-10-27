/* ช่องพิมพ์ค้นหา + เลือกจากรายการ (แนะนำชื่อที่คล้าย แม้พิมพ์ไม่ตรงทั้งหมด) โหลดทุกหน้าจาก base.html
 * - select[data-combo]: ซ่อน select เดิมไว้ (ค่าที่ส่งฟอร์มยังมาจาก select) แล้ววางช่องพิมพ์ค้นหาแทน
 *   เลือกแล้วส่ง change ให้สคริปต์อื่นที่ฟัง select นี้ (quick-project.js, project_source.js) เหมือนเลือกเอง
 * - input[data-suggest=กลุ่ม]: พิมพ์ชื่อใหม่เองได้ มีรายชื่อแนะนำจาก window.SUGGEST_NAMES[กลุ่ม]
 * - input[list] (datalist เดิมทั้งระบบ): ตอนคลิกช่องครั้งแรก เปลี่ยนมาใช้กล่องแนะนำนี้แทนของเบราว์เซอร์
 *   (ของเบราว์เซอร์หาได้แค่ตัวอักษรที่ตรงกันเป๊ะ) ใส่ data-native-list ไว้ถ้าอยากใช้แบบเดิม
 * กล่องรายการเป็น position:fixed ลอยเหนือหน้า จึงไม่โดนตาราง/กล่องที่เลื่อนได้ตัดขอบ
 */
(function () {
  if (window.__comboPick) return;
  window.__comboPick = true;
  var PREFIX = /^(นางสาว|นาง|นาย|น\.ส\.|ด\.ช\.|ด\.ญ\.|ว่าที่ร้อยตรี|ว่าที่ ร\.ต\.|ร้าน|บริษัท|หจก\.?|ห้างหุ้นส่วนจำกัด|โครงการ|กิจกรรม)/;

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
  // คะแนนความคล้าย 0 = ไม่แสดง ตรงต่อกันมาก่อน > มีทุกคำ > ตัวอักษรเรียงตาม > คล้าย (พิมพ์ผิดบางตัว)
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
  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

  // ---- กล่องรายการใบเดียวใช้ร่วมกันทั้งหน้า (ลอยใต้ช่องที่กำลังพิมพ์)
  var box = document.createElement('div');
  box.className = 'cp-box'; box.hidden = true;
  var owner = null;                        // ช่องที่เปิดกล่องอยู่
  function place() {
    if (!owner || box.hidden) return;
    var r = owner.input.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    if (r.bottom < 0 || r.top > vh) { hide(); return; }
    var w = Math.min(Math.max(r.width, 240), vw - 16);
    box.style.width = w + 'px';
    box.style.left = Math.max(8, Math.min(r.left, vw - w - 8)) + 'px';
    var below = vh - r.bottom, h = Math.min(box.scrollHeight, 300);
    if (below < h + 12 && r.top > below) { box.style.top = ''; box.style.bottom = (vh - r.top + 4) + 'px'; }
    else { box.style.bottom = ''; box.style.top = (r.bottom + 4) + 'px'; }
  }
  function hide() { box.hidden = true; owner = null; }
  window.addEventListener('resize', place);
  window.addEventListener('scroll', place, true);
  // mousedown: เลือกก่อนช่องพิมพ์หลุดโฟกัส
  box.addEventListener('mousedown', function (e) {
    e.preventDefault();
    var el = e.target.closest('.cp-item');
    if (el && owner) owner.pick(+el.dataset.i);
  });
  function mount() { if (!box.parentNode) document.body.appendChild(box); }

  // items() คืน [{v, label, sub, search, fixed, none}] fixed = แสดงเสมอ (เช่น "+ เพิ่มโครงการใหม่")
  function attach(input, items, onPick, opts) {
    opts = opts || {};
    var shown = [], act = -1, me = {};
    me.input = input;
    function render() {
      mount();
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
      if (!shown.length) { if (owner === me) hide(); return; }
      box.innerHTML = shown.map(function (it, i) {
        return '<div class="cp-item' + (it.fixed ? ' cp-fixed' : '') + '" data-i="' + i + '">' + esc(it.label) +
          (it.sub ? ' <span class="cp-sub">' + esc(it.sub) + '</span>' : '') + '</div>';
      }).join('') + (list.length > 40 ? '<div class="cp-more">พิมพ์เพิ่มเพื่อหาชื่ออื่น (มีอีก ' + (list.length - 40) + ' รายการ)</div>' : '');
      owner = me; box.hidden = false; box.scrollTop = 0; place();
    }
    function hl() {
      box.querySelectorAll('.cp-item').forEach(function (el, i) { el.classList.toggle('cp-act', i === act); });
      var el = box.querySelector('.cp-act');
      if (el) el.scrollIntoView({ block: 'nearest' });
    }
    me.pick = function (i) { var it = shown[i]; hide(); if (it) onPick(it); };
    me.open = function () { opts.showAll = !!opts.combo; render(); if (opts.combo) input.select(); };

    input.addEventListener('focus', me.open);
    input.addEventListener('input', function (e) { if (e.isTrusted === false && e.cpPicked) return; opts.showAll = false; render(); });
    input.addEventListener('keydown', function (e) {
      var open = owner === me && !box.hidden;
      if (!open) { if (e.key === 'ArrowDown') { opts.showAll = !input.value; render(); e.preventDefault(); } return; }
      var n = box.querySelectorAll('.cp-item').length;
      if (e.key === 'ArrowDown') { act = (act + 1) % n; hl(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { act = (act - 1 + n) % n; hl(); e.preventDefault(); }
      else if (e.key === 'Enter' && (act >= 0 || opts.combo)) { e.preventDefault(); me.pick(act >= 0 ? act : 0); }
      else if (e.key === 'Escape' || e.key === 'Tab') { hide(); }
    });
    input.addEventListener('blur', function () { if (owner === me) hide(); if (opts.onBlur) opts.onBlur(); });
    return me;
  }
  function setPicked(input, v) {
    input.value = v;
    var ev = new Event('input', { bubbles: true }); ev.cpPicked = true;   // ให้สคริปต์อื่นรู้ว่าค่าเปลี่ยน แต่ไม่เปิดกล่องซ้ำ
    input.dispatchEvent(ev);
    fire(input, 'change');
  }

  // ---- select ที่มีรายการเยอะ (โครงการ ผู้รับจ้าง) ----
  function comboSelect(sel) {
    if (sel.dataset.cpDone) return;
    sel.dataset.cpDone = '1';
    var input = document.createElement('input');
    input.type = 'text'; input.autocomplete = 'off'; input.className = 'cp-input';
    input.placeholder = sel.dataset.comboPlaceholder || 'พิมพ์ชื่อเพื่อค้นหา หรือคลิกเพื่อเลือก';
    if (sel.title) input.title = sel.title;
    sel.parentNode.insertBefore(input, sel);
    sel.hidden = true; sel.style.display = 'none';
    function label(o) { return o && o.value ? o.textContent.trim() : ''; }
    function sync() { input.value = label(sel.options[sel.selectedIndex]); input.disabled = sel.disabled; }
    sync();
    sel.addEventListener('change', sync);
    // สคริปต์อื่นปิด/เปิด select (เช่น กดเพิ่มผู้รับจ้างใหม่) -> ช่องพิมพ์ตามไปด้วย
    new MutationObserver(sync).observe(sel, { attributes: true, attributeFilter: ['disabled'] });
    function items() {
      return Array.prototype.map.call(sel.options, function (o) {
        var t = o.textContent.trim(), cut = t.indexOf(' ');
        return { v: o.value, label: cut > 0 ? t.slice(0, cut) : t, sub: cut > 0 ? t.slice(cut + 3) : '',
                 search: t, none: o.value === '', fixed: o.value === '__new' };   // ค้นหาปีแผนได้ด้วย (เช่น 2568)
      });
    }
    attach(input, items, function (it) {
      var typed = input.value.trim(), cur = label(sel.options[sel.selectedIndex]);
      sel.value = it.v;
      fire(sel, 'change');
      sync();   // "+ เพิ่มโครงการใหม่" ถูก quick-project.js คืนค่าเดิมไว้ก่อน จนกว่าจะบันทึกโครงการ
      // ค้นไม่เจอแล้วกดเพิ่มใหม่: เติมชื่อที่พิมพ์ค้นไว้ในการ์ดเพิ่มโครงการให้
      var qn = document.getElementById('qpName');
      if (it.fixed && qn && !qn.value && typed && typed !== cur) qn.value = typed;
    }, {
      combo: true,
      onBlur: function () {
        if (!input.value.trim() && sel.value) { sel.value = ''; fire(sel, 'change'); }
        sync();
      },
    });
  }

  // ---- ช่องชื่อที่พิมพ์เองได้ (จ่ายให้ / ชื่อผู้รับเงิน) ----
  function suggestInput(input) {
    var list = (window.SUGGEST_NAMES || {})[input.dataset.suggest] || [];
    if (!list.length || input.dataset.cpDone) return;
    input.dataset.cpDone = '1';
    attach(input, function () {
      return list.map(function (n) { return { v: n, label: n }; });
    }, function (it) { setPicked(input, it.v); });
  }

  // ---- datalist เดิมทั้งระบบ: เปลี่ยนตอนคลิกช่องครั้งแรก (รวมแถวที่สคริปต์เพิ่มทีหลัง)
  function upgradeList(input) {
    var id = input.getAttribute('list'), dl = id && document.getElementById(id);
    if (!dl || input.dataset.cpDone || input.hasAttribute('data-native-list')) return null;
    input.dataset.cpDone = '1';
    input.dataset.cpList = id;
    input.removeAttribute('list');                       // ปิดกล่องของเบราว์เซอร์ ไม่ให้ขึ้นซ้อนกัน
    input.setAttribute('autocomplete', 'off');
    return attach(input, function () {
      var seen = {};
      return Array.prototype.filter.call(dl.options, function (o) {
        var v = (o.value || '').trim();
        if (!v || seen[v]) return false;
        seen[v] = 1; return true;
      }).map(function (o) {
        var extra = (o.label && o.label !== o.value) ? o.label : (o.textContent.trim() !== o.value ? o.textContent.trim() : '');
        return { v: o.value, label: o.value, sub: extra, search: o.value + ' ' + extra };
      });
    }, function (it) { setPicked(input, it.v); });
  }
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el && el.tagName === 'INPUT' && el.hasAttribute('list')) {
      var me = upgradeList(el);
      if (me) me.open();                                 // โฟกัสเกิดไปแล้ว เปิดกล่องให้เลย
    }
  }, true);

  function init() {
    document.querySelectorAll('select[data-combo]').forEach(comboSelect);
    document.querySelectorAll('input[data-suggest]').forEach(suggestInput);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  var css = document.createElement('style');
  css.textContent =
    '.cp-input{width:100%;}' +
    '.cp-box{position:fixed;z-index:2000;max-height:300px;overflow-y:auto;' +
    'background:#fff;border-radius:12px;box-shadow:0 10px 30px rgba(15,23,42,.18);padding:4px;}' +
    '.cp-box[hidden]{display:none;}' +
    '.cp-item{padding:8px 10px;border-radius:8px;cursor:pointer;font-size:14px;line-height:1.4;text-align:left;}' +
    '.cp-item:hover,.cp-act{background:linear-gradient(120deg,#eef4ff,#e0e9ff);}' +
    '.cp-sub{color:#64748b;font-size:12.5px;white-space:nowrap;}' +
    '.cp-fixed{color:#3568e0;font-weight:600;}' +
    '.cp-more{padding:6px 10px;color:#94a3b8;font-size:12.5px;}';
  document.head.appendChild(css);
})();
