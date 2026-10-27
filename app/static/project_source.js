// เลือกโครงการช่องเดียว แล้วเติมบัญชี + หมวด ให้เอง (ฟอร์มขอเบิกจ่าย ทั้งสร้างใหม่และแก้ไข)
//
// โครงการรู้ว่าใช้หมวดไหนจาก /finance/project-sources/<id> (จัดสรรไว้ในแผน หรือเคยใช้ครั้งก่อน)
//   หมวดเดียว   ซ่อนช่องบัญชี/หมวด โชว์บรรทัด "จะหักจาก ..." พร้อมปุ่มเปลี่ยน
//   หลายหมวด   ให้กดเลือกจากรายการ
//   ไม่รู้จัก   โชว์ช่องให้เลือกเหมือนเดิม และบอกว่าครั้งหน้าระบบจำให้
//
// ต้องมีในหน้า: #projSel #acctSel #itemSel #srcLine #srcPick และ input[name=budget_source]
// และฟังก์ชัน fillItems(selectedItemId) ที่เติมตัวเลือกหมวดตามบัญชี
(function () {
  var proj = document.getElementById('projSel');
  var acct = document.getElementById('acctSel');
  var item = document.getElementById('itemSel');
  var line = document.getElementById('srcLine');
  var pick = document.getElementById('srcPick');
  var src = document.querySelector('input[name="budget_source"]');
  if (!proj || !acct || !item || !line || !pick) return;
  var fy = proj.getAttribute('data-fy') || '';
  var autoSrc = null;          // ข้อความแหล่งเงินที่ระบบเติมให้ล่าสุด (ผู้ใช้พิมพ์ทับแล้วจะไม่ไปแตะ)
  var auto = null;             // บัญชี+หมวดที่ระบบเติมให้ล่าสุด {acct, item}

  function esc(t) {
    return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function showPick(on) { pick.hidden = !on; }

  function apply(s) {
    acct.value = String(s.account_id);
    if (typeof fillItems === 'function') fillItems(s.item_id);
    auto = { acct: acct.value, item: item.value || '' };
    if (src && (!src.value.trim() || src.value === autoSrc)) {
      src.value = s.account_name;
      autoSrc = s.account_name;
    }
  }

  // เปลี่ยนโครงการแล้ว ค่าที่ระบบเติมให้โครงการเดิมต้องหายไป ไม่งั้นโครงการใหม่จะได้หมวดของโครงการเดิม
  // ไปแบบเงียบ ๆ (ค่าที่ผู้ใช้เลือกเองไม่แตะ)
  function clearAuto() {
    if (auto && acct.value === auto.acct && (item.value || '') === auto.item) {
      acct.value = '';
      if (typeof fillItems === 'function') fillItems(null);
    }
    if (src && autoSrc !== null && src.value === autoSrc) src.value = '';
    auto = null; autoSrc = null;
  }

  function render(list) {
    if (!proj.value) {                       // ไม่ผูกโครงการ: ใช้ฟอร์มเดิมทุกช่อง
      line.hidden = true; line.innerHTML = ''; showPick(true); return;
    }
    if (!list.length) {
      line.hidden = false;
      line.className = 'src-line src-new';
      line.innerHTML = 'โครงการนี้ยังไม่เคยระบุหมวด เลือกบัญชีและหมวดด้านล่างครั้งเดียว ครั้งหน้าระบบจำให้';
      showPick(true);
      return;
    }
    if (list.length === 1) {
      apply(list[0]);
      line.hidden = false;
      line.className = 'src-line src-ok';
      line.innerHTML = 'จะหักจาก <b>' + esc(list[0].label) + '</b> <span class="src-why">'
        + esc(list[0].why) + '</span> <button type="button" class="btn sm gray" id="srcChange">เปลี่ยน</button>';
      showPick(false);
      document.getElementById('srcChange').onclick = function () { showPick(true); this.remove(); };
      return;
    }
    line.hidden = false;
    line.className = 'src-line src-ok';
    var h = 'โครงการนี้ใช้เงินหลายหมวด เลือกหมวดที่จะหัก:<div class="src-opts">';
    list.forEach(function (s, i) {
      h += '<label><input type="radio" name="_src" value="' + i + '"> ' + esc(s.label)
        + ' <span class="src-why">' + esc(s.why) + '</span></label>';
    });
    line.innerHTML = h + '</div>';
    showPick(false);
    line.querySelectorAll('input[name=_src]').forEach(function (r) {
      r.onchange = function () { apply(list[+this.value]); };
    });
    var cur = list.findIndex(function (s) {
      return String(s.account_id) === acct.value && String(s.item_id || '') === (item.value || '');
    });
    if (cur >= 0) line.querySelectorAll('input[name=_src]')[cur].checked = true;
  }

  function load(keepCurrent) {
    if (!proj.value) { render([]); return; }
    fetch('/finance/project-sources/' + encodeURIComponent(proj.value) + '?fy=' + encodeURIComponent(fy),
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { sources: [] }; })
      .then(function (d) {
        var list = d.sources || [];
        // หน้าแก้ไข: ถ้าบันทึกนี้ระบุหมวดไว้แล้ว และตรงกับที่ระบบรู้ ไม่ต้องไปเปลี่ยนให้
        if (keepCurrent && acct.value && list.length === 1
            && (String(list[0].account_id) !== acct.value
                || String(list[0].item_id || '') !== (item.value || ''))) {
          line.hidden = false; line.className = 'src-line src-new';
          line.innerHTML = 'บันทึกนี้หักจากหมวดที่ต่างจากที่โครงการเคยใช้ ตรวจสอบช่องด้านล่าง';
          showPick(true);
          return;
        }
        render(list);
      })
      .catch(function () { render([]); });
  }

  proj.addEventListener('change', function () { clearAuto(); load(false); });
  load(proj.getAttribute('data-edit') === '1');
})();
