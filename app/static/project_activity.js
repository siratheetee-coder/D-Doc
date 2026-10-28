/* ช่องเลือกกิจกรรมในโครงการ: select[data-activity-for] เปลี่ยนรายการตามโครงการที่เลือก
   data-activity-for = selector ของช่องโครงการ (select ใช้ value = id, input ใช้ชื่อโครงการ)
   ข้อมูลจาก window.PJ_ACTS = {by_id: {...}, by_name: {...}} */
(function () {
  var maps = window.PJ_ACTS || {by_id: {}, by_name: {}};
  document.querySelectorAll('select[data-activity-for]').forEach(function (sel) {
    var src = document.querySelector(sel.dataset.activityFor);
    var wrap = sel.closest('[data-activity-wrap]') || sel.parentNode;
    if (!src) return;
    var keep = sel.dataset.selected || '';
    function fill() {
      var v = (src.value || '').trim();
      var list = (src.tagName === 'SELECT' ? maps.by_id[v] : maps.by_name[v]) || [];
      var cur = sel.value || keep;
      sel.innerHTML = '<option value="">- ไม่ระบุกิจกรรม -</option>';
      list.forEach(function (a) {
        var o = document.createElement('option');
        o.value = a[0]; o.textContent = a[1];
        if (String(a[0]) === String(cur)) o.selected = true;
        sel.appendChild(o);
      });
      wrap.style.display = list.length ? "" : "none";
      keep = '';
    }
    src.addEventListener('change', fill);
    src.addEventListener('input', fill);
    fill();
  });
})();
