// ถาม AI: หน้าต่างเปิดค้างข้ามหน้า (จำสถานะ+บทสนทนาไว้ใน sessionStorage ของแท็บนี้)
(() => {
  const panel = document.getElementById('aiHelp'), btn = document.getElementById('aiHelpOpen');
  if (!panel || !btn) return;
  document.body.append(panel);
  const log = document.getElementById('aiLog'), form = document.getElementById('aiForm'), q = document.getElementById('aiQ');
  const send = document.getElementById('aiSend'), left = document.getElementById('aiLeft');
  const store = {
    get(k, d) { try { const v = sessionStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };
  let chat = store.get('aiChat', []), busy = false, status = null;
  const EXAMPLES = ['กรอกยอดยกมาที่ไหน', 'เรื่องพัสดุที่จ่ายไปก่อนเริ่มใช้ระบบ ทำยังไง', 'สร้างบัญชีให้ครูยังไง'];

  // ชื่อหน้าจากเมนูซ้าย: ปุ่มลิงก์โชว์ชื่อเมนูแทน path
  const names = {};
  document.querySelectorAll('aside a[href^="/"]').forEach(a => { const n = a.textContent.trim(); if (n) names[a.getAttribute('href').split('?')[0]] ||= n; });
  const esc = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const go = (href, label) => /^\/[\w\-/.?=&%{}]*$/.test(href)
    ? `<a class="ai-go" href="${href.replace(/\{[^}]*\}/g, '')}">${label} ↗</a>` : esc(label);
  function inline(s) {
    s = esc(s);
    s = s.replace(/\[([^\]]+)\]\((\/[^)\s]*)\)/g, (_, t, h) => go(h, t));
    s = s.replace(/`(\/[^`\s]*)`/g, (_, h) => go(h, names[h.split('?')[0]] || h));
    s = s.replace(/`([^`]+)`/g, '<b>$1</b>');
    return s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  }
  function md(text) {
    const out = []; let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const raw of text.split('\n')) {
      const line = raw.trim().replace(/^#{1,4}\s+/, '');
      const ul = line.match(/^[-*•]\s+(.*)/), ol = line.match(/^\d+[.)]\s+(.*)/);
      if (ul || ol) {
        const kind = ul ? 'ul' : 'ol';
        if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${inline((ul || ol)[1])}</li>`);
      } else if (!line) close();
      else { close(); out.push(`<p>${inline(line)}</p>`); }
    }
    close();
    return out.join('');
  }
  function bubble(role, text) {
    const d = document.createElement('div');
    d.className = 'ai-msg ' + role;
    if (role === 'ai') d.innerHTML = md(text); else d.textContent = text;
    log.append(d);
    return d;
  }
  function hello() {
    const d = bubble('ai', '');
    d.innerHTML = '<div class="ai-hi">สวัสดีครับ ถามวิธีใช้ระบบได้เลยครับ เช่น<div class="ai-chips"></div></div>';
    const chips = d.querySelector('.ai-chips');
    EXAMPLES.forEach(t => { const b = document.createElement('button'); b.type = 'button'; b.textContent = t; b.onclick = () => { q.value = t; form.requestSubmit(); }; chips.append(b); });
  }
  function render() {
    log.replaceChildren();
    if (!chat.length) hello();
    chat.forEach(m => bubble(m.role, m.text));
    log.scrollTop = log.scrollHeight;
  }
  const WHY = {
    off: 'ถาม AI ใช้ได้สำหรับโรงเรียนที่เป็นสมาชิกครับ สนใจกดติดต่อเจ้าหน้าที่ด้านล่างได้เลยครับ',
    teacher: 'ถาม AI ใช้ได้เฉพาะไอดีเจ้าหน้าที่ครับ',
    nokey: 'ระบบถาม AI ยังไม่พร้อมใช้งาน กรุณาติดต่อเจ้าหน้าที่ครับ',
    net: 'เชื่อมต่อไม่ได้ ลองปิดแล้วเปิดหน้าต่างนี้ใหม่ครับ',
  };
  function showLeft() {
    if (!status) return;
    left.textContent = status.ok ? `วันนี้ถามได้อีก ${status.left} จาก ${status.limit} คำถาม` : 'ยังใช้งานไม่ได้';
    const blocked = !status.ok || status.left <= 0;
    q.disabled = send.disabled = blocked || busy;
    q.placeholder = !status.ok ? 'ยังใช้งานไม่ได้' : status.left <= 0 ? 'วันนี้ถามครบแล้ว ถามใหม่ได้พรุ่งนี้ครับ' : 'พิมพ์คำถาม เช่น กรอกยอดยกมาที่ไหน';
    // บอกเหตุผลที่ใช้ไม่ได้เสมอ (แสดงซ้ำได้หลัง render ใหม่)
    if (!status.ok && !log.querySelector('.ai-msg.err')) bubble('err', WHY[status.why] || WHY.net);
  }
  async function loadStatus() {
    try {
      const r = await fetch('/ai/status', { cache: 'no-store' });
      if (!r.ok || r.redirected) throw Error();
      status = await r.json();
    } catch { status = { ok: false, why: 'net' }; }
    showLeft();
  }
  function open(focus = true) {
    panel.hidden = false;
    store.set('aiOpen', true);
    render();
    showLeft();
    loadStatus();
    if (focus) setTimeout(() => q.focus(), 50);
  }
  function close() { panel.hidden = true; store.set('aiOpen', false); btn.focus(); }

  btn.addEventListener('click', () => panel.hidden ? open() : close());
  document.getElementById('aiClose').onclick = close;
  document.getElementById('aiClear').onclick = () => { chat = []; store.set('aiChat', chat); render(); q.focus(); };
  document.getElementById('aiHuman').onclick = () => {
    close();
    const chatBtn = document.getElementById('supportChatOpen');
    if (chatBtn) chatBtn.click(); else location.href = '/support';
  };
  panel.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  q.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = q.value.trim();
    if (!text || busy) return;
    busy = true; showLeft();
    const history = chat.slice(-6);
    chat.push({ role: 'me', text }); store.set('aiChat', chat);
    if (chat.length === 1) log.replaceChildren();
    bubble('me', text); q.value = '';
    const wait = bubble('ai', ''); wait.innerHTML = '<span class="ai-typing"><span></span><span></span><span></span></span>';
    log.scrollTop = log.scrollHeight;
    try {
      const r = await fetch('/ai/ask', { method: 'POST', body: new URLSearchParams({ q: text, path: location.pathname + location.search, history: JSON.stringify(history) }) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw Error(data.detail || 'ตอนนี้ AI ตอบไม่ได้ ลองใหม่อีกครั้งครับ');
      wait.innerHTML = md(data.answer);
      chat.push({ role: 'ai', text: data.answer }); store.set('aiChat', chat.slice(-30));
      if (status) status.left = data.left;
      wait.scrollIntoView({ block: 'start', behavior: 'smooth' });
    } catch (err) {
      wait.className = 'ai-msg err'; wait.textContent = err.message;
      chat.pop(); store.set('aiChat', chat); q.value = text;
    } finally { busy = false; showLeft(); if (!q.disabled) q.focus(); }
  });

  if (store.get('aiOpen', false)) open(false);
})();
