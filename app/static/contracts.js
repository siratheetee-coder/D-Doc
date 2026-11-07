(() => {
  'use strict';
  const rows=[...document.querySelectorAll('[data-contract-row]')],forms=[...document.querySelectorAll('[data-edit-form]')];
  const search=document.getElementById('contract-search'),filter=document.getElementById('contract-filter'),all=document.querySelector('[data-save-all]');
  const amount=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  let allowLeave=false;
  const snapshot=f=>JSON.stringify([...new FormData(f).entries()]);
  function error(form,text,fields={}) {
    const box=form.querySelector('[data-error]');box.textContent=text||'';box.hidden=!text;
    form.querySelectorAll('[aria-invalid]').forEach(e=>e.removeAttribute('aria-invalid'));
    Object.keys(fields).forEach(k=>{const el=form.elements.namedItem(k);if(el)el.setAttribute('aria-invalid','true');});
  }
  function dirty(f) {
    if(f.dataset.saving==='1')return;
    f.dataset.dirty=String(snapshot(f)!==f.dataset.original);
    f.querySelector('[data-dirty-hint]').textContent=f.dataset.dirty==='true'?'แก้ไขแล้ว ยังไม่ได้บันทึก':'';
    all.disabled=!forms.some(x=>x.dataset.dirty==='true')||forms.some(x=>x.dataset.saving==='1');
  }
  function time(row){
    const el=row.querySelector('[data-delivery-time]'),d=row.dataset;
    el.className=d.level|| (d.missing==='1'?'missing':'');
    el.textContent=d.missing==='1'?'ยังไม่ระบุวันส่งมอบ':d.level==='overdue'?'เกินกำหนด '+Math.abs(Number(d.days))+' วัน':d.days!==''?(Number(d.days)===0?'ครบกำหนดวันนี้':'เหลือ '+d.days+' วัน'):'';
  }
  function matches(row,key){const d=row.dataset;return key==='all'||(key==='active'&&d.active==='1')||((key==='soon'||key==='overdue')&&d.level===key)||(key==='missing'&&d.missing==='1')||key==='status:'+d.status;}
  function refresh(){
    const terms=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);let count=0;
    rows.forEach(row=>{
      const shown=terms.every(t=>row.dataset.search.toLocaleLowerCase().includes(t))&&matches(row,filter.value);
      row.hidden=!shown;if(shown)count++;
      const edit=document.querySelector('[data-contract-edit="'+row.dataset.cid+'"]');edit.hidden=!shown||edit.dataset.open!=='1';
      time(row);
    });
    document.querySelector('[data-result-count]').textContent='แสดง '+count+' จาก '+rows.length+' สัญญา';
    document.querySelector('[data-contract-empty]').hidden=count>0;
    document.querySelectorAll('[data-contract-filter]').forEach(btn=>{
      const key=btn.dataset.contractFilter;btn.setAttribute('aria-pressed',String(key===filter.value));
      document.querySelector('[data-count="'+key+'"]').textContent=rows.filter(r=>matches(r,key)).length;
    });
  }
  function updateRow(form,c){
    const row=document.getElementById('contract-'+c.id);
    for(const [k,v] of Object.entries(c)){
      const field=form.elements.namedItem(k);if(field){field.value=v===null?'':v;if(field.tagName==='SELECT')[...field.options].forEach(o=>o.defaultSelected=o.selected);else field.defaultValue=field.value;}
      const out=row.querySelector('[data-display="'+k+'"]');if(out)out.textContent=k==='amount'?amount(v):(v||'ยังไม่ระบุ');
    }
    Object.assign(row.dataset,{status:c.status,level:c.level||'',days:c.days_left===null?'':String(c.days_left),missing:c.missing_due?'1':'0',active:c.status==='ระหว่างดำเนินการ'?'1':'0',search:[c.contract_no,c.party,c.subject].join(' ')});
    // Controls are disabled during the request; snapshot after they are unlocked.
    form.dataset.saved='1';refresh();
  }
  function message(text,bad=false){const el=document.querySelector('[data-save-message]');el.textContent=text;el.hidden=false;el.classList.toggle('is-error',bad);}
  async function save(form){
    if(form.dataset.saving==='1')return false;
    if(!form.checkValidity()){
      filter.value='all';search.value='';form.closest('[data-contract-edit]').dataset.open='1';refresh();
      form.reportValidity();return false;
    }
    error(form,'');const body=new FormData(form),controls=[...form.elements].map(el=>[el,el.disabled]);
    form.dataset.saving='1';controls.forEach(([el])=>el.disabled=true);all.disabled=true;
    try {
      const response=await fetch(form.action,{method:'POST',body,headers:{'X-Requested-With':'fetch'}});
      const data=await response.json().catch(()=>({detail:'บันทึกไม่สำเร็จ กรุณาตรวจการเข้าสู่ระบบแล้วลองใหม่'}));
      if(!response.ok||!data.ok||!data.contract){error(form,data.detail||'บันทึกไม่สำเร็จ',data.errors);return false;}
      updateRow(form,data.contract);return true;
    }catch(e){error(form,'เชื่อมต่อไม่สำเร็จ ข้อมูลที่แก้ไขยังอยู่ กรุณาลองใหม่');return false;}
    finally {
      controls.forEach(([el,disabled])=>el.disabled=disabled);form.dataset.saving='0';
      if(form.dataset.saved==='1'){form.dataset.original=snapshot(form);delete form.dataset.saved;}
      dirty(form);
    }
  }
  forms.forEach(form=>{
    form.dataset.original=snapshot(form);form.dataset.dirty='false';
    form.addEventListener('input',()=>dirty(form));form.addEventListener('change',()=>dirty(form));
    form.addEventListener('submit',async e=>{e.preventDefault();const ok=await save(form);message(ok?'บันทึกรายการแล้ว':'ยังบันทึกไม่สำเร็จ ตรวจข้อความในรายการที่แก้ไข',!ok);});
  });
  document.querySelectorAll('[data-edit-contract]').forEach(btn=>btn.addEventListener('click',()=>{
    const edit=document.querySelector('[data-contract-edit="'+btn.dataset.editContract+'"]');
    edit.dataset.open=edit.dataset.open==='1'?'0':'1';refresh();
    btn.setAttribute('aria-expanded',String(edit.dataset.open==='1'));if(!edit.hidden)edit.querySelector('input').focus({preventScroll:true});
  }));
  document.querySelectorAll('[data-cancel-contract]').forEach(btn=>btn.addEventListener('click',()=>{
    const form=btn.closest('form'),edit=btn.closest('[data-contract-edit]');form.reset();error(form,'');dirty(form);edit.dataset.open='0';edit.hidden=true;
  }));
  all.addEventListener('click',async()=>{
    const pending=forms.filter(f=>f.dataset.dirty==='true');if(!pending.length)return;
    all.disabled=true;
    const results=[];for(const f of pending)results.push(await save(f));
    const n=results.filter(Boolean).length;
    message(n===pending.length?'บันทึกครบ '+n+' รายการแล้ว':'บันทึกแล้ว '+n+' รายการ · อีก '+(pending.length-n)+' รายการยังไม่สำเร็จ ข้อมูลที่แก้ยังอยู่',n!==pending.length);
    all.disabled=!forms.some(f=>f.dataset.dirty==='true');
  });
  async function submitNavigate(form){
    if(!form.reportValidity())return;
    if(forms.some(f=>f.dataset.dirty==='true')&&!confirm('มีรายการที่แก้ไขแล้วยังไม่บันทึก หากดำเนินการต่อข้อมูลส่วนนั้นจะหาย ต้องการไปต่อหรือไม่?'))return;
    const button=form.querySelector('button[type=submit]'),body=new FormData(form);button.disabled=true;error(form,'');
    try{
      const r=await fetch(form.action,{method:'POST',body,headers:{'X-Requested-With':'fetch'}});
      if(r.ok&&r.redirected&&new URL(r.url).pathname==='/procurement/contracts'){allowLeave=true;location.assign(r.url);return;}
      const d=await r.json().catch(()=>({detail:'ดำเนินการไม่สำเร็จ กรุณาเปิดหน้าใหม่และตรวจการเข้าสู่ระบบ'}));error(form,d.detail||'ดำเนินการไม่สำเร็จ',d.errors);
    }catch(e){error(form,'เชื่อมต่อไม่สำเร็จ กรุณาลองใหม่');}finally{button.disabled=false;}
  }
  document.querySelectorAll('[data-contract-new],[data-contract-import-form]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();submitNavigate(f);}));
  const importAll=document.querySelector('[data-import-all]');if(importAll)importAll.addEventListener('change',()=>document.querySelectorAll('[name=selected]').forEach(c=>c.checked=importAll.checked));
  document.querySelectorAll('[data-open-manual]').forEach(a=>a.addEventListener('click',()=>document.getElementById('contract-manual').open=true));
  document.querySelectorAll('[data-contract-filter]').forEach(b=>b.addEventListener('click',()=>{filter.value=b.dataset.contractFilter;refresh();}));
  search.addEventListener('input',refresh);filter.addEventListener('change',refresh);
  document.querySelectorAll('input[data-date]').forEach(el=>el.addEventListener('input',()=>{
    const v=el.value.replace(/\D/g,'').slice(0,8);el.value=v.slice(0,2)+(v.length>2?'/'+v.slice(2,4):'')+(v.length>4?'/'+v.slice(4):'');
  }));
  window.addEventListener('beforeunload',e=>{if(!allowLeave&&forms.some(f=>f.dataset.dirty==='true')){e.preventDefault();e.returnValue='';}});
  refresh();
})();
