// fx/field — 배경 레이어 2번: 떠다니는 점들이 가까우면 선으로 이어진다. 마우스 근처의 점은 밀려나고 마우스와도 이어진다.
//
// 가볍게: 초당 30번만 그린다(느린 배경이라 차이가 안 보인다), 고해상도 화면에서도 1배로 그린다(흐릿한 배경이라 충분),
// 점은 넓이에 맞춰 최대 80개, 탭이 숨으면 쉰다. 처음 3초 동안 그리는 데 오래 걸리는 컴퓨터면 멈춘 한 장으로 바꾼다.
// 움직임 줄이기 설정이면 처음부터 한 장만 그린다.

import { loop, reduced } from '../core/motion.js';
import { pointer } from './parallax.js';

const COLORS = ['94,234,212', '167,139,250', '96,165,250', '251,113,133'];
const LINK = 140;      // 이 거리 안이면 잇는다
const PUSH = 150;      // 마우스가 미는 거리
const FPS = 30;
const MAX_DOTS = 80;
const SLOW_MS = 14;    // 한 장 그리는 데 평균 이보다 오래 걸리면 멈춘 그림으로

export function startField(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, dpr = 1, dots = [];

  const resize = () => {
    dpr = 1;
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.min(MAX_DOTS, Math.round((W * H) / 16000));
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

  let acc = 0, spent = 0, drawn = 0, stopped = reduced();
  resize();
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { resize(); if (stopped) frame(0, 0); }, 150); });
  if (stopped) { frame(0, 0); return; }

  const stop = loop((dt, now) => {
    acc += dt;
    if (acc < 1 / FPS) return;
    const t0 = performance.now();
    frame(acc, now);
    acc = 0;
    if (drawn < 90) {           // 처음 3초: 이 컴퓨터가 감당하는지 본다
      spent += performance.now() - t0;
      drawn++;
      if (drawn === 90 && spent / drawn > SLOW_MS) { stop(); stopped = true; }
    }
  });
}
