(() => {
 'use strict';const source=document.getElementById('tcData');if(!source)return;
 const data=JSON.parse(source.textContent),events=data.events||[],today=data.today||new Date().toLocaleDateString('sv-SE'),parts=today.split('-').map(Number);let year=parts[0],month=parts[1]-1;
 const names=['มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม'],pad=n=>String(n).padStart(2,'0'),key=d=>`${year}-${pad(month+1)}-${pad(d)}`;
 function showDay(iso){const list=document.getElementById('tcList');list.replaceChildren();const rows=events.filter(e=>e.d===iso);if(!rows.length){const p=document.createElement('p');p.className='sc-widget-empty';p.textContent='ไม่มีกิจกรรมหรือวันสำคัญในวันที่เลือก';list.append(p);return;}
  for(const e of rows){const el=document.createElement(e.href?'a':'p');el.className='sc-widget-day-event';el.textContent=e.name+(e.audience_label?' · '+e.audience_label:'');if(e.href)el.href=e.href;list.append(el);}
 }
 function draw(){document.getElementById('tcMonth').textContent=names[month]+' '+(year+543);const grid=document.getElementById('tcGrid');grid.replaceChildren();for(const text of ['จ.','อ.','พ.','พฤ.','ศ.','ส.','อา.']){const b=document.createElement('b');b.textContent=text;grid.append(b);}
  const lead=(new Date(year,month,1).getDay()+6)%7,count=new Date(year,month+1,0).getDate();for(let n=0;n<lead;n++)grid.append(document.createElement('span'));
  for(let d=1;d<=count;d++){const iso=key(d),rows=events.filter(e=>e.d===iso),b=document.createElement('button');b.type='button';b.textContent=d;b.className=(lead+d-1)%7>=5?'sc-weekend':'';if(iso===today)b.classList.add('sc-is-today');b.setAttribute('aria-label',`${d} ${names[month]} ${year+543}${rows.length?' '+rows.map(e=>e.name).join(', '):''}`);
   if(rows.length){const dot=document.createElement('i');dot.className=rows.some(e=>e.kind==='holiday')?'sc-dot-holiday':rows.some(e=>e.href)?'sc-dot-activity':'sc-dot-term';b.append(dot);b.title=rows.map(e=>e.name).join(', ');}
   b.addEventListener('click',()=>showDay(iso));grid.append(b);
  }document.getElementById('tcList').replaceChildren();
 }
 document.getElementById('tcPrev').addEventListener('click',()=>{if(--month<0){month=11;year--;}draw();});document.getElementById('tcNext').addEventListener('click',()=>{if(++month>11){month=0;year++;}draw();});document.getElementById('tcToday').addEventListener('click',()=>{year=parts[0];month=parts[1]-1;draw();showDay(today);});draw();
})();
