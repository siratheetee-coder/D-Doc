// แยกจ่ายบันทึกขอเบิกจากหลายบัญชี (app/templates/_disburse_splits.html)
// ไม่เปิดกล่อง = ไม่ส่ง split_* ไปเลย บันทึกทำงานแบบบัญชีเดียวตามเดิม
(function () {
  var S = window.SPLIT, box = document.getElementById('splitBox'), list = document.getElementById('splitRows');
  var open = document.getElementById('splitOpen'), sum = document.getElementById('splitSum');
  if (!S || !box) return;
  var form = box.closest('form');
  var acct = document.getElementById('acctSel'), item = document.getElementById('itemSel');
  var line = document.getElementById('srcLine');
  var amount = form.querySelector('input[name="amount"]');
  var wht = form.querySelector('input[name="wht"]'), fine = form.querySelector('input[name="fine"]');

  function num(el) { return parseFloat(el && el.value) || 0; }
  function money(n) { return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function r2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }
  function rows() { return [].slice.call(list.querySelectorAll('.split-row')); }
  function amt(r) { return r.querySelector('[name="split_amount"]'); }

  function fillItems(sel, acctId, chosen) {
    var its = S.items[acctId] || [];
    sel.innerHTML = '';
    var first = document.createElement('option');
    first.value = '';
    first.textContent = !acctId ? '- เลือกบัญชีก่อน -' : its.length ? '- ไม่ระบุหมวด -' : '- บัญชีนี้ยังไม่มีหมวด -';
    sel.appendChild(first);
    its.forEach(function (it) {
      var o = document.createElement('option');
      o.value = it.id; o.textContent = it.name;
      if (String(it.id) === String(chosen)) o.selected = true;
      sel.appendChild(o);
    });
  }

  function addRow(accId, itemId, value) {
    var r = document.createElement('div');
    r.className = 'split-row';
    r.innerHTML = '<div><label>บัญชี</label><select name="split_account"></select></div>'
      + '<div><label>หมวด</label><select name="split_item"></select></div>'
      + '<div><label>จำนวนเงิน</label><input name="split_amount" type="number" step="0.01" min="0"></div>'
      + '<button type="button" class="split-del" title="ลบแถวนี้" aria-label="ลบแถวนี้">&times;</button>'
      + '<div class="split-cut"></div>';
    var a = r.querySelector('[name="split_account"]'), it = r.querySelector('[name="split_item"]');
    var blank = document.createElement('option');
    blank.value = ''; blank.textContent = '- เลือกบัญชี -';
    a.appendChild(blank);
    S.accounts.forEach(function (id, i) {
      var o = document.createElement('option');
      o.value = id; o.textContent = S.names[i];
      a.appendChild(o);
    });
    a.value = accId || '';
    fillItems(it, a.value, itemId);
    if (value) amt(r).value = value.toFixed(2);
    a.addEventListener('change', function () { fillItems(it, a.value, null); refresh(); });
    amt(r).addEventListener('input', function () { r.dataset.typed = '1'; refresh(); });
    r.querySelector('.split-del').addEventListener('click', function () {
      r.remove();
      if (rows().length < 2) close(); else refresh();
    });
    list.appendChild(r);
    return r;
  }

  // แถวสุดท้ายที่ยังไม่ได้พิมพ์เอง เติมส่วนที่เหลือให้
  function refresh() {
    var all = rows(), total = num(amount), last = all[all.length - 1];
    if (last && !last.dataset.typed) {
      var used = all.slice(0, -1).reduce(function (s, r) { return s + num(amt(r)); }, 0);
      var rest = r2(total - used);
      amt(last).value = rest > 0 ? rest.toFixed(2) : '';
    }
    var done = r2(all.reduce(function (s, r) { return s + num(amt(r)); }, 0)), diff = r2(total - done);
    sum.textContent = 'แบ่งแล้ว ' + money(done) + ' จาก ' + money(total) + ' บาท'
      + (diff > 0 ? ' ยังขาด ' + money(diff) : diff < 0 ? ' เกิน ' + money(-diff) : '');
    sum.className = 'split-sum ' + (diff === 0 && total > 0 ? 'ok' : 'bad');

    // แต่ละบัญชีหักเท่าไร เศษสตางค์ยกให้แถวสุดท้าย ตรงกับ disburse_split._share
    var w = num(wht), f = num(fine), wUsed = 0, fUsed = 0;
    all.forEach(function (r, i) {
      var a = num(amt(r)), end = i === all.length - 1;
      var ws = end ? r2(w - wUsed) : (done ? r2(w * a / done) : 0);
      var fs = end ? r2(f - fUsed) : (done ? r2(f * a / done) : 0);
      wUsed = r2(wUsed + ws); fUsed = r2(fUsed + fs);
      var parts = [];
      if (w) parts.push('หัก ณ ที่จ่าย ' + money(ws));
      if (f) parts.push('ค่าปรับ ' + money(fs));
      if (parts.length) parts.push('จ่ายจริง ' + money(r2(a - ws - fs)) + ' บาท');
      r.querySelector('.split-cut').textContent = parts.join('  ');
    });
    return diff === 0;
  }

  function show(on) {
    box.hidden = !on; open.hidden = on;
    [acct, item].forEach(function (el) { if (el) el.parentNode.style.display = on ? 'none' : ''; });
    if (line) line.style.display = on ? 'none' : '';
  }

  function close() {
    var one = rows()[0];
    if (one) {        // แถวที่เหลือกลับไปเป็นบัญชีเดียว
      var a = one.querySelector('[name="split_account"]').value;
      var it = one.querySelector('[name="split_item"]').value;
      if (acct && a) {
        acct.value = a;
        acct.dispatchEvent(new Event('change', { bubbles: true }));
        if (item) item.value = it;
      }
    }
    list.innerHTML = '';
    show(false);
  }

  open.addEventListener('click', function () {
    show(true);
    addRow(acct ? acct.value : '', item ? item.value : '', num(amount)).dataset.typed = '1';
    addRow('', '', 0);
    refresh();
    amt(rows()[0]).select();
  });
  document.getElementById('splitClose').addEventListener('click', function () {
    rows().slice(1).forEach(function (r) { r.remove(); });
    close();
  });
  document.getElementById('splitAdd').addEventListener('click', function () {
    var all = rows(), last = all[all.length - 1];
    if (last) last.dataset.typed = '1';
    addRow('', '', 0);
    refresh();
  });
  [amount, wht, fine].forEach(function (el) {
    if (el) el.addEventListener('input', function () { if (!box.hidden) refresh(); });
  });
  form.addEventListener('submit', function (e) {
    if (box.hidden) return;
    if (!refresh() || rows().some(function (r) { return !r.querySelector('[name="split_account"]').value; })) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (refresh()) sum.textContent = 'เลือกบัญชีให้ครบทุกแถว';
      sum.className = 'split-sum bad';
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, true);

  if (S.rows.length) {
    show(true);
    S.rows.forEach(function (r) { addRow(r.account_id, r.item_id, r.amount).dataset.typed = '1'; });
    refresh();
  }
})();
