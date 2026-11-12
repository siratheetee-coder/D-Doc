(()=>{
  // ---- ตั้งค่าคาบสอน: 1 สอนวันไหน 2 คาบไหนในแต่ละวัน 3 ช่วงเวลา ----
  const configEl=document.getElementById('lessonConfig'),form=document.getElementById('batchLessons');
  if(!configEl||!form)return;
  const cfg=JSON.parse(configEl.textContent),calendar=document.getElementById('lessonCalendar');
  const days=cfg.days||{},term=Number(cfg.term)||1;
  const hasTerms=Object.values(days).some(d=>d.t);
  const WD=['อา.','จ.','อ.','พ.','พฤ.','ศ.','ส.'],MS=['ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];
  const DAYNAME={'1':'จันทร์','2':'อังคาร','3':'พุธ','4':'พฤหัสบดี','5':'ศุกร์','60':'เสาร์/อาทิตย์'};
  const dateKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const parseKey=k=>{const [y,m,d]=k.split('-').map(Number);return new Date(y,m-1,d);};
  const label=k=>{const d=parseKey(k);return `${WD[d.getDay()]} ${d.getDate()} ${MS[d.getMonth()]}`;};
  const monthName=m=>{const [y,mm]=m.split('-').map(Number);return new Date(y,mm-1,1).toLocaleDateString('th-TH',{month:'long',year:'numeric'});};
  const info=k=>days[k]||{s:'off',t:0};
  const keyOf=k=>{const w=parseKey(k).getDay();return w===0||w===6?'60':String(w);};
  // วันของภาคเรียนอื่น หรือนอกภาคเรียน เลือกไม่ได้
  function blocked(k){const d=info(k);if(d.s==='off')return 'อยู่นอกภาคเรียน';if(hasTerms&&d.t&&d.t!==term)return `อยู่ในภาคเรียนที่ ${d.t}`;return '';}
  const byDate={};(cfg.events||[]).forEach(e=>{(byDate[e.date]=byDate[e.date]||[]).push(e);});
  const existing=new Set((cfg.events||[]).map(e=>e.date+'|'+e.slot));
  const hint=document.getElementById('calHint');
  function say(text){if(hint)hint.textContent=text;}

  // pattern: {"1": Set(คาบ)} วันที่เลือกแล้วแต่ยังไม่มีคาบเก็บเป็น Set ว่าง
  // ค่าเริ่มต้นมาจากคาบที่บันทึกไว้แล้วของเทอมนี้ (กดแก้ตั้งค่าจึงเห็นค่าเดิม)
  const pattern={};
  const minEls=()=>[...document.querySelectorAll('#slotMinutes .ls-min')];
  const slotNames=()=>minEls().map(el=>el.dataset.slot);
  const minutesOf=n=>{const el=minEls().find(x=>x.dataset.slot===n);return el?Number(el.querySelector('input').value):50;};
  let start=null;
  try{start=JSON.parse(cfg.entered.slots||'null');}catch{}
  if(Array.isArray(start)){start.forEach(s=>{if(!Array.isArray(s.wd))return;s.wd.forEach(w=>{const k=w===0||w===6?'60':String(w);(pattern[k]=pattern[k]||new Set()).add(s.name);});});}
  else Object.entries(cfg.pattern||{}).forEach(([k,v])=>pattern[k]=new Set(v));

  function choices(){
    const out={};
    Object.entries(pattern).forEach(([k,set])=>set.forEach(n=>{const o=out[n]=out[n]||{name:n,minutes:minutesOf(n),wd:[]};o.wd.push(...(k==='60'?[6,0]:[Number(k)]));}));
    // สอนชดเชยเสาร์/อาทิตย์ แต่ยังไม่ได้เลือกคาบของวันนั้น: ใช้คาบเดียวกับวันธรรมดาให้เอง
    if(!(pattern['60']&&pattern['60'].size))Object.values(out).forEach(o=>{if(!o.wd.includes(6))o.wd.push(6,0);});
    return Object.values(out);
  }
  const slotsFor=(k,slots)=>slots.filter(s=>s.wd.includes(parseKey(k).getDay()));

  // วันที่จะเพิ่ม = วันเปิดเรียนในช่วงที่เลือกที่ตรงกับวันที่มีคาบ (ไม่รวมเสาร์อาทิตย์)
  //   + วันที่กดเพิ่มเองในปฏิทิน - วันที่กดงดสอน
  const added=new Set(),removed=new Set();
  try{JSON.parse(cfg.entered.dates||'[]').forEach(d=>added.add(d));}catch{}
  const scopeSel=document.getElementById('scopeMonth');
  [...scopeSel.options].forEach(o=>o.textContent=monthName(o.value));
  const scope=()=>(form.querySelector('input[name=_scope]:checked')||{}).value||'month';
  function auto(){
    const all=scope()==='term',m=scopeSel.value,keys=new Set(Object.keys(pattern).filter(k=>k!=='60'&&pattern[k].size));
    return Object.keys(days).filter(k=>(all?info(k).t===term:k.startsWith(m))&&!blocked(k)&&info(k).s==='open'&&keys.has(keyOf(k)));
  }
  function selected(){const s=new Set(auto());added.forEach(k=>s.add(k));removed.forEach(k=>s.delete(k));return s;}

  // ---- ข้อ 1 และ 2 ----
  function renderDays(){
    document.querySelectorAll('.ls-dayopt').forEach(b=>{const on=!!pattern[b.dataset.wd];b.classList.toggle('on',on);b.setAttribute('aria-pressed',on);});
    const box=document.getElementById('dayRows');box.replaceChildren();
    const keys=['1','2','3','4','5','60'].filter(k=>pattern[k]);
    if(!keys.length){const p=document.createElement('p');p.className='ls-empty';p.textContent='เลือกวันในข้อ 1 ก่อน';box.append(p);}
    keys.forEach(k=>{
      const row=document.createElement('div');row.className='ls-dayrow';
      const lab=document.createElement('b');lab.textContent=DAYNAME[k];row.append(lab);
      const wrap=document.createElement('div');wrap.className='ls-slots';
      slotNames().forEach(n=>{const b=document.createElement('button');b.type='button';b.className='ls-slot'+(pattern[k].has(n)?' on':'');
        b.textContent=n;b.setAttribute('aria-pressed',pattern[k].has(n));b.setAttribute('aria-label',`${DAYNAME[k]} ${n}`);
        b.onclick=()=>{pattern[k].has(n)?pattern[k].delete(n):pattern[k].add(n);renderDays();update();};wrap.append(b);});
      row.append(wrap);
      if(!pattern[k].size&&k!=='60'){const w=document.createElement('small');w.className='ls-need';w.textContent='ยังไม่ได้เลือกคาบ';row.append(w);}
      if(k==='60'){const w=document.createElement('small');w.className='ls-hint';w.textContent=pattern[k].size?'กดเลือกวันเสาร์/อาทิตย์ที่สอนชดเชยในปฏิทินข้อ 3':'ไม่เลือกคาบก็ได้ ระบบใช้คาบเดียวกับวันธรรมดา แล้วกดวันชดเชยในปฏิทินข้อ 3';row.append(w);const cb=document.getElementById('calBox');if(cb)cb.open=true;}
      box.append(row);});
  }
  document.querySelectorAll('.ls-dayopt').forEach(b=>b.onclick=()=>{const k=b.dataset.wd;
    if(pattern[k]){if(pattern[k].size&&!confirm(`เอา${DAYNAME[k]}ออก คาบที่เลือกไว้ของวันนี้จะหายไปด้วย?`))return;delete pattern[k];}else pattern[k]=new Set();
    renderDays();update();});
  function addSlot(name){
    const l=document.createElement('label');l.className='ls-min';l.dataset.slot=name;
    const t=document.createElement('span');t.textContent=name;const n=document.createElement('input');n.type='number';n.min=1;n.max=720;n.value=50;n.setAttribute('aria-label','นาที '+name);
    const u=document.createElement('small');u.textContent='นาที';l.append(t,n,u);document.getElementById('slotMinutes').append(l);
  }
  document.getElementById('addSlot').onclick=()=>{const input=document.getElementById('customSlot'),name=input.value.trim();if(!name)return;
    if(slotNames().includes(name)){alert('มีชื่อคาบนี้แล้ว');return;}addSlot(name);input.value='';renderDays();update();};
  // คาบที่ติ๊กไว้แต่ไม่อยู่ในรายการคาบของโรงเรียน (เช่น สอนเสริม) เพิ่มให้เลือกได้
  Object.values(pattern).forEach(set=>set.forEach(n=>{if(!slotNames().includes(n))addSlot(n);}));

  // ---- ข้อ 3 ปฏิทิน (ปรับวันพิเศษ) ----
  let monthIndex=Math.max(0,cfg.months.indexOf(scopeSel.value));
  function draw(){
    const sel=selected(),[year,month]=cfg.months[monthIndex].split('-').map(Number),today=dateKey(new Date());
    document.getElementById('lessonCalTitle').textContent=monthName(cfg.months[monthIndex]);
    calendar.replaceChildren();['จ','อ','พ','พฤ','ศ','ส','อา'].forEach(text=>{const el=document.createElement('span');el.className='wd';el.textContent=text;calendar.append(el);});
    const first=(new Date(year,month-1,1).getDay()+6)%7;
    for(let i=0;i<first;i++)calendar.append(document.createElement('span'));
    for(let day=1;day<=new Date(year,month,0).getDate();day++){
      const key=dateKey(new Date(year,month-1,day)),d=info(key),stop=blocked(key),b=document.createElement('button');b.type='button';
      b.append(String(day));
      const tag=d.s==='hol'?(d.n||'วันหยุด'):stop?(d.s==='off'?'นอกเทอม':`เทอม ${d.t}`):'';
      if(tag){const s=document.createElement('small');s.textContent=tag;b.append(s);}
      const n=(byDate[key]||[]).length;if(n){const c=document.createElement('span');c.className='cnt';c.textContent=n;b.append(c);}
      b.className=(stop?'s-off':'s-'+d.s)+(sel.has(key)?' selected':'')+(key===today?' today':'');
      b.setAttribute('aria-pressed',sel.has(key));
      b.setAttribute('aria-label',`${label(key)}${d.n?' '+d.n:''}${n?` มี ${n} คาบแล้ว`:''}${stop?' '+stop:''}`);
      b.onclick=()=>{
        if(stop){say(`${label(key)} ${stop} เลือกไม่ได้ในภาคเรียนที่ ${term}`);return;}
        if(sel.has(key)){added.delete(key);removed.add(key);say(`งดสอน ${label(key)}`);}
        else{
          if(d.s==='hol'&&!confirm(`${label(key)} เป็นวันหยุด (${d.n||'วันหยุด'})\nต้องการเพิ่มเป็นวันสอนชดเชยไหม?`))return;
          if(d.s==='closed'&&!confirm(`${label(key)} ไม่ใช่วันเปิดเรียนตามปฏิทินปีการศึกษา\nต้องการเพิ่มเป็นวันสอนชดเชยไหม?`))return;
          removed.delete(key);added.add(key);
          say(slotsFor(key,choices()).length?`เพิ่ม ${label(key)} แล้ว`:`เพิ่ม ${label(key)} แล้ว เลือกคาบในข้อ 2 ก่อน`);
        }
        update();
      };
      calendar.append(b);
    }
    document.getElementById('lessonCalPrev').disabled=monthIndex===0;document.getElementById('lessonCalNext').disabled=monthIndex===cfg.months.length-1;
    saved();
  }
  function saved(){
    const list=document.getElementById('savedList');
    document.getElementById('savedTitle').textContent=monthName(cfg.months[monthIndex]);
    list.replaceChildren();
    const keys=Object.keys(byDate).filter(k=>k.startsWith(cfg.months[monthIndex])).sort();
    if(!keys.length){const e=document.createElement('p');e.className='ls-empty';e.textContent='เดือนนี้ยังไม่มีคาบที่บันทึก';list.append(e);return;}
    keys.forEach(k=>{
      const row=document.createElement('div');row.className='ls-day';const d=info(k);
      const lab=document.createElement('span');lab.className='ls-day-label'+(d.s==='hol'?' is-hol':'');lab.textContent=label(k)+(d.n?` ${d.n}`:'');row.append(lab);
      byDate[k].forEach(e=>{const p=document.createElement('span');p.className='ls-period';p.append(e.slot+' ');
        const meta=document.createElement('em');meta.textContent=`${e.minutes} นาที เช็กแล้ว ${e.checked}/${cfg.students}`;p.append(meta);
        const del=document.createElement('button');del.type='button';del.className='ls-del';del.textContent='×';del.title='ลบคาบนี้';del.setAttribute('aria-label',`ลบ ${label(k)} ${e.slot}`);
        del.onclick=()=>remove(e,k);p.append(del);row.append(p);});
      list.append(row);});
  }
  function remove(e,k){
    const msg=e.checked?`${label(k)} ${e.slot} เช็กชื่อแล้ว ${e.checked} คน\nถ้าลบ ผลเช็กชื่อของคาบนี้จะหายไปด้วย ยืนยันลบไหม?`:`ลบ ${label(k)} ${e.slot} ออกจากวันสอน?`;
    if(!confirm(msg))return;
    const f=document.getElementById('removeLesson');
    f.elements.lesson_id.value=e.id;f.elements.force.value=e.checked?'1':'';f.elements.month.value=k.slice(0,7);f.submit();
  }
  document.getElementById('lessonCalPrev').onclick=()=>{if(monthIndex>0){monthIndex--;draw();}};
  document.getElementById('lessonCalNext').onclick=()=>{if(monthIndex<cfg.months.length-1){monthIndex++;draw();}};
  form.querySelectorAll('input[name=_scope]').forEach(r=>r.addEventListener('change',update));
  scopeSel.addEventListener('change',()=>{form.querySelector('input[name=_scope][value=month]').checked=true;monthIndex=Math.max(0,cfg.months.indexOf(scopeSel.value));update();});
  document.getElementById('slotMinutes').addEventListener('input',update);

  // คาบเดิมในช่วงเวลาที่เลือกที่ไม่ตรงกับตั้งค่าใหม่ = จะถูกลบตอนบันทึก (คาบนอกช่วงไม่แตะ)
  function plan(){
    const slots=choices(),sel=selected(),want=new Set(),all=scope()==='term',m=scopeSel.value;
    let fresh=0,minutes=0;
    sel.forEach(k=>slotsFor(k,slots).forEach(s=>{want.add(k+'|'+s.name);if(!existing.has(k+'|'+s.name)){fresh++;minutes+=s.minutes||0;}}));
    const inRange=k=>all?info(k).t===term:k.startsWith(m);
    const drop=(cfg.events||[]).filter(e=>inRange(e.date)&&!want.has(e.date+'|'+e.slot));
    return {slots,sel,want,fresh,minutes,drop,keep:(cfg.events||[]).filter(e=>want.has(e.date+'|'+e.slot)).length};
  }
  const hm=min=>{const h=Math.floor(min/60),m=min%60;return ((h?`${h} ชั่วโมง`:'')+(m?` ${m} นาที`:'')).trim()||'0 นาที';};
  function update(){
    const p=plan(),checked=p.drop.filter(e=>e.checked).length,box=document.getElementById('batchSummary');
    let text;
    if(!Object.keys(pattern).length&&!p.drop.length)text='เลือกวันที่สอนในข้อ 1';
    else if(!p.fresh&&!p.drop.length)text=p.keep?`คาบในช่วงนี้ตรงกับที่ตั้งไว้ครบแล้ว ${p.keep} คาบ ไม่มีอะไรต้องเปลี่ยน`:(!p.slots.length?'เลือกคาบของแต่ละวันในข้อ 2':'ช่วงเวลาที่เลือกไม่มีวันเปิดเรียนที่ตรงกับวันสอน');
    else{
      const parts=[];
      if(p.fresh)parts.push(`เพิ่ม ${p.fresh} คาบ (${hm(p.minutes)})`);
      if(p.drop.length)parts.push(`ลบ ${p.drop.length} คาบเดิมที่ไม่ตรงกับที่ตั้งใหม่`+(checked?` (เช็คชื่อแล้ว ${checked} คาบ ผลเช็คชื่อจะหายด้วย)`:''));
      text='เมื่อกดบันทึก ระบบจะ'+parts.join(' และ ');
      if(p.keep)text+=` คาบที่ตรงอยู่แล้ว ${p.keep} คาบ ไม่เปลี่ยน`;
    }
    box.textContent=text;box.classList.toggle('is-warn',!!checked);
    document.getElementById('batchSubmit').disabled=!(p.fresh||p.drop.length);
    draw();
  }
  form.addEventListener('submit',event=>{
    const p=plan(),sel=[...p.sel].filter(k=>slotsFor(k,p.slots).length),checked=p.drop.filter(e=>e.checked);
    if(p.slots.some(s=>!Number.isInteger(s.minutes)||s.minutes<1||s.minutes>720)){event.preventDefault();alert('นาทีต่อคาบต้องเป็นตัวเลข 1 ถึง 720');return;}
    if(!sel.length&&!p.drop.length){event.preventDefault();return;}
    if(checked.length&&!confirm(`จะลบ ${p.drop.length} คาบเดิม ในนั้นเช็คชื่อแล้ว ${checked.length} คาบ\nผลเช็คชื่อของคาบเหล่านั้นจะหายไปด้วย ยืนยันไหม?`)){event.preventDefault();return;}
    document.getElementById('batchDates').value=JSON.stringify(sel.sort());document.getElementById('batchSlots').value=JSON.stringify(p.slots);
    document.getElementById('batchRemove').value=JSON.stringify(p.drop.map(e=>e.id));document.getElementById('batchForce').value=checked.length?'1':'';
  });
  const clearAll=document.getElementById('removeAll');
  if(clearAll)clearAll.addEventListener('submit',event=>{
    const ev=cfg.events||[],checked=ev.filter(e=>e.checked).length;
    if(!confirm(`ลบคาบทั้งหมดของภาคเรียนนี้ ${ev.length} คาบ`+(checked?`\nในนั้นเช็คชื่อแล้ว ${checked} คาบ ผลเช็คชื่อจะหายไปด้วย`:'')+'\nยืนยันไหม?')){event.preventDefault();return;}
    clearAll.elements.force.value=checked?'1':'';
  });
  renderDays();update();
})();

(()=>{
  const configEl=document.getElementById('lessonConfig');if(!configEl)return;
  const cfg=JSON.parse(configEl.textContent);
  // ---- ตารางเช็กชื่อ ----
  const cells=[...document.querySelectorAll('.grid-mark')],gridForm=document.getElementById('gridMarks');
  function update(){
    let count=0;const filled={};
    cells.forEach(c=>{c.dataset.state=c.value;const changed=c.value!==c.dataset.original;c.classList.toggle('changed',changed);if(changed)count++;if(c.value)filled[c.dataset.lesson]=(filled[c.dataset.lesson]||0)+1;});
    document.querySelectorAll('.lg-prog').forEach(p=>{const n=filled[p.dataset.lesson]||0;p.textContent=`${n}/${cfg.students}`;p.classList.toggle('full',n===cfg.students&&n>0);});
    window.lessonGridDirty=count>0;const status=document.getElementById('gridStatus');if(status)status.textContent=count?`แก้ไข ${count} ช่อง ยังไม่บันทึก`:'ยังไม่มีการแก้ไข';
  }
  // Restore the user's edits after validation errors without changing server baselines.
  try{JSON.parse(cfg.entered.changes||'[]').forEach(item=>{const cell=cells.find(c=>c.dataset.lesson===String(item.lesson_id)&&c.dataset.student===String(item.student_id));if(cell)cell.value=item.mark;});}catch{}
  cells.forEach(c=>c.addEventListener('change',update));
  document.querySelectorAll('.grid-all').forEach(b=>b.onclick=()=>{if(cells.some(c=>c.dataset.lesson===b.dataset.lesson&&c.value&&c.value!=='/')&&!confirm('เปลี่ยนสถานะทุกคนในคาบนี้เป็นมา?'))return;cells.filter(c=>c.dataset.lesson===b.dataset.lesson).forEach(c=>c.value='/');update();});
  document.querySelectorAll('.grid-copy').forEach(b=>b.onclick=()=>{const targets=cells.filter(c=>c.dataset.lesson===b.dataset.to);if(targets.some(c=>c.value)&&!confirm('แทนที่สถานะคาบนี้ด้วยคาบก่อนหน้า?'))return;targets.forEach(c=>{const source=cells.find(s=>s.dataset.lesson===b.dataset.from&&s.dataset.student===c.dataset.student);if(source)c.value=source.value;});update();});
  if(gridForm)gridForm.addEventListener('submit',()=>{document.getElementById('gridChanges').value=JSON.stringify(cells.filter(c=>c.value!==c.dataset.original).map(c=>({lesson_id:Number(c.dataset.lesson),student_id:Number(c.dataset.student),mark:c.value,old:c.dataset.original})));window.lessonGridDirty=false;});
  window.addEventListener('beforeunload',event=>{if(window.lessonGridDirty){event.preventDefault();event.returnValue='';}});update();
})();
