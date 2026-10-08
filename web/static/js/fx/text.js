// fx/text — 글자 효과.
//   splitLetters(el)  글자를 하나씩 쪼개 차례로 솟아오르게 (CSS .ch, --i)
//   glitch(el)        가끔 지지직 (색 어긋남)
//   scramble(el)      무작위 글자에서 진짜 글자로 풀려 나온다
//   countUp(el, n)    숫자가 0 에서 n 까지 올라간다

import { reduced } from '../core/motion.js';
import { num } from '../core/format.js';

export function splitLetters(el) {
  const text = el.textContent.trim();
  el.setAttribute('aria-label', text);
  el.dataset.text = text;
  el.replaceChildren(...[...text].map((c, i) => {
    const s = document.createElement('span');
    s.className = c === ' ' ? 'ch space' : 'ch';
    s.textContent = c === ' ' ? ' ' : c;
    s.style.setProperty('--i', i);
    s.setAttribute('aria-hidden', 'true');
    return s;
  }));
  // 그라데이션이 글자 위를 한 번 쓸고 지나간다
  if (!reduced()) {
    let t0 = 0;
    const sweep = (now) => {
      t0 ||= now;
      const p = Math.min(1, (now - t0) / 2200);
      el.style.setProperty('--sweep', (1 - (1 - p) ** 3).toFixed(4));
      if (p < 1) requestAnimationFrame(sweep);
    };
    setTimeout(() => requestAnimationFrame(sweep), 900);
  }
}

export function glitch(el, every = 7000) {
  if (reduced()) return;
  const fire = () => {
    el.classList.add('is-glitch');
    setTimeout(() => el.classList.remove('is-glitch'), 340);
    setTimeout(fire, every * (.6 + Math.random() * .8));
  };
  setTimeout(fire, 2600);
}

const GLYPHS = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#$%&*+=<>/\\';

export function scramble(el, duration = 700) {
  const target = el.dataset.final || el.textContent;
  el.dataset.final = target;
  if (reduced()) { el.textContent = target; return; }
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / duration);
    const fixed = Math.floor(p * target.length);
    let out = target.slice(0, fixed);
    for (let i = fixed; i < target.length; i++) {
      out += target[i] === ' ' ? ' ' : GLYPHS[(Math.random() * GLYPHS.length) | 0];
    }
    el.textContent = out;
    if (p < 1) requestAnimationFrame(step);
    else el.textContent = target;
  };
  requestAnimationFrame(step);
}

export function countUp(el, value, duration = 1400) {
  value = Math.round(value || 0);
  if (reduced() || value === 0) { el.textContent = num(value); return; }
  const from = Number(el.dataset.shown || 0);
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - p) ** 4;
    el.textContent = num(from + (value - from) * eased);
    if (p < 1) requestAnimationFrame(step);
    else el.dataset.shown = String(value);
  };
  requestAnimationFrame(step);
}
