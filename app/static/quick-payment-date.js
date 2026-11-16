(function(){
  const dialog=document.getElementById('quick-pay-date');if(!dialog)return;
  const form=document.getElementById('qpd-form'),input=document.getElementById('qpd-date'),save=document.getElementById('qpd-save'),message=document.getElementById('qpd-message'),useMemo=document.getElementById('qpd-use-memo');
  let current=null,opener=null,loading=0,busy=false;
  const headers={'X-Requested-With':'fetch','Accept':'application/json'};
  function errorText(data){return typeof data?.detail==='string'?data.detail:'ไม่สามารถแก้วันที่ได้ กรุณาลองใหม่';}
  async function open(button){
    if(busy)return;const serial=++loading;opener=button;current=null;message.textContent='กำลังโหลดวันที่ล่าสุด…';input.value='';input.disabled=true;save.disabled=true;useMemo.hidden=true;document.getElementById('qpd-recon').hidden=true;document.getElementById('qpd-subject').textContent='';dialog.showModal();
    try{const response=await fetch('/finance/txn/'+button.dataset.paymentDateEdit+'/payment-date',{headers});const data=await response.json();if(serial!==loading||!dialog.open)return;if(!response.ok)throw new Error(errorText(data));current=data;input.disabled=false;save.disabled=false;input.value=data.be_date;document.getElementById('qpd-subject').textContent=data.subject+' · '+data.amount_label+' บาท';document.getElementById('qpd-recon').hidden=!data.recon;message.textContent='';if(data.memo_date){useMemo.hidden=false;useMemo.textContent='ใช้วันที่บันทึกขอเบิก '+data.memo_date;}input.focus();input.select();}catch(error){if(serial===loading)message.textContent=error.message;}
  }
  document.addEventListener('click',function(event){const button=event.target.closest('[data-payment-date-edit]');if(!button)return;event.preventDefault();event.stopPropagation();open(button);});
  function close(){if(busy)return;++loading;dialog.close();opener?.focus();}
  dialog.querySelectorAll('.qpd-close').forEach(button=>button.addEventListener('click',close));dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}});
  useMemo.addEventListener('click',()=>{input.value=current.memo_date;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();});
  async function refreshLedger(id){
    const history=document.getElementById('txn-history');if(!history)return;
    const response=await fetch(location.href,{headers:{'X-Requested-With':'fetch'}});if(!response.ok)throw new Error('โหลดตารางล่าสุดไม่สำเร็จ');
    const html=new DOMParser().parseFromString(await response.text(),'text/html'),table=html.querySelector('#txn-history .table-wrap');if(!table)throw new Error('ไม่พบตารางล่าสุด');
    history.querySelector('.table-wrap').replaceWith(table);window.initRowLinks?.(history);const row=document.getElementById('t'+id);if(row){row.classList.add('qpd-highlight');row.scrollIntoView({block:'nearest'});}
  }
  form.addEventListener('submit',async function(event){
    event.preventDefault();if(!current||busy)return;busy=true;save.disabled=true;input.disabled=true;message.textContent='กำลังบันทึก…';
    try{const response=await fetch('/finance/txn/'+current.id+'/payment-date',{method:'POST',headers:{...headers,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({paid_date:input.value,version:current.version})});const data=await response.json();if(!response.ok)throw new Error(errorText(data));
      document.querySelectorAll('[data-payment-date-label="'+data.id+'"]').forEach(label=>{label.textContent=label.dataset.dateStyle==='long'?data.label_long:data.label_short;});
      try{await refreshLedger(data.id);}catch(error){const history=document.getElementById('txn-history');const warning=document.createElement('p');warning.className='alert warn';warning.setAttribute('role','alert');warning.textContent='บันทึกวันที่แล้ว แต่ยังโหลดลำดับรายการและยอดคงเหลือใหม่ไม่สำเร็จ ';const retry=document.createElement('button');retry.type='button';retry.className='btn sm gray';retry.textContent='โหลดตารางล่าสุด';retry.addEventListener('click',async()=>{try{await refreshLedger(data.id);warning.remove();}catch(e){retry.textContent='โหลดไม่สำเร็จ ลองอีกครั้ง';}});warning.append(retry);history.prepend(warning);}
      busy=false;dialog.close();opener=document.querySelector('[data-payment-date-edit="'+data.id+'"]');opener?.focus();window.showToast?.('แก้วันที่จ่ายเป็น '+data.be_date+' แล้ว');document.dispatchEvent(new CustomEvent('payment-date-updated',{detail:data}));
    }catch(error){message.textContent=error.message;input.disabled=false;save.disabled=false;}finally{busy=false;}
  });
})();
