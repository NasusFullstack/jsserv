// fx/cover — 대표 그림이 없는 작품에 그 작품만의 그림을 그려 준다.
// 작품 주소 이름이 씨앗이라 같은 작품은 언제나 같은 그림. 강조 색에서 색을 뽑는다.
//   흐름선(보이지 않는 바람을 따라 그은 선 수백 개) + 빛 덩어리 + 점 격자 + 제목 첫 글자 윤곽

import { paletteFrom, rng, seedOf } from '../core/color.js';

export function paintCover(canvas, { seed, accent, title }) {
  const dpr = Math.min(2, devicePixelRatio || 1);
  const W = canvas.clientWidth || 640;
  const H = canvas.clientHeight || 400;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const R = rng(seedOf(seed));
  const pal = paletteFrom(accent || '#5eead4');

  // 바탕
  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, pal.deep);
  bg.addColorStop(1, pal.mid);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // 빛 덩어리
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < 3; i++) {
    const x = R() * W, y = R() * H, r = (.35 + R() * .45) * Math.max(W, H);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, [pal.main(.28), pal.side(.22), pal.far(.18)][i]);
    g.addColorStop(1, 'transparent');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }

  // 흐름선: 사인 몇 개를 겹친 바람
  const f1 = .002 + R() * .004, f2 = .002 + R() * .004, p1 = R() * 10, p2 = R() * 10, swirl = 1.5 + R() * 2.5;
  const angle = (x, y) => (Math.sin(x * f1 + p1) + Math.cos(y * f2 + p2) + Math.sin((x + y) * f1 * .7)) * swirl;
  const lines = Math.round((W * H) / 900);
  ctx.lineWidth = .9;
  for (let i = 0; i < lines; i++) {
    let x = R() * W, y = R() * H;
    const col = R();
    ctx.strokeStyle = col < .6 ? pal.main(.10) : col < .9 ? pal.side(.09) : 'rgba(255,255,255,.08)';
    ctx.beginPath();
    ctx.moveTo(x, y);
    const steps = 18 + R() * 40;
    for (let s = 0; s < steps; s++) {
      const a = angle(x, y);
      x += Math.cos(a) * 4;
      y += Math.sin(a) * 4;
      ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.globalCompositeOperation = 'source-over';

  // 점 격자
  ctx.fillStyle = 'rgba(255,255,255,.07)';
  for (let x = 12; x < W; x += 22) for (let y = 12; y < H; y += 22) ctx.fillRect(x, y, 1, 1);

  // 제목 첫 글자 윤곽
  const ch = [...(title || '?').trim()][0] || '?';
  ctx.font = `800 ${Math.round(H * 1.05)}px "Pretendard Variable", "Space Grotesk", sans-serif`;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'alphabetic';
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = 'rgba(255,255,255,.12)';
  ctx.strokeText(ch, W * .97, H * .93);
  const tg = ctx.createLinearGradient(W * .5, 0, W, H);
  tg.addColorStop(0, pal.main(.0));
  tg.addColorStop(1, pal.main(.16));
  ctx.fillStyle = tg;
  ctx.fillText(ch, W * .97, H * .93);
}
