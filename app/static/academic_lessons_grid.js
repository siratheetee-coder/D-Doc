(()=>{
  const configEl=document.getElementById('lessonConfig');if(!configEl)return;
  const cfg=JSON.parse(configEl.textContent),calendar=document.getElementById('lessonCalendar');
  let monthIndex=cfg.months.indexOf(cfg.month),selected=new Set();
  try{JSON.parse(cfg.entered.dates||'[]').forEach(d=>selected.add(d));}catch{}
  const dateKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const events=new Set(cfg.events.map(e=>e.date));
  function choices(){return [...document.querySelectorAll('#slotChoices .slot-choice')].filter(el=>el.querySelector('[type=checkbox]').checked).map(el=>({name:el.querySelector('[type=checkbox]').dataset.slot,minutes:Number(el.querySelector('[type=number]').value)}));}
  function summary(){const slots=choices(),minutes=slots.reduce((sum,s)=>sum+s.minutes,0)*selected.size;document.getElementById('batchSummary').textContent=`เลือก ${selected.size} วัน · ${slots.length} คาบต่อวัน · รวม ${selected.size*slots.length} คาบ (${minutes} นาที)`;}
  function draw(){
    const [year,month]=cfg.months[monthIndex].split('-').map(Number);
    document.getElementById('calTitle').textContent=new Date(year,month-1,1).toLocaleDateString('th-TH',{month:'long',year:'numeric'});
    calendar.replaceChildren();['จ','อ','พ','พฤ','ศ','ส','อา'].forEach(text=>{const el=document.createElement('span');el.textContent=text;calendar.append(el);});
    const first=(new Date(year,month-1,1).getDay()+6)%7;
    for(let i=0;i<first;i++)calendar.append(document.createElement('span'));
    for(let day=1;day<=new Date(year,month,0).getDate();day++){
      const key=dateKey(new Date(year,month-1,day)),b=document.createElement('button');b.type='button';b.textContent=day;
      b.setAttribute('aria-label',new Date(year,month-1,day).toLocaleDateString('th-TH'));b.setAttribute('aria-pressed',selected.has(key));
      b.classList.toggle('selected',selected.has(key));b.classList.toggle('has-lesson',events.has(key));
      b.onclick=()=>{selected.has(key)?selected.delete(key):selected.add(key);draw();};calendar.append(b);
    }
    document.getElementById('calPrev').disabled=monthIndex===0;document.getElementById('calNext').disabled=monthIndex===cfg.months.length-1;summary();
  }
  document.getElementById('calPrev').onclick=()=>{if(monthIndex>0){monthIndex--;draw();}};
  document.getElementById('calNext').onclick=()=>{if(monthIndex<cfg.months.length-1){monthIndex++;draw();}};
  document.getElementById('calToday').onclick=()=>{const now=dateKey(new Date()),index=cfg.months.indexOf(now.slice(0,7));if(index<0){alert('วันนี้ไม่อยู่ในปีการศึกษาที่เลือก');return;}monthIndex=index;selected.add(now);draw();};
  document.getElementById('clearDates').onclick=()=>{selected.clear();draw();};
  document.getElementById('slotChoices').addEventListener('input',summary);
  function addSlot(name,minutes=50,checked=true){
    const label=document.createElement('label');label.className='slot-choice';
    const check=document.createElement('input');check.type='checkbox';check.checked=checked;check.dataset.slot=name;
    const text=document.createElement('span');text.textContent=name;
    const number=document.createElement('input');number.type='number';number.min=1;number.max=720;number.value=minutes;number.setAttribute('aria-label','นาที '+name);
    const unit=document.createElement('small');unit.textContent='นาที';label.append(check,text,number,unit);document.getElementById('slotChoices').append(label);
  }
  try{JSON.parse(cfg.entered.slots||'[]').forEach(slot=>{const box=[...document.querySelectorAll('[data-slot]')].find(el=>el.dataset.slot===slot.name);if(box){box.checked=true;box.parentElement.querySelector('[type=number]').value=slot.minutes;}else addSlot(slot.name,slot.minutes);});}catch{}
  document.getElementById('addSlot').onclick=()=>{const input=document.getElementById('customSlot'),name=input.value.trim();if(!name)return;if([...document.querySelectorAll('[data-slot]')].some(el=>el.dataset.slot===name)){alert('มีชื่อคาบนี้แล้ว');return;}addSlot(name);input.value='';summary();};
  document.getElementById('batchLessons').addEventListener('submit',event=>{const slots=choices();if(!selected.size||!slots.length||slots.some(s=>!Number.isInteger(s.minutes)||s.minutes<1||s.minutes>720)){event.preventDefault();alert('เลือกวันและคาบ พร้อมระบุนาทีต่อคาบให้ถูกต้อง');return;}if(window.lessonGridDirty&&!confirm('มีผลเช็กชื่อที่ยังไม่บันทึก ต้องการออกจากตารางเพื่อเพิ่มวันสอนหรือไม่?')){event.preventDefault();return;}window.lessonGridDirty=false;document.getElementById('batchDates').value=JSON.stringify([...selected].sort());document.getElementById('batchSlots').value=JSON.stringify(slots);});
  draw();
  const cells=[...document.querySelectorAll('.grid-mark')],gridForm=document.getElementById('gridMarks');
  function update(){let count=0;cells.forEach(c=>{c.dataset.state=c.value;const changed=c.value!==c.dataset.original;c.classList.toggle('changed',changed);if(changed)count++;});window.lessonGridDirty=count>0;const status=document.getElementById('gridStatus');if(status)status.textContent=count?`แก้ไข ${count} ช่อง · ยังไม่บันทึก`:'ยังไม่มีการแก้ไข';}
  // Restore the user's edits after validation errors without changing server baselines.
  try{JSON.parse(cfg.entered.changes||'[]').forEach(item=>{const cell=cells.find(c=>c.dataset.lesson===String(item.lesson_id)&&c.dataset.student===String(item.student_id));if(cell)cell.value=item.mark;});}catch{}
  cells.forEach(c=>c.addEventListener('change',update));
  document.querySelectorAll('.grid-all').forEach(b=>b.onclick=()=>{if(cells.some(c=>c.dataset.lesson===b.dataset.lesson&&c.value&&c.value!=='/')&&!confirm('เปลี่ยนสถานะทุกคนในคาบนี้เป็นมา?'))return;cells.filter(c=>c.dataset.lesson===b.dataset.lesson).forEach(c=>c.value='/');update();});
  document.querySelectorAll('.grid-copy').forEach(b=>b.onclick=()=>{const targets=cells.filter(c=>c.dataset.lesson===b.dataset.to);if(targets.some(c=>c.value)&&!confirm('แทนที่สถานะคาบนี้ด้วยคาบก่อนหน้า?'))return;targets.forEach(c=>{const source=cells.find(s=>s.dataset.lesson===b.dataset.from&&s.dataset.student===c.dataset.student);if(source)c.value=source.value;});update();});
  if(gridForm)gridForm.addEventListener('submit',()=>{document.getElementById('gridChanges').value=JSON.stringify(cells.filter(c=>c.value!==c.dataset.original).map(c=>({lesson_id:Number(c.dataset.lesson),student_id:Number(c.dataset.student),mark:c.value,old:c.dataset.original})));window.lessonGridDirty=false;});
  window.addEventListener('beforeunload',event=>{if(window.lessonGridDirty){event.preventDefault();event.returnValue='';}});update();
})();
