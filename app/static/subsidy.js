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
    actions.forEach(el => {
      el.querySelectorAll('button').forEach(b => b.disabled = dirty || b.dataset.originalDisabled === 'true');
      if (el.tagName === 'A') el.setAttribute('aria-disabled', String(dirty));
    });
    const selected = new Set([...form.querySelectorAll('[name=levels]:checked')].map(el=>el.value));
    form.querySelectorAll('[data-rate-level]').forEach(row=>row.hidden=!selected.has(row.dataset.rateLevel));
  }
  function changed(e) {
    dirty = true;
    const name = e?.target?.name || '';
    if (name.startsWith('r_') || name === 'rate_source' || name === 'levels') form.elements.rates_confirmed.checked = false;
    if (name.startsWith('n_') || name.startsWith('source_')) {
      const panel = e.target.closest('[data-census]');
      if (panel) form.elements['confirm_' + panel.dataset.census].checked = false;
    }
    refresh();
  }
  form.addEventListener('input',changed);
  form.addEventListener('change',changed);
  form.addEventListener('submit',()=>{dirty=false;});
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  actions.forEach(el=>el.addEventListener(el.tagName==='FORM'?'submit':'click',e=>{
    if(dirty){e.preventDefault();banner.scrollIntoView({block:'center'});}
  }));
  document.querySelectorAll('[data-fill]').forEach(button=>button.addEventListener('click',()=>{
    if(!confirm('เติมเฉพาะช่องว่างของรอบนี้จากนักเรียนปัจจุบันเป็นร่าง? ต้องตรวจเทียบ DMC ณ วันสำรวจอีกครั้ง')) return;
    const key=button.dataset.fill;
    Object.entries(data.now).forEach(([lv,n])=>{const input=form.elements['n_'+key+'_'+lv];if(input.value==='')input.value=n;});
    form.elements['source_'+key].value='ร่างจากทะเบียนปัจจุบัน — ยังไม่ได้ตรวจเทียบ DMC ณ วันสำรวจ';
    form.elements['confirm_'+key].checked=false;
    changed();
  }));
  document.getElementById('copy-rates')?.addEventListener('click',()=>{
    if(!confirm('นำอัตราปีงบก่อนมาแทนค่าที่กรอกในตารางนี้เพื่อตรวจสอบ? ต้องตรวจอัตราปีงบใหม่ก่อนยืนยัน'))return;
    Object.entries(data.previous).forEach(([lv,rates])=>Object.entries(rates).forEach(([key,n])=>{
      const input=form.elements['r_'+lv+'_'+key];if(input)input.value=n??'';
    }));
    form.elements.rates_confirmed.checked=false;
    form.elements.rate_source.value='';
    changed();
  });
  refresh();
})();
