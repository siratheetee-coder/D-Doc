(function(){
  var me=document.getElementById('rqJs'), box=document.getElementById('rq'); if(!box||!me) return;
  var pid=me.dataset.pid, back=me.dataset.back||'', rows=[], budget=0, spent=0;
  var $=function(i){return document.getElementById(i);};
  function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');}
  function f2(n){return (Math.round(n*100)/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
  function step(u){return {'กก.':0.5,'กิโลกรัม':0.5,'ฟอง':10,'ลิตร':0.5}[(u||'').trim()]||1;}
  function bq(){return back?'&back='+encodeURIComponent(back):'';}
  function load(rid){
    fetch('/lunch/'+pid+'/recipes/calc?d='+encodeURIComponent($('rqDay').value)+(rid?'&recipe='+rid:'')+bq())
    .then(function(r){return r.json();}).then(function(j){
      var sel=$('rqRecipe');
      sel.innerHTML='<option value="">เลือกสูตร</option>'+j.recipes.map(function(x){return '<option value="'+x.id+'">'+esc(x.name)+'</option>';}).join('');
      if(j.recipe) sel.value=j.recipe.id;
      budget=j.budget; spent=j.spent; rows=j.rows;
      $('rqShop').href='/lunch/'+pid+'/shopping?w='+encodeURIComponent($('rqDay').value)+bq();
      if(!j.recipe){
        $('rqOut').hidden=true; $('rqNone').hidden=false;
        $('rqNone').textContent=j.recipes.length?'ยังไม่มีสูตรที่ชื่อตรงกับเมนูวันนี้ เลือกสูตรจากรายการแล้วกดคำนวณ':'ยังไม่มีสูตรอาหาร กด "สูตรอาหาร" เพื่อตั้งสูตรก่อน';
        return;
      }
      $('rqNone').hidden=true; $('rqOut').hidden=false;
      $('rqTiers').textContent='นักเรียน อนุบาล '+j.tiers[0]+' คน ประถม '+j.tiers[1]+' คน มัธยม '+j.tiers[2]+' คน (ยอดที่ตั้งไว้ในโครงการ)';
      draw();
    });
  }
  function draw(){
    $('rqRows').innerHTML=rows.map(function(r,i){
      return '<tr class="'+(r.have?'have':'')+'"><td>'+esc(r.name)+(r.locked?' 🔒':'')+(r.have?' <span class="muted">(กรอกแล้ว)</span>':'')+'</td><td>'+r.raw+'</td>'+
        '<td><input type="number" step="0.01" min="0" data-i="'+i+'" data-k="qty" value="'+r.qty+'"></td><td>'+esc(r.unit)+'</td>'+
        '<td><input type="number" step="0.01" min="0" data-i="'+i+'" data-k="price" value="'+r.price+'"></td><td class="amt">'+f2(r.qty*r.price)+'</td></tr>';
    }).join('');
    $('rqRows').querySelectorAll('input').forEach(function(el){
      el.oninput=function(){var r=rows[+el.dataset.i]; r[el.dataset.k]=parseFloat(el.value)||0;
        el.closest('tr').querySelector('.amt').textContent=f2(r.qty*r.price); sum();};
    });
    sum();
  }
  function sum(){
    var c=rows.reduce(function(a,r){return a+(r.have?0:r.qty*r.price);},0), left=budget-spent-c, over=left<0;
    $('rqBud').className='rq-bud'+(over?' over':'');
    $('rqBud').innerHTML='<div><span>งบวัตถุดิบวันนี้</span><b>'+f2(budget)+'</b></div><div><span>กรอกไว้แล้ว</span><b>'+f2(spent)+'</b></div>'+
      '<div><span>จากสูตร</span><b>'+f2(c)+'</b></div><div><span>'+(over?'เกินงบ':'เหลือ')+'</span><b>'+f2(Math.abs(left))+'</b></div>';
    $('rqFit').hidden=!(over&&budget>0);
  }
  $('rqFit').onclick=function(){
    var fixed=rows.reduce(function(a,r){return a+((!r.have&&r.locked)?r.qty*r.price:0);},0);
    var flex=rows.reduce(function(a,r){return a+((!r.have&&!r.locked)?r.raw*r.price:0);},0);
    var room=budget-spent-fixed;
    if(flex<=0||room<=0){alert('ปรับไม่ได้ เพราะรายการที่ล็อกไว้ใช้งบเกินแล้ว');return;}
    var k=Math.min(1,room/flex);
    rows.forEach(function(r){ if(r.have||r.locked) return; var s=step(r.unit);
      r.qty=Math.max(0,Math.round(Math.floor(r.raw*k/s+1e-9)*s*100)/100); });
    draw();
    if(window.showToast) showToast('ลดปริมาณรายการที่ไม่ล็อกลง '+Math.round((1-k)*100)+'%');
  };
  $('rqGo').onclick=function(){load($('rqRecipe').value);};
  $('rqDay').onchange=function(){load(0);};
  $('rqForm').onsubmit=function(){ $('rqDate').value=$('rqDay').value;
    $('rqData').value=JSON.stringify(rows.filter(function(r){return !r.have;})); };
  load(0);
})();
