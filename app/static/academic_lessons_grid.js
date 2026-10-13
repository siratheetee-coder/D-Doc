(()=>{
  const configEl=document.getElementById('lessonConfig');if(!configEl)return;
  const cfg=JSON.parse(configEl.textContent),calendar=document.getElementById('lessonCalendar');
  const identity=document.getElementById('batchLessons');
  const stateKey='lesson-ui:'+['cid','sid','term'].map(k=>identity.elements[k].value).join(':');
  let ui={};try{ui=JSON.parse(sessionStorage.getItem(stateKey)||'{}');}catch{}
  document.querySelectorAll('details.lesson-card[id]').forEach(el=>{
    if(Object.prototype.hasOwnProperty.call(ui.open||{},el.id)&&!Object.keys(cfg.entered).length)el.open=ui.open[el.id];
    el.addEventListener('toggle',()=>{ui.open=ui.open||{};ui.open[el.id]=el.open;persist();});
  });
  function persist(){try{sessionStorage.setItem(stateKey,JSON.stringify(ui));}catch{}}

  // ---- วันและสถานะวันจากปฏิทินปีการศึกษา ----
  const days=cfg.days||{},term=Number(cfg.term)||1;
  const hasTerms=Object.values(days).some(d=>d.t);
  const WD=['อา.','จ.','อ.','พ.','พฤ.','ศ.','ส.'],MS=['ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];
  const dateKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const parseKey=k=>{const [y,m,d]=k.split('-').map(Number);return new Date(y,m-1,d);};
  const label=k=>{const d=parseKey(k);return `${WD[d.getDay()]} ${d.getDate()} ${MS[d.getMonth()]}`;};
  const info=k=>days[k]||{s:'off',t:0};
  // วันของภาคเรียนอื่น หรือนอกภาคเรียน เลือกไม่ได้ (เดิมเลือกได้ แล้วไปนับรวมผิดภาคเรียน)
  function blocked(k){const d=info(k);if(d.s==='off')return 'อยู่นอกภาคเรียน';if(hasTerms&&d.t&&d.t!==term)return `อยู่ในภาคเรียนที่ ${d.t}`;return '';}

  const byDate={};(cfg.events||[]).forEach(e=>{(byDate[e.date]=byDate[e.date]||[]).push(e);});
  const existing=new Set((cfg.events||[]).map(e=>e.date+'|'+e.slot));
  let monthIndex=cfg.months.indexOf(cfg.month),selected=new Set();
  try{JSON.parse(cfg.entered.dates||'[]').forEach(d=>selected.add(d));}catch{}
  if(cfg.months.includes(ui.calendarMonth))monthIndex=cfg.months.indexOf(ui.calendarMonth);
  const hint=document.getElementById('calHint');
  function say(text){if(hint)hint.textContent=text;}

  function choices(){return [...document.querySelectorAll('#slotChoices .slot-choice')].filter(el=>el.querySelector('[type=checkbox]').checked).map(el=>({name:el.querySelector('[type=checkbox]').dataset.slot,minutes:Number(el.querySelector('[type=number]').value)}));}
  function summary(){
    const slots=choices();let fresh=0,dup=0,minutes=0;
    selected.forEach(k=>slots.forEach(s=>{if(existing.has(k+'|'+s.name))dup++;else{fresh++;minutes+=s.minutes||0;}}));
    const h=Math.floor(minutes/60),m=minutes%60,time=(h?`${h} ชม.`:'')+(m?` ${m} นาที`:'')||'0 นาที';
    document.getElementById('batchSummary').textContent=!selected.size?'ยังไม่ได้เลือกวัน':!slots.length?`เลือก ${selected.size} วัน · ยังไม่ได้เลือกคาบ`:
      `เลือก ${selected.size} วัน × ${slots.length} คาบ · เพิ่มใหม่ ${fresh} คาบ (${time.trim()})`+(dup?` · ข้าม ${dup} คาบที่มีอยู่แล้ว`:'');
  }
  function chips(){
    const box=document.getElementById('selectedChips');box.replaceChildren();
    if(!selected.size){const e=document.createElement('span');e.className='ls-empty';e.textContent='ยังไม่ได้เลือกวัน';box.append(e);return;}
    [...selected].sort().forEach(k=>{const b=document.createElement('button');b.type='button';b.className='ls-chip'+(['hol','closed'].includes(info(k).s)?' is-hol':'');
      b.title='เอาวันนี้ออก';b.append(label(k));const x=document.createElement('b');x.textContent='×';b.append(x);
      b.onclick=()=>{selected.delete(k);draw();};box.append(b);});
  }
  function saved(){
    const [y,m]=cfg.months[monthIndex].split('-').map(Number),list=document.getElementById('savedList');
    document.getElementById('savedTitle').textContent=new Date(y,m-1,1).toLocaleDateString('th-TH',{month:'long',year:'numeric'});
    list.replaceChildren();
    const keys=Object.keys(byDate).filter(k=>k.startsWith(cfg.months[monthIndex])).sort();
    if(!keys.length){const e=document.createElement('p');e.className='ls-empty';e.textContent='เดือนนี้ยังไม่มีคาบที่บันทึก';list.append(e);return;}
    keys.forEach(k=>{
      const row=document.createElement('div');row.className='ls-day';const d=info(k);
      const lab=document.createElement('span');lab.className='ls-day-label'+(d.s==='hol'?' is-hol':'');lab.textContent=label(k)+(d.n?` · ${d.n}`:'');row.append(lab);
      byDate[k].forEach(e=>{const p=document.createElement('span');p.className='ls-period';p.append(e.slot+' ');
        const meta=document.createElement('em');meta.textContent=`${e.minutes} นาที · เช็กแล้ว ${e.checked}/${cfg.students}`;p.append(meta);
        const del=document.createElement('button');del.type='button';del.className='ls-del';del.textContent='×';del.title='ลบคาบนี้';del.setAttribute('aria-label',`ลบ ${label(k)} ${e.slot}`);
        del.onclick=()=>remove(e,k);p.append(del);row.append(p);});
      list.append(row);});
  }
  function remove(e,k){
    const msg=e.checked?`${label(k)} ${e.slot} เช็กชื่อแล้ว ${e.checked} คน\nถ้าลบ ผลเช็กชื่อของคาบนี้จะหายไปด้วย ยืนยันลบไหม?`:`ลบ ${label(k)} ${e.slot} ออกจากวันสอน?`;
    if(!confirm(msg))return;
    if(window.lessonGridDirty&&!confirm('มีผลเช็กชื่อที่ยังไม่บันทึก ต้องการทิ้งการแก้ไขแล้วลบคาบหรือไม่?'))return;
    window.lessonGridDirty=false;const f=document.getElementById('removeLesson');
    f.elements.lesson_id.value=e.id;f.elements.force.value=e.checked?'1':'';f.elements.month.value=k.slice(0,7);
    f.dispatchEvent(new Event('submit',{cancelable:true}));f.submit();
  }
  function draw(){
    ui.calendarMonth=cfg.months[monthIndex];persist();
    const [year,month]=cfg.months[monthIndex].split('-').map(Number),today=dateKey(new Date());
    document.getElementById('lessonCalTitle').textContent=new Date(year,month-1,1).toLocaleDateString('th-TH',{month:'long',year:'numeric'});
    calendar.replaceChildren();['จ','อ','พ','พฤ','ศ','ส','อา'].forEach(text=>{const el=document.createElement('span');el.className='wd';el.textContent=text;calendar.append(el);});
    const first=(new Date(year,month-1,1).getDay()+6)%7;
    for(let i=0;i<first;i++)calendar.append(document.createElement('span'));
    for(let day=1;day<=new Date(year,month,0).getDate();day++){
      const key=dateKey(new Date(year,month-1,day)),d=info(key),stop=blocked(key),b=document.createElement('button');b.type='button';
      b.append(String(day));
      const tag=d.s==='hol'?(d.n||'วันหยุด'):stop?(d.s==='off'?'นอกเทอม':`เทอม ${d.t}`):'';
      if(tag){const s=document.createElement('small');s.textContent=tag;b.append(s);}
      const n=(byDate[key]||[]).length;if(n){const c=document.createElement('span');c.className='cnt';c.textContent=n;b.append(c);}
      b.className=(stop?'s-off':'s-'+d.s)+(selected.has(key)?' selected':'')+(key===today?' today':'');
      b.setAttribute('aria-pressed',selected.has(key));
      b.setAttribute('aria-label',`${label(key)}${d.n?' '+d.n:''}${n?` มี ${n} คาบแล้ว`:''}${stop?' '+stop:''}`);
      b.onclick=()=>{
        if(stop){say(`${label(key)} ${stop} เลือกไม่ได้ในหน้าภาคเรียนที่ ${term}`);return;}
        if(selected.has(key)){selected.delete(key);say(`เอา ${label(key)} ออกแล้ว`);}
        else{
          if(d.s==='hol'&&!confirm(`${label(key)} เป็นวันหยุด (${d.n||'วันหยุด'})\nต้องการเลือกเป็นวันสอนชดเชยไหม?`))return;
          if(d.s==='closed'&&!confirm(`${label(key)} ไม่ใช่วันเปิดเรียนตามปฏิทินปีการศึกษา\nต้องการเลือกเป็นวันสอนชดเชยไหม?`))return;
          selected.add(key);say(`เลือก ${label(key)} แล้ว`);
        }
        draw();
      };
      calendar.append(b);
    }
    document.getElementById('lessonCalPrev').disabled=monthIndex===0;document.getElementById('lessonCalNext').disabled=monthIndex===cfg.months.length-1;
    chips();summary();saved();
  }
  document.getElementById('lessonCalPrev').onclick=()=>{if(monthIndex>0){monthIndex--;draw();}};
  document.getElementById('lessonCalNext').onclick=()=>{if(monthIndex<cfg.months.length-1){monthIndex++;draw();}};
  // "วันนี้" แค่เปิดเดือนนี้ ไม่เลือกให้เอง (เดิมเลือกวันนี้ทันที แม้เป็นวันหยุดหรือนอกภาคเรียน)
  document.getElementById('lessonCalToday').onclick=()=>{const now=dateKey(new Date()),index=cfg.months.indexOf(now.slice(0,7));if(index<0){say('วันนี้ไม่อยู่ในปีการศึกษานี้');return;}monthIndex=index;draw();say('กดวันที่เพื่อเลือก');};
  document.getElementById('clearDates').onclick=()=>{selected.clear();draw();};
  const scope=document.getElementById('quickScope');
  if(scope&&!hasTerms){scope.querySelector('option[value=term]').disabled=true;scope.title='ตั้งวันเปิด-ปิดภาคเรียนในปฏิทินปีการศึกษาก่อน';}
  document.querySelectorAll('.ls-wd').forEach(btn=>btn.onclick=()=>{
    const wd=Number(btn.dataset.wd),month=cfg.months[monthIndex],all=scope&&scope.value==='term';
    const pool=Object.keys(days).filter(k=>(all?true:k.startsWith(month))&&parseKey(k).getDay()===wd&&!blocked(k)&&(!all||info(k).t===term));
    const pick=pool.filter(k=>info(k).s==='open'),skipped=pool.length-pick.length;
    if(!pick.length){say(`ไม่มีวัน ${btn.textContent} ที่เป็นวันเปิดเรียน${all?'ในภาคเรียนนี้':'ในเดือนนี้'}`);return;}
    const allOn=pick.every(k=>selected.has(k));
    pick.forEach(k=>allOn?selected.delete(k):selected.add(k));
    draw();say(`${allOn?'เอาออก':'เลือก'}ทุกวัน ${btn.textContent} ${pick.length} วัน${skipped?` · ข้ามวันหยุด/วันปิดเรียน ${skipped} วัน`:''}`);
  });
  document.getElementById('slotChoices').addEventListener('input',summary);
  function addSlot(name,minutes=50,checked=true){
    const label=document.createElement('label');label.className='slot-choice';
    const check=document.createElement('input');check.type='checkbox';check.checked=checked;check.dataset.slot=name;
    const text=document.createElement('span');text.textContent=name;
    const number=document.createElement('input');number.type='number';number.min=1;number.max=720;number.value=minutes;number.setAttribute('aria-label','นาที '+name);
    const unit=document.createElement('small');unit.textContent='นาที';label.append(check,text,number,unit);document.getElementById('slotChoices').append(label);
  }
  try{JSON.parse(cfg.entered.slots||JSON.stringify(ui.slots||[])).forEach(slot=>{const box=[...document.querySelectorAll('[data-slot]')].find(el=>el.dataset.slot===slot.name);if(box){box.checked=true;box.parentElement.querySelector('[type=number]').value=slot.minutes;}else addSlot(slot.name,slot.minutes);});}catch{}
  document.getElementById('addSlot').onclick=()=>{const input=document.getElementById('customSlot'),name=input.value.trim();if(!name)return;if([...document.querySelectorAll('[data-slot]')].some(el=>el.dataset.slot===name)){alert('มีชื่อคาบนี้แล้ว');return;}addSlot(name);input.value='';summary();};
  document.getElementById('batchLessons').addEventListener('submit',event=>{const slots=choices();if(!selected.size||!slots.length||slots.some(s=>!Number.isInteger(s.minutes)||s.minutes<1||s.minutes>720)){event.preventDefault();alert('เลือกวันและคาบ พร้อมระบุนาทีต่อคาบให้ถูกต้อง');return;}if(window.lessonGridDirty&&!confirm('มีผลเช็กชื่อที่ยังไม่บันทึก ต้องการออกจากตารางเพื่อเพิ่มวันสอนหรือไม่?')){event.preventDefault();return;}window.lessonGridDirty=false;document.getElementById('batchDates').value=JSON.stringify([...selected].sort());document.getElementById('batchSlots').value=JSON.stringify(slots);});
  document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
    if(event.defaultPrevented)return;
    ui.slots=choices();ui.scroll=window.scrollY;ui.restore=true;
    ui.open=Object.fromEntries([...document.querySelectorAll('details.lesson-card[id]')].map(el=>[el.id,el.open]));persist();
  }));
  if(ui.restore){ui.restore=false;persist();window.addEventListener('load',()=>requestAnimationFrame(()=>window.scrollTo(0,ui.scroll||0)),{once:true});}
  draw();

  // ---- ตารางเช็กชื่อ ----
  const cells=[...document.querySelectorAll('.grid-mark')],gridForm=document.getElementById('gridMarks');
  function update(){
    let count=0;const filled={};
    cells.forEach(c=>{c.dataset.state=c.value;const changed=c.value!==c.dataset.original;c.classList.toggle('changed',changed);if(changed)count++;if(c.value)filled[c.dataset.lesson]=(filled[c.dataset.lesson]||0)+1;});
    document.querySelectorAll('.lg-prog').forEach(p=>{const n=filled[p.dataset.lesson]||0;p.textContent=`${n}/${cfg.students}`;p.classList.toggle('full',n===cfg.students&&n>0);});
    window.lessonGridDirty=count>0;const status=document.getElementById('gridStatus');if(status)status.textContent=count?`แก้ไข ${count} ช่อง · ยังไม่บันทึก`:'ยังไม่มีการแก้ไข';
  }
  // Restore the user's edits after validation errors without changing server baselines.
  try{JSON.parse(cfg.entered.changes||'[]').forEach(item=>{const cell=cells.find(c=>c.dataset.lesson===String(item.lesson_id)&&c.dataset.student===String(item.student_id));if(cell)cell.value=item.mark;});}catch{}
  cells.forEach(c=>c.addEventListener('change',update));
  document.querySelectorAll('.grid-all').forEach(b=>b.onclick=()=>{if(cells.some(c=>c.dataset.lesson===b.dataset.lesson&&c.value&&c.value!=='/')&&!confirm('เปลี่ยนสถานะทุกคนในคาบนี้เป็นมา?'))return;cells.filter(c=>c.dataset.lesson===b.dataset.lesson).forEach(c=>c.value='/');update();});
  document.querySelectorAll('.grid-copy').forEach(b=>b.onclick=()=>{const targets=cells.filter(c=>c.dataset.lesson===b.dataset.to);if(targets.some(c=>c.value)&&!confirm('แทนที่สถานะคาบนี้ด้วยคาบก่อนหน้า?'))return;targets.forEach(c=>{const source=cells.find(s=>s.dataset.lesson===b.dataset.from&&s.dataset.student===c.dataset.student);if(source)c.value=source.value;});update();});
  if(gridForm)gridForm.addEventListener('submit',()=>{document.getElementById('gridChanges').value=JSON.stringify(cells.filter(c=>c.value!==c.dataset.original).map(c=>({lesson_id:Number(c.dataset.lesson),student_id:Number(c.dataset.student),mark:c.value,old:c.dataset.original})));window.lessonGridDirty=false;});
  window.addEventListener('beforeunload',event=>{if(window.lessonGridDirty){event.preventDefault();event.returnValue='';}});update();
})();
