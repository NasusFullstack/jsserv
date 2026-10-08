// fx/parallax — 스크롤과 마우스에 따라 배경 레이어를 서로 다른 양만큼 옮긴다(깊이감).
//
// 가볍게 하려고 지키는 것:
// - 문서 맨 위(:root)의 CSS 변수를 매 프레임 바꾸지 않는다(그러면 페이지 전체 스타일을 다시 계산한다).
//   대신 움직일 요소에 transform 을 직접 넣는다 — 그 요소만 GPU 가 옮긴다
// - 마우스가 멈추고 레이어가 따라잡으면 프레임 돌리기를 멈춘다
// - 스크롤은 프레임당 한 번만 처리한다
//
//   오로라   스크롤 0.15배 · 마우스 반대로 24px
//   격자     스크롤 0.35배 · 마우스 반대로 8px
//   첫 화면  .hero 의 --hero-out (첫 화면을 지나간 정도 0~1, 그 안에서만 다시 계산)
//   진행 막대 .scroll-progress 의 --progress
//   마우스 빛 .layer-spot 을 transform 으로 옮김

import { lerp, reduced } from '../core/motion.js';

export const pointer = { x: innerWidth / 2, y: innerHeight / 3, nx: 0, ny: 0, active: false };

export function startParallax() {
  const aurora = document.querySelector('.layer--aurora');
  const grid = document.querySelector('.layer--grid');
  const spot = document.querySelector('.layer-spot');
  const hero = document.querySelector('.hero');
  const progress = document.querySelector('.scroll-progress');
  const topbar = document.getElementById('topbar');
  const still = reduced();
  let tx = 0, ty = 0, sy = 0, raf = 0, scrolled = false;

  const place = () => {
    if (still) return;
    if (aurora) aurora.style.transform = `translate3d(${(-pointer.nx * 24).toFixed(1)}px, ${(-sy * .15 - pointer.ny * 24).toFixed(1)}px, 0)`;
    if (grid) grid.style.transform = `translate3d(${(-pointer.nx * 8).toFixed(1)}px, ${(-sy * .35).toFixed(1)}px, 0)`;
  };

  const frame = () => {
    raf = 0;
    if (scrolled) {
      scrolled = false;
      sy = scrollY;
      const max = document.documentElement.scrollHeight - innerHeight;
      if (hero) hero.style.setProperty('--hero-out', Math.min(1, sy / (innerHeight * .9)).toFixed(3));
      if (progress) progress.style.setProperty('--progress', max > 0 ? (sy / max).toFixed(4) : '0');
      if (topbar) topbar.classList.toggle('is-scrolled', sy > 24);
    }
    // 마우스 쪽으로 부드럽게 따라가다가 다 따라잡으면 멈춘다
    const nx = lerp(pointer.nx, tx, .08), ny = lerp(pointer.ny, ty, .08);
    const moving = Math.abs(nx - tx) > .001 || Math.abs(ny - ty) > .001;
    pointer.nx = moving ? nx : tx;
    pointer.ny = moving ? ny : ty;
    place();
    if (moving) kick();
  };
  const kick = () => { if (!raf) raf = requestAnimationFrame(frame); };

  addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse') return;
    pointer.x = e.clientX;
    pointer.y = e.clientY;
    pointer.active = true;
    tx = (e.clientX / innerWidth) * 2 - 1;
    ty = (e.clientY / innerHeight) * 2 - 1;
    if (spot) spot.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
    if (!still) kick();
  }, { passive: true });
  document.addEventListener('pointerleave', () => { pointer.active = false; });
  addEventListener('scroll', () => { scrolled = true; kick(); }, { passive: true });
  scrolled = true;
  kick();
}
