// core/motion — 움직임 설정과 프레임 돌리기. 효과(fx)들은 이것을 통해서만 움직인다.

const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
export const reduced = () => mq.matches;
export const finePointer = () => window.matchMedia('(pointer: fine)').matches;

/** 매 프레임 fn(dt초, 지금ms) 을 부른다. 탭이 숨으면 쉰다. 멈추는 함수를 돌려준다 */
export function loop(fn) {
  let id = 0;
  let last = performance.now();
  let on = true;
  const tick = (now) => {
    if (!on) return;
    const dt = Math.min(.05, (now - last) / 1000);
    last = now;
    fn(dt, now);
    id = requestAnimationFrame(tick);
  };
  const vis = () => {
    cancelAnimationFrame(id);
    if (!document.hidden && on) { last = performance.now(); id = requestAnimationFrame(tick); }
  };
  document.addEventListener('visibilitychange', vis);
  id = requestAnimationFrame(tick);
  return () => { on = false; cancelAnimationFrame(id); document.removeEventListener('visibilitychange', vis); };
}

export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** 화면에 보이는 동안만 on 이 true 인 상자 */
export function visibility(el, rootMargin = '100px') {
  const state = { on: true };
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([e]) => { state.on = e.isIntersecting; }, { rootMargin }).observe(el);
  }
  return state;
}
