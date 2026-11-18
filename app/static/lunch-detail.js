// Keep the original controls, form names, ids and event listeners; group only their presentation.
(() => {
 const root=document.querySelector('[data-round-detail]');if(!root)return;
 const priority=['approval','installments','buy','hire'];
 const cards=[...root.children].filter(el=>el.classList.contains('card'));
 const main=cards.filter(el=>priority.includes(el.id));
 const more=cards.filter(el=>!priority.includes(el.id)&&!el.classList.contains('fs-card'));
 const overview=root.querySelector('.rd-overview');
 let cursor=overview;
 for(const id of priority){const card=main.find(el=>el.id===id);if(card){cursor.after(card);cursor=card;}}
 const names={'round-info':'ข้อมูลรอบและสรุปรายละเอียด','committee':'กรรมการและวันมอบหมายตรวจรับ','round-chart':'ยอดนักเรียนรายวันและกราฟทั้งรอบ','menus':'เมนูอาหารรายวัน / ชุดเมนู','docnos':'เลขที่หนังสือและเอกสาร'};
 for(const card of more){
   const h=card.querySelector(':scope > h2, :scope > div > h2, :scope > h1, :scope > div > h1');
   const title=names[card.id]||h?.textContent.trim()||'รายละเอียดและการตั้งค่า';
   const fold=document.createElement('details');fold.className='rd-fold';
   const summary=document.createElement('summary');summary.textContent=title;
   const content=document.createElement('div');content.className='rd-fold-content';
   while(card.firstChild)content.append(card.firstChild);
   fold.append(summary,content);card.append(fold);cursor.after(card);cursor=card;
 }
 root.querySelectorAll('#buy .bf-rows,#hire .bf-rows').forEach((rows,index)=>{
   const fold=document.createElement('details');fold.className='rd-fold rd-doc-group';
   const summary=document.createElement('summary');summary.textContent='เอกสาร / เลขที่หนังสือ ('+rows.querySelectorAll('.bf-row').length+' รายการ)';
   rows.before(fold);fold.append(summary,rows);
 });
 root.querySelectorAll('form[action$="/loan/repay"],form[action$="/status"]').forEach(form=>{
   if(!form.querySelector('[name="action"][value="undo"],[name="status"][value="จ้างแล้ว"]'))return;
   const fold=document.createElement('details');fold.className='rd-undo';const summary=document.createElement('summary');
   summary.textContent='ย้อนสถานะ / จัดการรายการ';form.before(fold);fold.append(summary,form);
 });
 function menuIcon(name){return '<svg class="icon" aria-hidden="true"><use href="#ic-'+name+'"></use></svg>';}
 root.querySelectorAll('.rd-undo').forEach(menu=>{
   const summary=menu.querySelector(':scope > summary');if(!summary)return;
   summary.innerHTML=menuIcon('settings')+'<span>จัดการ</span><span class="rd-chevron" aria-hidden="true">⌄</span>';
   const body=document.createElement('div');body.className='rd-menu-content';
   while(summary.nextSibling)body.append(summary.nextSibling);
   menu.append(body);
   body.querySelectorAll('button,a').forEach(item=>{if(!item.querySelector('svg'))item.insertAdjacentHTML('afterbegin',menuIcon(item.tagName==='A'?'coins':'undo'));});
   const row=menu.closest('tr[data-iid]'),dateButton=row?.querySelector('.iq-edit');
   if(dateButton){const view=document.createElement('button');view.type='button';view.innerHTML=menuIcon('calendar')+'ดูวันจัดอาหาร';view.addEventListener('click',()=>{menu.open=false;dateButton.click();});body.append(view);}
 });
 root.querySelectorAll('.iq-acts').forEach(cell=>{
   const docs=cell.querySelector(':scope > .lf-docs'),manage=cell.querySelector(':scope > .rd-undo');
   if(!docs||!manage)return;
   const bar=document.createElement('div');bar.className='rd-controls';cell.append(bar);bar.append(docs,manage);
   docs.querySelector('summary').innerHTML=menuIcon('download')+'<span>เอกสาร</span><span class="rd-chevron" aria-hidden="true">⌄</span>';
 });
 root.addEventListener('toggle',e=>{
   const menu=e.target;if(!menu.matches('.rd-undo')||!menu.open)return;
   menu.classList.remove('rd-menu-up');
   requestAnimationFrame(()=>{const body=menu.querySelector('.rd-menu-content');const box=body.getBoundingClientRect();const trigger=menu.querySelector('summary').getBoundingClientRect();if(box.bottom>innerHeight-100 && trigger.top-box.height>80)menu.classList.add('rd-menu-up');});
 },true);
 document.addEventListener('click',e=>root.querySelectorAll('.rd-undo[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;}));
 document.addEventListener('keydown',e=>{if(e.key==='Escape')root.querySelectorAll('.rd-undo[open]').forEach(menu=>{menu.open=false;menu.querySelector('summary').focus();});});
 const steps=root.querySelector('.fs-card');if(steps){const box=document.createElement('details');box.className='rd-fold rd-setup';const s=document.createElement('summary');s.textContent='ขั้นตอนเตรียมงานและตรวจความพร้อม';box.append(s);steps.before(box);box.append(steps);root.append(box);}
 const groups={};
 const INFO_T=root.dataset.mode==='hire'?'ข้อมูลรอบ การแบ่งงวด และขั้นตอนเตรียมงาน':'ข้อมูลรอบและขั้นตอนเตรียมงาน';
 const ORDER=['info','committee','menus','docs'];
 function group(key,title){if(groups[key])return groups[key];const d=document.createElement('details');d.className='rd-fold rd-group card';const h=document.createElement('summary');h.textContent=title;d.append(h);groups[key]=d;return d;}
 for(const card of more){
   const title=card.querySelector('summary')?.textContent||'';
   if(card.id==='committee'){group('committee','คณะกรรมการและวันมอบหมายตรวจรับ').append(card);}
   else if(['menus','round-chart'].includes(card.id)||title.includes('คัดลอก')){group('menus','เมนูอาหาร ยอดนักเรียนรายวัน และการคัดลอก').append(card);}
   else if(card.id==='round-info'||title.includes('เพิ่มงวด')){if(title.includes('เพิ่มงวด'))card.id='installment-setup';group('info',INFO_T).append(card);}
   else{group('docs','เลขที่หนังสือและเอกสารทั้งหมด').append(card);}
 }
 if(steps?.parentElement?.classList.contains('rd-setup'))group('info',INFO_T).append(steps.parentElement);
 // วางกลุ่มตามลำดับงาน: ข้อมูลรอบ > กรรมการ > เมนู > เอกสาร และกลุ่มที่มีการ์ดเดียวไม่ต้องพับซ้อน 2 ชั้น
 const flow=root.querySelector(':scope>#installments,:scope>#buy,:scope>#hire');
 const gaps=new Set([...root.querySelectorAll('.mi-box a[href^="#"]')].map(a=>a.getAttribute('href').slice(1)));
 if(root.querySelector('.fs-card'))gaps.add('round-info');
 const need={info:['round-info'],committee:['committee'],menus:['menus']};
 ORDER.forEach(k=>{const g=groups[k];if(!g)return;
   // เตรียมงาน (ข้อมูลรอบ กรรมการ เมนู) อยู่ก่อนขั้นตอนทำงาน เอกสารอยู่ท้ายสุด
   if(k!=='docs'&&flow)flow.before(g);else root.append(g);
   if((need[k]||[]).some(id=>gaps.has(id))){const b=document.createElement('span');b.className='rd-gap';b.textContent='ยังไม่ครบ';g.querySelector(':scope>summary').append(b);}
   const inner=g.querySelectorAll(':scope>.card>.rd-fold');
   if(g.children.length===2&&inner.length===1){inner[0].open=true;inner[0].classList.add('rd-solo');}});

 // Add visual field cues without changing controls, names, values or form listeners.
 function fieldIcon(text,field){
   const key=(field?.name||field?.dataset.key||'').toLowerCase();
   if(/^(borrower|name|position|role|kind)$/.test(key)||/กรรมการ|นักเรียน|บทบาท|ตำแหน่ง/.test(text))return 'users';
   if(/ยืมเงิน|เงินยืม|จ่ายค่าจ้าง/.test(text))return 'coins';
   if(/date|วันที่|วันเริ่ม|วันสิ้นสุด|วันส่งมอบ|วันตรวจรับ/.test(key+' '+text))return 'calendar';
   if(/จำนวนวัน|จำนวนงวด|จำนวน|อัตรา|ราคาต่อ|days|rate|quantity|n_inst/.test(key+' '+text))return 'calc';
   if(/amount|wage|cost|vat|wht|fine|วงเงิน|ยอด|บาท|ค่าจ้าง|เชื้อเพลิง|ภาษี|ค่าปรับ/.test(key+' '+text))return 'coins';
   if(/vendor|ผู้รับจ้าง|ชื่อร้าน|เจ้าของ/.test(key+' '+text))return 'store';
   if(/borrower|name|position|role|ผู้ยืม|ชื่อ|ตำแหน่ง|บทบาท|กรรมการ|ผู้รับเงิน/.test(key+' '+text))return 'users';
   if(/no|เลข|เอกสาร|หนังสือ|สัญญา/.test(key+' '+text))return 'file';
   if(/เมนู|อาหาร|วัตถุดิบ/.test(text))return 'package';
   if(/สถานะ|status/.test(key+' '+text))return 'clipboard';
   return 'edit';
 }
 const fieldArt={calendar:'home3d/calendar',users:'academic3d/students',store:'home3d/p_hire',coins:'finance3d/wallet-paid',calc:'home3d/f_subsidy',file:'finance3d/document-money',clipboard:'home3d/todo',package:'home3d/p_material',edit:'home3d/t_edit'};
 function cue(name){const span=document.createElement('span');span.className='rd-input-icon rd-icon-'+name;span.setAttribute('aria-hidden','true');const img=document.createElement('img');img.src='/static/images/'+(fieldArt[name]||fieldArt.edit)+'.png';img.alt='';img.width=32;img.height=32;img.decoding='async';span.append(img);return span;}
 root.querySelectorAll('label').forEach(label=>{
   if(label.querySelector('svg,input[type=checkbox],input[type=radio]'))return;
   const field=label.querySelector('input,select,textarea')||label.control||label.parentElement.querySelector('input,select,textarea');
   if(!label.textContent.trim())return;
   label.classList.add('rd-field-label');label.prepend(cue(fieldIcon(label.textContent.trim(),field)));
 });
 root.querySelectorAll('.rd-fold>summary').forEach(summary=>{
   if(summary.querySelector('.rd-summary-name'))return;
   const name=document.createElement('span');name.className='rd-summary-name';
   name.append(cue(fieldIcon(summary.textContent,null)));
   while(summary.firstChild)name.append(summary.firstChild);
   summary.append(name);
 });
 root.querySelectorAll('.bf-step h3,.bf-head h2,.rd-fold-content h2,.rd-fold-content h3').forEach(h=>{
   if(h.querySelector('svg'))return;h.prepend(cue(fieldIcon(h.textContent,null)));
 });
 root.querySelectorAll('.bf-fields').forEach(fields=>{if(!fields.querySelector(':scope > .rd-input-icon'))fields.prepend(cue('file'));});
 function reveal(hash){if(!hash)return;let el;try{el=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}if(!el)return;for(let p=el;p&&p!==root;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;const fold=el.querySelector(':scope > details.rd-fold');if(fold)fold.open=true;requestAnimationFrame(()=>el.scrollIntoView({block:'start'}));}
 addEventListener('hashchange',()=>reveal(location.hash));
 root.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(a)reveal(a.getAttribute('href'));});
 root.addEventListener('toggle',e=>{if(e.target.tagName==='DETAILS'&&e.target.open)dispatchEvent(new Event('resize'));},true);
 reveal(location.hash);
})();
