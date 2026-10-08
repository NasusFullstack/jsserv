// fx/reveal — 화면에 들어오면 나타난다(.reveal → .is-in). 함께 들어온 것끼리는 차례로(--i).
// 처음 나타날 때 한 번 부를 일(숫자 올리기·글자 풀기 등)은 onReveal 로 건다.

import { scramble } from './text.js';

const hooks = new WeakMap();
let io = null;

function observer() {
  if (io) return io;
  io = new IntersectionObserver((entries) => {
    const fresh = entries.filter((e) => e.isIntersecting);
    fresh.forEach((e, i) => {
      const el = e.target;
      if (!el.style.getPropertyValue('--i')) el.style.setProperty('--i', i);
      el.classList.add('is-in');
      el.querySelectorAll('[data-scramble]').forEach((s) => scramble(s));
      const fn = hooks.get(el);
      if (fn) { hooks.delete(el); fn(); }
      io.unobserve(el);
    });
  }, { threshold: .12, rootMargin: '0px 0px -6% 0px' });
  return io;
}

export function reveal(el, onReveal) {
  if (onReveal) hooks.set(el, onReveal);
  if (!('IntersectionObserver' in window)) { el.classList.add('is-in'); onReveal?.(); return; }
  observer().observe(el);
}

export function revealAll(root = document) {
  root.querySelectorAll('.reveal:not(.is-in)').forEach((el) => reveal(el));
}
