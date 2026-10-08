// fx/field — 배경 레이어 2번: 떠다니는 점들이 가까우면 선으로 이어진다. 마우스 근처의 점은 밀려나고 마우스와도 이어진다.
// 화면 넓이에 맞춰 점 수를 정하고(최대 130), 탭이 숨으면 쉰다. 움직임 줄이기면 한 장만 그린다.

import { loop, reduced } from '../core/motion.js';
import { pointer } from './parallax.js';

const COLORS = ['94,234,212', '167,139,250', '96,165,250', '251,113,133'];
const LINK = 130;      // 이 거리 안이면 잇는다
const PUSH = 150;      // 마우스가 미는 거리

export function startField(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, dpr = 1, dots = [];

  const resize = () => {
    dpr = Math.min(2, devicePixelRatio || 1);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.min(130, Math.round((W * H) / 13000));
    dots = Array.from({ length: n }, (_, i) => ({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - .5) * 14,
      vy: (Math.random() - .5) * 14,
      r: Math.random() * 1.4 + .5,
      c: COLORS[i % 7 === 0 ? 3 : i % 3],
      z: Math.random() * .8 + .2,       // 깊이: 가까운 점일수록 크고 마우스 시차가 크다
      tw: Math.random() * Math.PI * 2,
    }));
  };

  const frame = (dt, now) => {
    ctx.clearRect(0, 0, W, H);
    const ox = -pointer.nx * 18, oy = -pointer.ny * 18;
    const mx = pointer.x, my = pointer.y;
    for (const d of dots) {
      if (dt) {
        d.x += d.vx * dt;
        d.y += d.vy * dt;
        if (pointer.active) {
          const dx = d.x - mx, dy = d.y - my, dist = Math.hypot(dx, dy);
          if (dist < PUSH && dist > .1) {
            const f = (1 - dist / PUSH) * 60 * dt;
            d.x += (dx / dist) * f;
            d.y += (dy / dist) * f;
          }
        }
        if (d.x < -20) d.x = W + 20; else if (d.x > W + 20) d.x = -20;
        if (d.y < -20) d.y = H + 20; else if (d.y > H + 20) d.y = -20;
      }
      d.sx = d.x + ox * d.z;
      d.sy = d.y + oy * d.z;
    }
    // 선
    ctx.lineWidth = 1;
    for (let i = 0; i < dots.length; i++) {
      const a = dots[i];
      for (let j = i + 1; j < dots.length; j++) {
        const b = dots[j];
        const dx = a.sx - b.sx, dy = a.sy - b.sy;
        if (Math.abs(dx) > LINK || Math.abs(dy) > LINK) continue;
        const dist = Math.hypot(dx, dy);
        if (dist < LINK) {
          ctx.strokeStyle = `rgba(${a.c},${(1 - dist / LINK) * .22})`;
          ctx.beginPath();
          ctx.moveTo(a.sx, a.sy);
          ctx.lineTo(b.sx, b.sy);
          ctx.stroke();
        }
      }
      if (pointer.active) {
        const dist = Math.hypot(a.sx - mx, a.sy - my);
        if (dist < PUSH * 1.3) {
          ctx.strokeStyle = `rgba(94,234,212,${(1 - dist / (PUSH * 1.3)) * .35})`;
          ctx.beginPath();
          ctx.moveTo(a.sx, a.sy);
          ctx.lineTo(mx, my);
          ctx.stroke();
        }
      }
    }
    // 점 (반짝임)
    for (const d of dots) {
      const tw = .55 + Math.sin(now / 900 + d.tw) * .45;
      ctx.fillStyle = `rgba(${d.c},${.35 + tw * .5 * d.z})`;
      ctx.beginPath();
      ctx.arc(d.sx, d.sy, d.r * (0.7 + d.z), 0, Math.PI * 2);
      ctx.fill();
    }
  };

  resize();
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(resize, 150); });
  if (reduced()) { frame(0, 0); return; }
  loop(frame);
}
