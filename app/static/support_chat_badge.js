// คอนโซลผู้ขาย: นับข้อความโรงเรียนที่ยังไม่อ่าน + แจ้งเตือนเมื่อมีข้อความใหม่ (เสียง + ป๊อปอัปเครื่อง + ตัวเลขบนแท็บ)
(() => {
  const count = document.getElementById('consoleChatCount'), title = document.title;
  let seen = null;
  function ask() { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); }
  document.addEventListener('click', ask, { once: true });
  function beep() {
    try {
      const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = 880; g.gain.setValueAtTime(0.15, a.currentTime); g.gain.exponentialRampToValueAtTime(0.001, a.currentTime + 0.5);
      o.connect(g); g.connect(a.destination); o.start(); o.stop(a.currentTime + 0.5);
    } catch {}
  }
  async function poll() {
    try {
      const r = await fetch('/admin-console/chat/inbox');
      if (!r.ok || r.redirected) return;
      const rows = await r.json(), n = rows.reduce((a, r) => a + r.unread, 0);
      if (count) count.textContent = n ? '(' + n + ')' : '';
      document.title = (n ? '(' + n + ') ' : '') + title;
      if (seen !== null && n > seen) {
        beep();
        const who = rows.find(r => r.unread);
        if ('Notification' in window && Notification.permission === 'granted') {
          const note = new Notification('มีข้อความใหม่จากโรงเรียน', { body: who ? who.name + ': ' + who.preview : '', tag: 'ddoc-chat' });
          note.onclick = () => { window.focus(); location.href = '/admin-console/chat'; };
        }
      }
      seen = n;
    } catch {}
  }
  poll(); setInterval(poll, 15000);
})();
