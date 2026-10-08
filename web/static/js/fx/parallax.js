// fx/parallax — 스크롤과 마우스 위치를 CSS 변수로 흘려보낸다. 레이어들은 이 값을 각자 다른 배율로 써서 깊이가 생긴다.
//   --sy        스크롤 px          (layers.css: 오로라 0.15배, 격자 0.35배)
//   --px, --py  마우스 -1 ~ 1      (부드럽게 따라감)
//   --mx, --my  마우스 px          (마우스 빛)
//   --hero-out  첫 화면을 지나간 정도 0 ~ 1
//   --progress  전체 스크롤 0 ~ 1   (맨 위 막대)

import { loop, lerp, reduced } from '../core/motion.js';

export const pointer = { x: innerWidth / 2, y: innerHeight / 3, nx: 0, ny: 0, active: false };

export function startParallax() {
  const root = document.documentElement.style;
  const topbar = document.getElementById('topbar');
  let tx = 0, ty = 0, sx = 0, sy = 0;

  addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse') return;
    pointer.x = e.clientX;
    pointer.y = e.clientY;
    pointer.active = true;
    tx = (e.clientX / innerWidth) * 2 - 1;
    ty = (e.clientY / innerHeight) * 2 - 1;
    root.setProperty('--mx', `${e.clientX}px`);
    root.setProperty('--my', `${e.clientY}px`);
  }, { passive: true });
  document.addEventListener('pointerleave', () => { pointer.active = false; });

  const onScroll = () => {
    const y = scrollY;
    const max = document.documentElement.scrollHeight - innerHeight;
    root.setProperty('--sy', y.toFixed(1));
    root.setProperty('--hero-out', Math.min(1, y / (innerHeight * .9)).toFixed(3));
    root.setProperty('--progress', max > 0 ? (y / max).toFixed(4) : '0');
    if (topbar) topbar.classList.toggle('is-scrolled', y > 24);
  };
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  if (reduced()) return;
  loop(() => {
    sx = lerp(sx, tx, .06);
    sy = lerp(sy, ty, .06);
    pointer.nx = sx;
    pointer.ny = sy;
    root.setProperty('--px', sx.toFixed(4));
    root.setProperty('--py', sy.toFixed(4));
  });
}
