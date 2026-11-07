(() => {
  const form=document.querySelector('[data-lunch-round-form]');
  if(!form)return;
  const key='lunchCalendarDraft:'+form.dataset.draftKey;
  document.querySelectorAll('[data-calendar-link]').forEach(link=>link.addEventListener('click',()=>{
    try{
      const fields=[...form.elements].filter(e=>e.name&&e.type!=='file'&&e.type!=='password')
        .map(e=>({name:e.name,value:e.value,checked:e.checked,type:e.type}));
      sessionStorage.setItem(key,JSON.stringify({path:location.pathname,at:Date.now(),fields,nv:document.getElementById('nvBox')?.style.display}));
    }catch(e){/* The server still supports navigating to and from the shared calendar. */}
  }));
  let draft;try{draft=JSON.parse(sessionStorage.getItem(key)||'null');}catch(e){return;}
  if(!draft||draft.path!==location.pathname||Date.now()-draft.at>4*3600000)return;
  draft.fields.forEach(v=>{
    const field=form.elements.namedItem(v.name);if(!field||!field.tagName)return;
    field.value=v.value;if(v.type==='checkbox'||v.type==='radio')field.checked=v.checked;
    if(field.tagName==='SELECT')field.dispatchEvent(new Event('change',{bubbles:true}));
  });
  const box=document.getElementById('nvBox');if(box&&draft.nv)box.style.display=draft.nv;
  sessionStorage.removeItem(key);
  if(typeof calcAmt==='function')calcAmt();
  if(typeof splitHint==='function')splitHint();
  const note=document.querySelector('[data-calendar-restored]');if(note)note.hidden=false;
})();
