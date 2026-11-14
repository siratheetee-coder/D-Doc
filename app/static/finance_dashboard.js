(() => {
  'use strict';
  function reveal(id){const target=document.getElementById(id);if(!target)return;let el=target;while(el){if(el.tagName==='DETAILS')el.open=true;el=el.parentElement;}target.scrollIntoView({block:'start',behavior:'smooth'});}
  document.querySelectorAll('.fd-page a[href^="#"]').forEach(a=>a.addEventListener('click',event=>{const id=a.getAttribute('href').slice(1);if(document.getElementById(id)){event.preventDefault();reveal(id);history.replaceState(null,'','#'+id);}}));
  if(location.hash)requestAnimationFrame(()=>reveal(location.hash.slice(1)));
  const setup=document.getElementById('fd-setup');
  if(setup){const update=()=>{const step=setup.querySelector('.fs-step.is-next .fs-name'),label=setup.querySelector('.fd-setup-next');if(label)label.textContent=step?'ขั้นถัดไป: '+step.textContent.replace(/^\s*\d+\.\s*/,''):'ตรวจขั้นตอนที่ข้ามไว้ หรือดูวิธีใช้งาน';};update();setup.addEventListener('click',()=>requestAnimationFrame(update));}
})();
