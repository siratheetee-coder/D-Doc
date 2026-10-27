// การ์ดฟอร์ม "เพิ่ม..." ที่อยู่บนสุดของหน้า: ปิดไว้เป็นปุ่ม กดแล้วค่อยกางฟอร์ม
// เปิดค้างเองเมื่อ: กำลังแก้ไข (data-open="1"), มีข้อความผิดพลาดในฟอร์ม, หรือลิงก์ชี้มาที่การ์ดนี้ (#id)
(() => {
  document.querySelectorAll('[data-addbox]').forEach((card, n) => {
    const h = [...card.children].find(el => /^H[23]$/.test(el.tagName));
    if (!h) return;
    const body = document.createElement('div');
    body.className = 'addbox-body';
    body.id = card.id ? card.id + '-body' : 'addbox-body-' + n;
    while (h.nextSibling) body.append(h.nextSibling);
    card.append(body);
    card.classList.add('addbox');
    h.setAttribute('role', 'button');
    h.setAttribute('tabindex', '0');
    h.setAttribute('aria-controls', body.id);
    // นับเฉพาะข้อความผิดพลาดที่มีเนื้อหาและแสดงอยู่จริง (ช่องแจ้งเตือนว่างที่ซ่อนไว้ไม่นับ)
    const hasErr = [...body.querySelectorAll('.alert.warn, .err, .error, [role=alert]')]
      .some(el => !el.hidden && el.textContent.trim() && getComputedStyle(el).display !== 'none');
    const open = card.dataset.open === '1' || hasErr || (card.id && location.hash === '#' + card.id);
    const set = v => { card.classList.toggle('open', v); h.setAttribute('aria-expanded', v); };
    set(!!open);
    const toggle = () => {
      const v = !card.classList.contains('open');
      set(v);
      if (v) { const f = body.querySelector('input:not([type=hidden]), select, textarea'); if (f) f.focus({ preventScroll: true }); }
    };
    h.addEventListener('click', toggle);
    h.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });
})();
