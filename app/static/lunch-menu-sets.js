(()=>{
 const search=document.getElementById('setSearch');if(search)search.addEventListener('input',()=>document.querySelectorAll('[data-set-name]').forEach(e=>e.hidden=!e.dataset.setName.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())));
 const editor=document.getElementById('setEditor'),days=document.getElementById('setDays'),body=document.getElementById('setEditorRows');
 if(editor){
  const initial=JSON.parse(document.getElementById('setInitialRows').textContent||'[]');
  function add(row={}){const tr=document.getElementById('setRowTemplate').content.firstElementChild.cloneNode(true),i=body.children.length;tr.querySelector('[data-day-number]').textContent='วันที่ '+(i+1);for(const n of ['main','dessert','note'])tr.querySelector('[name='+n+']').value=row[n]||'';body.appendChild(tr);}
  function resize(){const n=Number(days.value);if(!Number.isInteger(n)||n<1||n>366)return;const old=body.children.length;if(n<old&&[...body.children].slice(n).some(r=>r.querySelector('[name=main]').value.trim())&&!confirm('ลดจำนวนวันจะนำเมนูท้ายชุดออกจากฟอร์มนี้ ต้องการลดหรือไม่?')){days.value=old;return;}while(body.children.length<n)add();while(body.children.length>n)body.lastElementChild.remove();}
  initial.forEach(add);resize();days.addEventListener('change',resize);
 }
 const plan=document.getElementById('setPlanForm'),seq=document.getElementById('setSequence');
 function changed(){const apply=document.getElementById('applyPreview'),warn=document.getElementById('previewChanged');if(apply)apply.hidden=true;if(warn)warn.hidden=false;}
 if(plan){plan.addEventListener('input',changed);plan.addEventListener('change',changed);document.getElementById('addSequence').addEventListener('click',()=>{if(seq.children.length>=50)return;const row=seq.firstElementChild.cloneNode(true);row.querySelector('select').value='';seq.appendChild(row);changed()});seq.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const row=b.closest('.lm-seq-row');if(b.hasAttribute('data-remove')){if(seq.children.length>1)row.remove();else row.querySelector('select').value='';}else if(b.dataset.move==='up'&&row.previousElementSibling)seq.insertBefore(row,row.previousElementSibling);else if(b.dataset.move==='down'&&row.nextElementSibling)seq.insertBefore(row.nextElementSibling,row);changed()});}
 document.querySelectorAll('input[data-date]').forEach(el=>el.addEventListener('input',()=>{let v=el.value.replace(/\D/g,'').slice(0,8);el.value=v.length>4?v.slice(0,2)+'/'+v.slice(2,4)+'/'+v.slice(4):v.length>2?v.slice(0,2)+'/'+v.slice(2):v;}));
})();
