(() => {
  'use strict';
  const form = document.getElementById('subsidy-form');
  if (!form) return;
  const data = JSON.parse(document.getElementById('subsidy-data').textContent);
  const banner = document.getElementById('sub-dirty');
  let dirty = data.error;
  const actions = [...document.querySelectorAll('[data-needs-saved]')];
  actions.forEach(el => el.querySelectorAll('button').forEach(b => b.dataset.originalDisabled = String(b.disabled)));
  function refresh() {
    banner.hidden = !dirty;
    document.getElementById('allocation-fields').hidden = form.elements.budget_basis.value !== 'allocated';
    actions.forEach(el => {
      el.querySelectorAll('button').forEach(b => b.disabled = dirty || b.dataset.originalDisabled === 'true');
      if (el.tagName === 'A') el.setAttribute('aria-disabled', String(dirty));
    });
    const selected = new Set([...form.querySelectorAll('[name=levels]:checked')].map(el=>el.value));
    form.querySelectorAll('[data-rate-level]').forEach(row=>row.hidden=!selected.has(row.dataset.rateLevel));
    // ช่อง DMC ก็ต้องซ่อนชั้นที่ไม่ได้ติ๊กเหมือนตารางอัตรา ไม่งั้นโรงเรียนประถม
    // ยังต้องเลื่อนผ่านช่อง ม.1-ม.6 ที่ไม่มีวันได้ใช้
    form.querySelectorAll('[data-count-level]').forEach(el=>el.hidden=!selected.has(el.dataset.countLevel));
  }

  // ---- ไฮไลต์ช่องที่ยังต้องกรอก (คำนวณจากฝั่งเซิร์ฟเวอร์ ไม่เดาเองในหน้า) ----
  function markNeeded() {
    (data.need || []).forEach(name => {
      const el = form.elements[name];
      const input = el && (el.length && !el.tagName ? el[0] : el);
      if (!input || !input.setAttribute) return;
      input.setAttribute('aria-invalid', 'true');
      input.addEventListener('input', () => input.removeAttribute('aria-invalid'), {once: true});
    });
  }
  markNeeded();
  document.getElementById('goto-missing')?.addEventListener('click', () => {
    const first = form.querySelector('[aria-invalid="true"]');
    if (!first) return;
    const panel = first.closest('[data-rate-level],[data-count-level]');
    if (panel && panel.hidden) panel.hidden = false;
    first.scrollIntoView({block: 'center', behavior: 'smooth'});
    first.focus({preventScroll: true});
  });

  // ---- เติมทั้งคอลัมน์: พิมพ์เลขเดียว เติมให้ทุกชั้นที่เลือกไว้ ----
  document.querySelectorAll('[data-fill-col]').forEach(btn => btn.addEventListener('click', () => {
    const key = btn.dataset.fillCol;
    const rows = [...form.querySelectorAll('[data-rate-level]')].filter(r => !r.hidden);
    if (!rows.length) return;
    const raw = prompt('ใส่อัตราต่อคนต่อเทอม (บาท) แล้วระบบจะเติมให้ทุกชั้นที่เลือกไว้ '
      + rows.length + ' ชั้น (ชั้นไหนไม่เท่ากัน แก้เฉพาะช่องนั้นทีหลังได้)');
    if (raw === null || raw.trim() === '') return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) { alert('กรุณาใส่ตัวเลขไม่ติดลบ'); return; }
    rows.forEach(r => { const input = form.elements['r_' + r.dataset.rateLevel + '_' + key];
      if (input) { input.value = n; input.removeAttribute('aria-invalid'); } });
    changed();
  }));
  // ---- ยืนยันก่อนบันทึก เมื่อมีการแก้ยอดนักเรียน ----
  // ระบบเลื่อนชั้นให้เองตอนคำนวณงวดแรก ถ้าครูกรอกเป็นชั้นของปีที่จะได้รับแทน
  // ยอดจะเพี้ยนทั้งแผ่นโดยไม่มีอะไรฟ้อง จึงถามย้ำเฉพาะตอนที่แตะยอด DMC
  let censusTouched = false;
  const NL = String.fromCharCode(10);
  function censusConfirmText() {
    const dates = (data.surveys || []).join(' และ ');
    const pair = (data.shifts || [])[0];
    const example = pair ? NL + NL + 'ระบบจะเลื่อนชั้นให้เองตอนคำนวณงวดแรก เช่น ' + pair[0]
      + ' ณ วันสำรวจ ถูกใช้เป็นฐานของ ' + pair[1] + ' ในปีที่คำนวณ จึงไม่ต้องเลื่อนชั้นมาก่อนกรอก' : '';
    return 'โปรดตรวจสอบระดับชั้นของนักเรียน ณ วันที่ ' + dates + NL + NL
      + 'ตัวเลขที่กรอกต้องเป็นจำนวนนักเรียนของชั้นนั้นจริง ๆ ณ วันสำรวจ'
      + example + NL + NL + 'ตรวจแล้ว บันทึกเลยหรือไม่';
  }

  function changed(e) {
    dirty = true;
    if (e && e.target && e.target.closest && e.target.closest('[data-census]')) censusTouched = true;
    refresh();
  }
  form.addEventListener('input',changed);
  form.addEventListener('change',changed);
  form.addEventListener('submit',ev=>{
    if(censusTouched && !confirm(censusConfirmText())){ev.preventDefault();return;}
    dirty=false;
  });
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  actions.forEach(el=>el.addEventListener(el.tagName==='FORM'?'submit':'click',e=>{
    if(dirty){e.preventDefault();banner.scrollIntoView({block:'center'});}
  }));
  document.querySelectorAll('[data-fill]').forEach(button=>button.addEventListener('click',()=>{
    if(!confirm('เติมเฉพาะช่องว่างของรอบนี้จากนักเรียนปัจจุบันเป็นร่าง? ต้องตรวจเทียบ DMC ณ วันสำรวจอีกครั้ง')) return;
    const key=button.dataset.fill;
    Object.entries(data.now).forEach(([lv,n])=>{const input=form.elements['n_'+key+'_'+lv];if(input.value==='')input.value=n;});
    censusTouched=true;
    changed();
  }));
  document.getElementById('copy-rates')?.addEventListener('click',()=>{
    if(!confirm('นำอัตราปีงบก่อนมาแทนค่าที่กรอกในตารางนี้เพื่อตรวจสอบ? กรุณาตรวจตัวเลขก่อนบันทึก'))return;
    Object.entries(data.previous).forEach(([lv,rates])=>Object.entries(rates).forEach(([key,n])=>{
      const input=form.elements['r_'+lv+'_'+key];if(input)input.value=n??'';
    }));
    changed();
  });
  form.addEventListener('click',e=>{
    const add=e.target.closest('[data-add-extra]'), remove=e.target.closest('[data-remove-extra]');
    if(add){
      const rows=add.closest('[data-extra-group]').querySelector('[data-extra-rows]');
      if(rows.children.length>=100){alert('เพิ่มได้ไม่เกิน 100 ครั้งต่อประเภท');return;}
      const row=rows.firstElementChild.cloneNode(true);
      row.querySelectorAll('input').forEach(input=>input.value='');
      rows.appendChild(row);row.querySelector('input').focus();changed();
    }
    if(remove){
      const row=remove.closest('[data-extra-row]');
      if(row.parentElement.children.length>1)row.remove();
      else row.querySelectorAll('input').forEach(input=>input.value='');
      changed();
    }
  });
  const receipts=document.querySelector('form[action="/finance/subsidy/receipts"]');
  if(receipts){
    const type=receipts.elements.item_key, txn=receipts.elements.txn_id;
    function filterReceipts(){
      const id=type.selectedOptions[0]?.dataset.mappedItem;
      [...txn.options].forEach(o=>{if(o.value){o.hidden=!id||o.dataset.item!==id;o.disabled=o.hidden;}});
      if(txn.selectedOptions[0]?.disabled)txn.value='';
    }
    type.addEventListener('change',filterReceipts);filterReceipts();
  }
  refresh();
})();
