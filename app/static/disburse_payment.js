(() => {
  'use strict';
  const dialog=document.getElementById('disburse-payment-dialog'),edit=document.getElementById('disburseEditForm'),details=document.getElementById('disburse-details'),warning=document.getElementById('dm-unsaved');
  let baseline,opener;
  const snapshot=()=>JSON.stringify([...new FormData(edit).entries()].map(([key,value])=>[key,String(value)]));
  window.addEventListener('load',()=>{if(edit)baseline=snapshot();});
  function reveal(field){if(details)details.open=true;const el=edit&&(edit.querySelector('#'+field)||edit.querySelector('[name="'+field+'"]'));if(el){el.scrollIntoView({block:'center',behavior:'smooth'});el.focus({preventScroll:true});}}
  document.querySelectorAll('[data-dm-edit]').forEach(b=>b.addEventListener('click',()=>reveal(b.dataset.dmEdit)));
  if(!dialog)return;
  document.querySelectorAll('[data-dm-open]').forEach(b=>b.addEventListener('click',()=>{
    if(edit&&baseline!==undefined&&snapshot()!==baseline){warning.hidden=false;warning.scrollIntoView({block:'center',behavior:'smooth'});return;}
    warning.hidden=true;opener=b;dialog.showModal();
  }));
  dialog.querySelectorAll('[data-dm-close]').forEach(b=>b.addEventListener('click',()=>{dialog.close();if(opener)opener.focus();}));
  const form=document.getElementById('dm-payment-form'),submit=document.getElementById('dm-confirm');
  form.addEventListener('submit',event=>{if(!form.checkValidity()){event.preventDefault();return;}submit.disabled=true;submit.textContent='กำลังบันทึกจ่าย…';});
  window.addEventListener('pageshow',()=>{submit.disabled=false;submit.textContent='ยืนยันบันทึกจ่าย';});
})();
