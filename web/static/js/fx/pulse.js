// fx/pulse — 서버 심장 박동 그래프. 왼쪽으로 흘러가는 선에, 서버가 답할 때마다 맥박이 뛴다(높이 = 응답 시간).

import { loop, reduced, visibility } from '../core/motion.js';

export function startPulse(canvas) {
  const ctx = canvas.getContext('2d');
  const seen = visibility(canvas);
  let W = 0, H = 0, dpr = 1;
  const SPEED = 60;            // px/초
  const FPS = 30;              // 가볍게: 초당 30번만 그린다
  let samples = [];            // 화면 오른쪽 끝에서 생긴 높이들
  let beat = null;             // 진행 중인 맥박 { t, amp }
  let t = 0;

  const resize = () => {
    dpr = Math.min(2, devicePixelRatio || 1);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    samples = new Array(Math.ceil(W / 2) + 2).fill(0);
  };

  // 맥박 모양: 작은 혹 → 아래로 → 크게 위로 → 아래로 → 잔물결
  const shape = (p) => {
    if (p < .12) return Math.sin((p / .12) * Math.PI) * .15;
    if (p < .2) return -((p - .12) / .08) * .25;
    if (p < .3) return -.25 + ((p - .2) / .1) * 1.25;
    if (p < .4) return 1 - ((p - .3) / .1) * 1.35;
    if (p < .55) return -.35 + ((p - .4) / .15) * .35;
    if (p < .8) return Math.sin(((p - .55) / .25) * Math.PI) * .12;
    return 0;
  };

  const draw = () => {
    ctx.clearRect(0, 0, W, H);
    const mid = H * .6;
    // 바닥 눈금
    ctx.strokeStyle = 'rgba(255,255,255,.05)';
    ctx.lineWidth = 1;
    for (let y = 0; y < H; y += 24) { ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(W, y + .5); ctx.stroke(); }
    // 선
    const g = ctx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, 'rgba(94,234,212,0)');
    g.addColorStop(.6, 'rgba(94,234,212,.7)');
    g.addColorStop(1, 'rgba(167,139,250,1)');
    // 빛 번짐은 그림자 흐림(무거움) 대신 굵고 옅은 선을 한 번 더 그어서
    ctx.beginPath();
    samples.forEach((v, i) => {
      const x = i * 2, y = mid - v * H * .5;
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.strokeStyle = 'rgba(94,234,212,.14)';
    ctx.lineWidth = 7;
    ctx.stroke();
    ctx.strokeStyle = g;
    ctx.lineWidth = 2;
    ctx.stroke();
    // 앞머리 점
    const last = samples[samples.length - 1];
    ctx.fillStyle = '#a78bfa';
    ctx.beginPath();
    ctx.arc(W - 2, mid - last * H * .5, 3.5, 0, Math.PI * 2);
    ctx.fill();
  };

  let acc = 0, wait = 0;
  const frame = (dt) => {
    if (!seen.on) return;
    wait += dt;
    if (wait < 1 / FPS) return;
    dt = wait;
    wait = 0;
    t += dt;
    acc += dt * SPEED / 2;
    while (acc >= 1) {
      acc -= 1;
      let v = (Math.random() - .5) * .02;
      if (beat) {
        const p = (t - beat.t) / .9;
        if (p >= 1) beat = null; else v += shape(p) * beat.amp;
      }
      samples.push(v);
      samples.shift();
    }
    draw();
  };

  resize();
  addEventListener('resize', resize);
  if (!reduced()) loop(frame); else draw();

  return {
    /** 응답 시간 ms (null = 실패) */
    beat(ms) {
      const amp = ms == null ? -.6 : Math.min(1, .45 + Math.min(ms, 400) / 400 * .55);
      beat = { t, amp };
      if (reduced()) { samples = samples.map(() => 0); draw(); }
    },
  };
}
