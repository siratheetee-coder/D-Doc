(() => {
 'use strict';
 const source=document.getElementById('se-data');if(!source)return;
 const data=JSON.parse(source.textContent),events=data.events,dialog=document.getElementById('se-editor'),form=document.getElementById('se-event-form');
 let filterKind='';
 const be=iso=>{const a=iso.split('-');return `${a[2]}/${a[1]}/${Number(a[0])+543}`;};let daySelected=data.today.slice(0,7)===data.initial_day.slice(0,7)?data.today:data.initial_day;
 function selectEvent(id,update=true){
  const e=events.find(x=>String(x.id)===String(id));if(!e)return;
  document.querySelectorAll('[data-event-detail]').forEach(el=>el.hidden=el.dataset.eventDetail!==String(id));
  document.querySelectorAll('[data-event-link]').forEach(el=>el.classList.toggle('is-selected',el.dataset.eventLink===String(id)));
  if(update){const url=new URL(location.href);url.searchParams.set('event',id);history.replaceState(null,'',url);}
  if(matchMedia('(max-width:900px)').matches)document.getElementById('se-details').scrollIntoView({block:'start',behavior:'smooth'});
 }
 document.addEventListener('click',e=>{const a=e.target.closest('[data-event-link]');if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();selectEvent(a.dataset.eventLink);});
 function dayDetails(iso){daySelected=iso;const panel=document.getElementById('se-day-results'),list=document.getElementById('se-day-events');panel.hidden=false;document.getElementById('se-day-title').textContent='กิจกรรมวันที่ '+be(iso);list.replaceChildren();
  const rows=events.filter(e=>e.start<=iso&&e.end>=iso&&(!filterKind||e.kind===filterKind));
  for(const e of rows){const a=document.createElement('a');a.className='se-day-result';a.href=e.href;a.textContent=e.title+' · '+e.time_label;a.addEventListener('click',x=>{if(x.ctrlKey||x.metaKey||x.shiftKey)return;x.preventDefault();selectEvent(e.id);});list.append(a);}
  if(!rows.length){const p=document.createElement('p');p.className='muted';p.textContent='ยังไม่มีกิจกรรมในวันนี้';list.append(p);}
  if(matchMedia('(max-width:900px)').matches)panel.scrollIntoView({block:'start',behavior:'smooth'});
 }
 document.querySelectorAll('[data-se-day]').forEach(b=>b.addEventListener('click',()=>dayDetails(b.dataset.seDay)));
 const views=document.querySelectorAll('[data-se-view]');
 function setView(value){document.getElementById('se-month-view').hidden=value!=='month';document.getElementById('se-list-view').hidden=value!=='list';views.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.seView===value)));}
 views.forEach(b=>b.addEventListener('click',()=>setView(b.dataset.seView)));if(matchMedia('(max-width:650px)').matches)setView('list');
 function renderChips(){document.querySelectorAll('[data-day-entries]').forEach(box=>{const iso=box.dataset.dayEntries,rows=events.filter(e=>e.start<=iso&&e.end>=iso&&(!filterKind||e.kind===filterKind));box.replaceChildren();for(const e of rows.slice(0,2)){const a=document.createElement('a');a.className='se-event-chip se-kind-'+e.kind;a.href=e.href;a.dataset.eventLink=e.id;a.dataset.kind=e.kind;a.textContent=e.title;box.append(a);}if(rows.length>2){const b=document.createElement('button');b.type='button';b.className='se-more';b.textContent='อีก '+(rows.length-2)+' กิจกรรม';b.addEventListener('click',()=>dayDetails(iso));box.append(b);}});}
 renderChips();
 document.getElementById('se-kind-filter').addEventListener('change',e=>{filterKind=e.target.value;renderChips();let n=0;document.querySelectorAll('[data-kind]').forEach(el=>{el.hidden=!!e.target.value&&el.dataset.kind!==e.target.value;if(!el.hidden&&el.classList.contains('se-list-event'))n++;});document.getElementById('se-filter-empty').hidden=!!n;});
 if(!dialog||!form)return;
 let opener;
 function fields(){const all=form.elements.all_day.checked;document.getElementById('se-time-fields').hidden=all;for(const n of ['start_time','end_time']){form.elements[n].disabled=all;form.elements[n].required=!all;}
  document.querySelectorAll('[data-se-targets]').forEach(box=>{const on=box.dataset.seTargets===form.elements.audience.value;box.hidden=!on;box.querySelectorAll('input').forEach(el=>el.disabled=!on);});form.elements.audience.setCustomValidity('');}
 function openEditor(obj={},trigger){opener=trigger;form.reset();document.getElementById('se-editor-title').textContent=(obj.id||obj.event_id)?'แก้ไขกิจกรรมโรงเรียน':'เพิ่มกิจกรรมโรงเรียน';
  for(const n of ['title','kind','audience','location','organizer','note','version'])if(obj[n]!=null)form.elements[n].value=obj[n];
  form.elements.event_id.value=obj.id||obj.event_id||'';
  form.elements.start_date.value=obj.start_input||obj.start_date||be(daySelected);
  form.elements.end_date.value=obj.end_input||obj.end_date||form.elements.start_date.value;
  form.elements.all_day.checked=obj.all_day==null?true:(obj.all_day===true||obj.all_day==='1');
  for(const n of ['start_time','end_time'])form.elements[n].value=obj[n]||'';
  const selected=(obj.targets||(obj.audience==='class'?obj.classes:obj.levels)||[]).map(String);
  form.querySelectorAll('[name=levels],[name=classes]').forEach(el=>el.checked=selected.includes(el.value));
  fields();dialog.showModal();form.elements.title.focus();
 }
 document.querySelectorAll('[data-event-new]').forEach(b=>b.addEventListener('click',()=>openEditor({},b)));
 document.querySelectorAll('[data-event-edit]').forEach(b=>b.addEventListener('click',()=>openEditor(events.find(e=>String(e.id)===b.dataset.eventEdit),b)));
 document.getElementById('se-add-on-day').addEventListener('click',e=>openEditor({},e.currentTarget));
 document.querySelectorAll('[data-se-close]').forEach(b=>b.addEventListener('click',()=>dialog.close()));dialog.addEventListener('close',()=>opener?.focus());
 form.elements.all_day.addEventListener('change',fields);form.elements.audience.addEventListener('change',fields);
 form.querySelectorAll('[name=levels],[name=classes]').forEach(el=>el.addEventListener('change',()=>form.elements.audience.setCustomValidity('')));
 form.addEventListener('submit',e=>{const a=form.elements.audience;if(a.value!=='school'&&!form.querySelector(`[name=${a.value==='level'?'levels':'classes'}]:checked`)){a.setCustomValidity('เลือกผู้เข้าร่วมอย่างน้อยหนึ่งรายการ');a.reportValidity();e.preventDefault();return;}if(form.checkValidity()){const b=form.querySelector('[type=submit]');b.disabled=true;b.textContent='กำลังบันทึก…';}});
 fields();if(data.form)openEditor(data.form);
})();
