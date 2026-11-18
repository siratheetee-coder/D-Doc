// Keep the original controls, form names, ids and event listeners; group only their presentation.
(() => {
 const root=document.querySelector('[data-round-detail]');if(!root)return;
 const priority=['approval','installments','buy','hire'];
 const cards=[...root.children].filter(el=>el.classList.contains('card'));
 const main=cards.filter(el=>priority.includes(el.id));
 const more=cards.filter(el=>!priority.includes(el.id));
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
 function group(key,title){if(groups[key])return groups[key];const d=document.createElement('details');d.className='rd-fold rd-group card';const h=document.createElement('summary');h.textContent=title;d.append(h);root.append(d);groups[key]=d;return d;}
 for(const card of more){
   const title=card.querySelector('summary')?.textContent||'';
   if(card.id==='committee'){group('committee','คณะกรรมการและวันมอบหมายตรวจรับ').append(card);}
   else if(['menus','round-chart'].includes(card.id)||title.includes('คัดลอก')){group('menus','เมนูอาหาร ยอดนักเรียนรายวัน และการคัดลอก').append(card);}
   else if(card.id==='round-info'||title.includes('เพิ่มงวด')){if(title.includes('เพิ่มงวด'))card.id='installment-setup';group('info','ข้อมูลรอบ การแบ่งงวด และขั้นตอนเตรียมงาน').append(card);}
   else{group('docs','เลขที่หนังสือและเอกสารทั้งหมด').append(card);}
 }
 if(steps?.parentElement?.classList.contains('rd-setup'))group('info','ข้อมูลรอบ การแบ่งงวด และขั้นตอนเตรียมงาน').append(steps.parentElement);
 function reveal(hash){if(!hash)return;let el;try{el=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}if(!el)return;for(let p=el;p&&p!==root;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;const fold=el.querySelector(':scope > details.rd-fold');if(fold)fold.open=true;requestAnimationFrame(()=>el.scrollIntoView({block:'start'}));}
 addEventListener('hashchange',()=>reveal(location.hash));
 root.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(a)reveal(a.getAttribute('href'));});
 root.addEventListener('toggle',e=>{if(e.target.tagName==='DETAILS'&&e.target.open)dispatchEvent(new Event('resize'));},true);
 reveal(location.hash);
})();
