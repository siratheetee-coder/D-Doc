// ตารางที่กว้างกว่าจอ (.table-wrap เลื่อนแนวนอน) ผู้ใช้มักไม่รู้ว่ามีคอลัมน์ซ่อนอยู่ทางขวา (เจ้าของแจ้ง)
// เติมเงาจางที่ขอบด้านที่ยังเลื่อนได้ + ปุ่ม "เลื่อนดูเพิ่ม ›" กดแล้วเลื่อนให้ · เลื่อนสุดแล้วหายเอง
// ใช้กับทุกตารางในระบบ (base.html) ไม่ต้องแก้ทีละหน้า
(function () {
  function setup(wrap) {
    if (wrap.dataset.tsh) return;
    wrap.dataset.tsh = '1';
    var outer = document.createElement('div');
    outer.className = 'tsh-outer';
    wrap.parentNode.insertBefore(outer, wrap);
    outer.appendChild(wrap);
    var fadeL = document.createElement('div'); fadeL.className = 'tsh-fade tsh-l';
    var fadeR = document.createElement('div'); fadeR.className = 'tsh-fade tsh-r';
    var pill = document.createElement('button');
    pill.type = 'button'; pill.className = 'tsh-pill'; pill.textContent = 'เลื่อนดูเพิ่ม ›';
    pill.setAttribute('aria-label', 'เลื่อนตารางไปทางขวาเพื่อดูคอลัมน์ที่เหลือ');
    pill.addEventListener('click', function () {
      wrap.scrollBy({ left: Math.max(200, wrap.clientWidth * 0.7), behavior: 'smooth' });
    });
    outer.appendChild(fadeL); outer.appendChild(fadeR); outer.appendChild(pill);
    function update() {
      var max = wrap.scrollWidth - wrap.clientWidth;
      var left = wrap.scrollLeft;
      outer.classList.toggle('tsh-more-r', max > 4 && left < max - 4);
      outer.classList.toggle('tsh-more-l', max > 4 && left > 4);
    }
    wrap.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    if (window.ResizeObserver) new ResizeObserver(update).observe(wrap);
    update();
  }
  function scan() { document.querySelectorAll('.table-wrap').forEach(setup); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan); else scan();
  window.tableScrollHint = scan;          // หน้าไหนสร้างตารางใหม่ด้วยสคริปต์ เรียกซ้ำได้
})();
