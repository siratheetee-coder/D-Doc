/* ราคาแพ็กเกจหลายปี (แสดงผลเท่านั้น) ต้องตรงกับ price_for / term_total ใน app/seller_config.py
   3 ปี = ราคา 2.5 ปี, 5 ปี = ราคา 3.75 ปี ปัดให้ลงท้ายด้วย 90
   ถ้าราคาที่เลือกไม่ถูกกว่าครบทุกงาน -> ได้ครบทุกงานในราคาแพ็กแทน */
(function(){
  var F = {1: 1, 3: 2.5, 5: 3.75};
  function term(annual, years){
    years = F[years] ? +years : 1;
    if(years === 1 || annual <= 0) return annual;
    return Math.floor((annual * F[years] - 90) / 100 + 0.5) * 100 + 90;
  }
  // listSum = ราคาเต็มต่อปีของงานที่เลือก, count = จำนวนงาน
  function pick(listSum, count, nmods, tiers, bundle, years){
    years = F[years] ? +years : 1;
    var bundleT = term(bundle, years);
    if(!count) return {total: 0, all: false, capped: false, years: years, full: 0, bundle: bundleT};
    var annual = count === nmods ? bundle : Math.max(0, listSum - (tiers[count] || 0));
    var total = term(annual, years), capped = false;
    if(count < nmods && total >= bundleT){ total = bundleT; capped = true; }
    return {total: total, all: count === nmods || capped, capped: capped, years: years,
            full: listSum * years, bundle: bundleT, perYear: Math.round(total / years)};
  }
  // ปุ่มสลับ 1/3/5 ปี: <div data-years-toggle><button data-y="1">...</button>...</div>
  function toggle(root, onChange){
    if(!root) return function(){ return 1; };
    var btns = [].slice.call(root.querySelectorAll('[data-y]'));
    var input = root.querySelector('input[name="years"]');
    function set(y){
      btns.forEach(function(b){ var on = b.dataset.y == y; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
      if(input) input.value = y;
    }
    btns.forEach(function(b){ b.addEventListener('click', function(){ set(b.dataset.y); onChange(); }); });
    var cur = function(){ var on = btns.filter(function(b){ return b.classList.contains('on'); })[0]; return on ? +on.dataset.y : 1; };
    set(cur());
    return cur;
  }
  window.ddocTerm = {term: term, pick: pick, toggle: toggle, factor: F};
})();
