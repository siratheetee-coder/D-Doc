(() => {
  'use strict';
  const dialog=document.getElementById('lunch-dates');
  if(!dialog)return;
  const get=id=>document.getElementById(id),thaiMonths=['มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม'];
  let info,selected,month,initial,loadVersion=0,opener;
  const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const parse=d=>new Date(d+'T12:00:00');
  const label=d=>{const x=parse(d);return `${x.getDate()} ${thaiMonths[x.getMonth()].slice(0,3)} ${x.getFullYear()+543}`;};
  const close=()=>{loadVersion++;dialog.close();if(opener)opener.focus();};
  dialog.querySelector('.ld-close').onclick=close;
  dialog.querySelector('.ld-cancel').onclick=close;
  dialog.addEventListener('cancel',()=>{loadVersion++;});
  window.editRange=async button=>{
    opener=button;const version=++loadVersion;
    get('ld-preview').textContent='ดูผลการเปลี่ยนวันที่ →';get('ld-title').textContent='เลือกวันที่จัดอาหาร';get('ld-message').textContent='กำลังโหลดปฏิทิน…';
    dialog.querySelector('.ld-body').hidden=true;get('ld-preview').disabled=true;
    dialog.showModal();
    try{
      const response=await fetch(`/lunch/installment/${button.closest('[data-iid]').dataset.iid}/dates`,{headers:{Accept:'application/json'}});
      if(!response.ok)throw Error('โหลดปฏิทินไม่สำเร็จ กรุณาปิดแล้วลองใหม่');
      const data=await response.json();if(version!==loadVersion||!dialog.open)return;
      info=data;initial=[...info.selected];selected=new Set(initial);
      month=parse(initial[0]||info.minimum||Object.keys(info.calendar).sort()[0]);month.setDate(1);
      get('ld-title').textContent=`${info.readonly?'วันจัดอาหาร':'แก้ไขวันที่'} · งวด ${info.seq}`;
      get('ld-message').textContent=info.readonly?'งวดนี้ดำเนินการแล้ว เปิดดูวันที่ได้อย่างเดียว':'คลิกวันที่เพื่อเลือกหรือยกเลิก วันหยุดเลือกไม่ได้ หากมีวันชดเชยให้ตั้งค่าปฏิทินโรงเรียนก่อน';
      get('ld-form').action=info.preview_url;get('ld-preview').hidden=info.readonly;
      get('ld-reset').hidden=info.readonly;dialog.querySelector('.ld-cancel').textContent=info.readonly?'ปิด':'ยกเลิก';
      dialog.querySelector('.ld-body').hidden=false;draw();
    }catch(error){if(version===loadVersion)get('ld-message').textContent=error.message;}
  };
  function draw(){
    const keys=Object.keys(info.calendar).sort(),first=iso(month),last=iso(new Date(month.getFullYear(),month.getMonth()+1,0,12));
    get('ld-month').textContent=thaiMonths[month.getMonth()]+' '+(month.getFullYear()+543);
    get('ld-prev').disabled=first<=keys[0];get('ld-next').disabled=last>=keys[keys.length-1];
    const grid=get('ld-grid');grid.replaceChildren();
    for(let n=0;n<(month.getDay()+6)%7;n++)grid.append(document.createElement('span'));
    for(let n=1;n<=parse(last).getDate();n++){
      const d=new Date(month.getFullYear(),month.getMonth(),n,12),key=iso(d),open=info.calendar[key]===true,chosen=selected.has(key),b=document.createElement('button');
      b.type='button';b.textContent=n;b.setAttribute('aria-pressed',String(chosen));
      b.setAttribute('aria-label',`${label(key)} ${chosen?'เลือกแล้ว':open?'วันเรียน':'วันหยุดหรือไม่มีเรียน'}`);
      b.className=!open?(d.getDay()===0||d.getDay()===6?'ld-weekend':'ld-closed'):key<info.minimum?'ld-blocked':'';
      // Historical selected holidays can be removed, but cannot be newly selected.
      b.disabled=info.readonly||(!chosen&&(!open||key<info.minimum));
      b.dataset.date=key;b.onclick=()=>{selected.has(key)?selected.delete(key):selected.add(key);draw();get('ld-grid').querySelector(`[data-date="${key}"]`).focus();};grid.append(b);
    }
    const dates=[...selected].sort();get('ld-count').textContent=dates.length+' / '+info.days;
    get('ld-range').textContent=dates.length?label(dates[0])+' – '+label(dates[dates.length-1]):'ยังไม่ได้เลือกวันที่';
    const chips=get('ld-chips');chips.replaceChildren();
    dates.forEach(key=>{const chip=document.createElement('span');chip.className='ld-chip'+(!info.calendar[key]?' ld-invalid':'');chip.textContent=label(key)+(!info.calendar[key]?' · วันหยุด':'');
      if(!info.readonly){const x=document.createElement('button');x.type='button';x.textContent='×';x.setAttribute('aria-label','ยกเลิก '+label(key));x.onclick=()=>{selected.delete(key);draw();};chip.append(x);}chips.append(chip);});
    const invalid=dates.some(d=>!info.calendar[d]||d<info.minimum);
    dialog.querySelector('.ld-help').textContent=info.readonly?'คงวันที่เดิมไว้เพื่อรักษาประวัติการดำเนินงาน':invalid?'มีวันหยุดหรือวันที่ก่อนงวดนี้อยู่ในรายการ กรุณายกเลิกวันนั้นแล้วเลือกวันเรียนแทน':dates.length>info.days?'เลือกเกินจำนวนวันเดิม กรุณายกเลิกวันที่เกิน':dates.length<info.days?`เลือกเพิ่มอีก ${info.days-dates.length} วัน ให้ครบจำนวนวันเดิมของงวด`:'เลือกครบแล้ว ระบบจะตรวจผลต่องวดอื่นก่อนบันทึก';
    get('ld-preview').disabled=info.readonly||dates.length!==info.days||invalid||JSON.stringify(dates)===JSON.stringify([...initial].sort());
    get('ld-selected').value=JSON.stringify(dates);
    get('ld-reset').onclick=()=>{selected=new Set(initial);month=parse(initial[0]||info.minimum||keys[0]);month.setDate(1);draw();};
    get('ld-prev').onclick=()=>{month.setMonth(month.getMonth()-1);draw();};
    get('ld-next').onclick=()=>{month.setMonth(month.getMonth()+1);draw();};
  }
  window.addEventListener('pageshow',()=>{if(info&&dialog.open){get('ld-preview').textContent='ดูผลการเปลี่ยนวันที่ →';draw();}});
  get('ld-form').addEventListener('submit',event=>{if(get('ld-preview').disabled)event.preventDefault();else{get('ld-preview').disabled=true;get('ld-preview').textContent='กำลังตรวจวันที่…';}});
})();
