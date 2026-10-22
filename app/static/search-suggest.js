// กล่องค้นหาแถบบน: แสดงผลย่อ ๆ ระหว่างพิมพ์ (กด Enter = ไปหน้าผลค้นหาเต็ม)
(() => {
  const form = document.querySelector('form.topsearch');
  const input = form && form.querySelector('input[name=q]');
  if (!input) return;
  input.setAttribute('autocomplete', 'off');
  const box = document.createElement('div');
  box.className = 'ss-box'; box.hidden = true; box.setAttribute('role', 'listbox');
  form.append(box);
  let timer = 0, seq = 0, active = -1;
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const links = () => [...box.querySelectorAll('a')];
  function mark(i) { const a = links(); active = (i + a.length) % a.length; a.forEach((x, j) => x.classList.toggle('on', j === active)); a[active]?.scrollIntoView({ block: 'nearest' }); }
  async function load() {
    const q = input.value.trim(), my = ++seq;
    if (q.length < 2) { box.hidden = true; return; }
    try {
      const r = await fetch('/search/suggest?q=' + encodeURIComponent(q));
      if (!r.ok || r.redirected || my !== seq) return;
      const data = await r.json();
      active = -1;
      box.innerHTML = data.groups.length
        ? data.groups.map(g => `<div class="ss-h">${esc(g.label)}</div>` + g.items.map(it =>
            `<a href="${esc(it.url)}"><b>${esc(it.title)}</b>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}</a>`).join('')).join('')
          + `<a class="ss-all" href="/search?q=${encodeURIComponent(q)}">ดูผลทั้งหมดของ "${esc(q)}" →</a>`
        : `<div class="ss-none">ไม่พบ "${esc(q)}"</div>`;
      box.hidden = false;
    } catch {}
  }
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 220); });
  input.addEventListener('focus', () => { if (box.innerHTML && input.value.trim().length >= 2) box.hidden = false; });
  input.addEventListener('keydown', e => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); mark(active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); mark(active - 1); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); links()[active].click(); }
    else if (e.key === 'Escape') box.hidden = true;
  });
  document.addEventListener('click', e => { if (!form.contains(e.target)) box.hidden = true; });
})();
