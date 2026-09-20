(() => {
  'use strict';
  const main = document.querySelector('main');
  if (!main) return;
  document.querySelectorAll('.save-fab').forEach(el=>{if(el.form && main.contains(el.form)){el.classList.add('save-dock-original');el.form.appendChild(el);}});
  const known = new WeakSet();
  const dock = document.createElement('div');
  dock.id = 'floating-save-dock'; dock.hidden = true;
  dock.innerHTML = '<label for="floating-save-target">บันทึกส่วน</label><select id="floating-save-target" aria-label="เลือกส่วนที่ต้องการบันทึก"></select><button type="button" class="btn" id="floating-save-action">💾 บันทึก</button>';
  document.body.appendChild(dock);
  const select = dock.querySelector('select'), action = dock.querySelector('button');
  let targets = [], chosen = null, scheduled = false;
  const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' && !el.closest('[hidden], [aria-hidden="true"]'));
  function candidates() {
    return [...main.querySelectorAll('button,input[type=submit]')].filter(el => {
      const text = (el.textContent || el.value || '').replace(/💾/g, '').trim();
      const save = known.has(el) || (/^บันทึก/.test(text) && !/ออก|พิมพ์|ดาวน์โหลด|นำ.*ทะเบียน|รหัสผ่าน/.test(text));
      if(save) known.add(el);
      return el !== action && visible(el) && !el.closest('[role=dialog],.modal,.cf-ov') &&
        !el.hasAttribute('data-no-floating-save') && el.name !== 'document' && el.name !== 'transfer' &&
        save;
    });
  }
  function label(el, index) {
    const row = el.closest('tr');
    const section = el.closest('.card,.tp-card,section');
    const title = row?.querySelector('input[name*=name]')?.value || row?.querySelector('td')?.textContent || section?.querySelector('h2,h3')?.textContent || '';
    return `${index+1}. ${title.trim().replace(/\s+/g,' ').slice(0,70) || (el.textContent || el.value).trim()}`;
  }
  function refresh() {
    scheduled = false;
    targets = candidates();
    if (!targets.includes(chosen)) chosen = targets[0] || null;
    const blocked = [...document.querySelectorAll('[aria-modal=true],.cf-ov,.dn-ov,.trial-modal,.sb-overlay,.sig-overlay,.wm-ov,#vendorOverlay')].some(visible) || document.querySelector('.cal-panel.open');
    const keyboard = window.visualViewport && window.innerHeight - visualViewport.height > 160;
    dock.hidden = !chosen || !!blocked || !!keyboard;
    document.body.classList.toggle('has-save-dock', !dock.hidden);
    // One visible dock replaces the trip's existing floating control.
    main.querySelectorAll('.save-fab').forEach(el => el.classList.toggle('save-dock-original', !!chosen));
    const signature = targets.map((el,i)=>label(el,i)).join('|');
    if (select.dataset.signature !== signature) {
      select.replaceChildren(...targets.map((el,i)=>new Option(label(el,i),String(i))));
      select.dataset.signature = signature;
    }
    select.value = String(targets.indexOf(chosen));
    select.hidden = targets.length < 2; dock.querySelector('label').hidden = targets.length < 2;
    action.disabled = !chosen || chosen.disabled || chosen.matches(':disabled');
    action.textContent = chosen ? (chosen.textContent || chosen.value).trim() : 'บันทึก';
    action.title = chosen ? label(chosen,targets.indexOf(chosen)) : '';
  }
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(refresh);}}
  select.addEventListener('change',()=>{chosen=targets[+select.value];refresh();});
  main.addEventListener('focusin',e=>{
    const form=e.target.form || e.target.closest('form');
    const row=e.target.closest('tr');
    const found=targets.find(b=>row && b.closest('tr')===row) || targets.find(b=>form && b.form===form);
    if(found) chosen=found;schedule();
  });
  action.addEventListener('click',()=>{
    if (!chosen || !visible(chosen) || chosen.disabled || chosen.matches(':disabled')) return;
    // Preserve the exact submitter, its name/value, validation and existing click/AJAX handlers.
    chosen.click();schedule();
  });
  document.addEventListener('invalid',e=>e.target.scrollIntoView({block:'center',behavior:'smooth'}),true);
  new MutationObserver(schedule).observe(main,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','style','class','disabled']});
  document.addEventListener('click',schedule);window.addEventListener('resize',schedule);
  window.visualViewport?.addEventListener('resize',schedule);
  refresh();
})();
