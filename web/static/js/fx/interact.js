// fx/interact — 마우스에 반응하는 작은 효과들.
//   spotlight(el)  유리판·카드 안의 마우스 위치를 --lx, --ly 로 (테두리 빛)
//   tilt(el)       카드가 마우스 쪽으로 살짝 기운다 (--rx, --ry)
//   magnetic(el)   버튼이 마우스 쪽으로 살짝 끌려온다
// 터치 화면이나 움직임 줄이기에서는 아무것도 안 한다.

import { finePointer, reduced } from '../core/motion.js';

const on = () => finePointer() && !reduced();

export function spotlight(el) {
  if (!finePointer()) return;
  el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    el.style.setProperty('--lx', `${e.clientX - r.left}px`);
    el.style.setProperty('--ly', `${e.clientY - r.top}px`);
  }, { passive: true });
}

export function tilt(el, max = 7) {
  spotlight(el);
  if (!on()) return;
  el.addEventListener('pointerenter', () => el.classList.add('is-tilting'));
  el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - .5;
    const y = (e.clientY - r.top) / r.height - .5;
    el.style.setProperty('--ry', `${(x * max).toFixed(2)}deg`);
    el.style.setProperty('--rx', `${(-y * max).toFixed(2)}deg`);
  }, { passive: true });
  el.addEventListener('pointerleave', () => {
    el.classList.remove('is-tilting');
    el.style.setProperty('--rx', '0deg');
    el.style.setProperty('--ry', '0deg');
  });
}

export function magnetic(el, pull = .28) {
  if (!on()) return;
  el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    const x = e.clientX - (r.left + r.width / 2);
    const y = e.clientY - (r.top + r.height / 2);
    el.style.transform = `translate(${x * pull}px, ${y * pull}px)`;
  }, { passive: true });
  el.addEventListener('pointerleave', () => { el.style.transform = ''; });
}

/** 문서 안의 [data-magnetic], [data-tilt], .glass 에 한 번에 */
export function wireInteractions(root = document) {
  root.querySelectorAll('[data-magnetic]').forEach((el) => magnetic(el));
  root.querySelectorAll('[data-tilt]').forEach((el) => tilt(el, 5));
  root.querySelectorAll('.glass:not([data-tilt])').forEach((el) => spotlight(el));
}
