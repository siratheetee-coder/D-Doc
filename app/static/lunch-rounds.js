// List controls are read-only. Payments and document actions stay in the source workflow.
(() => {
  const formBox = document.getElementById('new-round');
  function revealForm() {
    if (!formBox) return;
    if (location.hash === '#new-round' || document.querySelector('[data-calendar-restored]:not([hidden])')) {
      formBox.open = true;
      requestAnimationFrame(() => formBox.scrollIntoView({block:'start'}));
    }
  }
  revealForm();
  addEventListener('hashchange', revealForm);
  document.querySelectorAll('a[href$="#new-round"]').forEach(a => a.addEventListener('click', () => {
    if (new URL(a.href).pathname !== location.pathname) return;
    formBox.open = true;
    requestAnimationFrame(() => formBox.scrollIntoView({block:'start'}));
  }));
  const cards = [...document.querySelectorAll('[data-round-state]')];
  const search = document.getElementById('lr-search');
  const tabs = [...document.querySelectorAll('[data-round-filter]')];
  const empty = document.getElementById('lr-no-matches');
  let filter = 'all';
  const normal = s => (s || '').normalize('NFKC').toLocaleLowerCase('th').trim();
  function update() {
    const q = normal(search?.value);
    let n = 0;
    const counts = {all:0, active:0, complete:0};
    cards.forEach(card => {
      const match = normal(card.dataset.roundSearch).includes(q);
      if (match) { counts.all++; counts[card.dataset.roundState]++; }
      card.hidden = !match || (filter !== 'all' && filter !== card.dataset.roundState);
      if (!card.hidden) n++;
    });
    tabs.forEach(tab => {
      const on = tab.dataset.roundFilter === filter;
      tab.classList.toggle('on', on);
      tab.setAttribute('aria-pressed', String(on));
      tab.querySelector('b').textContent = counts[tab.dataset.roundFilter];
    });
    if (empty) empty.hidden = n !== 0;
  }
  tabs.forEach(tab => tab.addEventListener('click', () => { filter = tab.dataset.roundFilter; update(); }));
  search?.addEventListener('input', update);
  update();
  document.addEventListener('click', e => document.querySelectorAll('.lr-more[open],.lr-help[open]').forEach(d => {
    if (!d.contains(e.target)) d.open = false;
  }));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.lr-more[open],.lr-help[open]').forEach(d => {
      d.open = false; d.querySelector('summary').focus();
    });
  });
})();
