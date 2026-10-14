'use strict';
(() => {
  const nav = document.querySelector('.workspace-nav');
  if (!nav) return;
  const toggle = nav.querySelector('.nav-toggle');
  const desktop = window.matchMedia('(min-width: 961px)');
  function sync() {
    const expanded = !desktop.matches || nav.matches(':hover, :focus-within') || nav.classList.contains('is-open');
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? '收起导航' : '展开导航');
  }
  function close() {
    nav.classList.remove('is-open');
    if (nav.contains(document.activeElement)) document.activeElement.blur();
    sync();
  }
  toggle.addEventListener('click', () => {
    if (nav.classList.contains('is-open')) close();
    else { nav.classList.add('is-open'); sync(); }
  });
  nav.addEventListener('pointerenter', sync);
  nav.addEventListener('pointerleave', event => {
    if (event.pointerType === 'mouse') {
      nav.classList.remove('is-open');
      // Mouse clicks must not keep the unused navigation open through focus.
      if (nav.contains(document.activeElement) && !document.activeElement.matches(':focus-visible')) document.activeElement.blur();
    }
    sync();
  });
  nav.addEventListener('focusin', sync);
  nav.addEventListener('focusout', () => setTimeout(sync, 0));
  nav.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
  });
  document.addEventListener('pointerdown', event => {
    if (!nav.contains(event.target)) close();
  });
  desktop.addEventListener('change', close);
  sync();
})();
