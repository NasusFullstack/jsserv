// home/lab — 서버 칸: 터미널처럼 찍히는 상태(가동 시간이 실시간으로 올라감)와 응답 시간 박동.

import { $, h } from '../core/dom.js';
import { ping } from '../core/api.js';
import { uptime } from '../core/format.js';
import { startPulse } from '../fx/pulse.js';
import { reveal } from '../fx/reveal.js';

export function renderLab(data) {
  const term = $('#term');
  const started = Date.now() - data.server.uptime * 1000;
  const up = h('span.v', uptime(data.server.uptime));
  const rows = [
    [h('span.p', '$ '), h('span.v', 'jsserv status')],
    [h('span.k', 'server   '), h('span.ok', '● online'), '   ', h('span.v', `${data.server.name} v${data.server.version}`)],
    [h('span.k', 'uptime   '), up],
    [h('span.k', 'works    '), h('span.v', `${data.works.length}`)],
    [''],
    [h('span.p', '$ '), h('span.v', 'jsserv features')],
    ...data.services.map((s) => [
      h('span.ok', '● '), h('span.c', s.name.padEnd(10)), h('span.k', `v${s.version}`.padEnd(9)), h('span.v', s.about),
    ]),
    [''],
    [h('span.p', '$ '), h('span.cursor')],
  ];
  const draw = () => term.replaceChildren(...rows.map((r, i) => h('span.ln', { style: { '--i': i } }, r)));
  // 화면에 들어왔을 때 한 줄씩 찍힌다
  reveal(term.closest('.lab__term'), draw);
  setInterval(() => { up.textContent = uptime((Date.now() - started) / 1000); }, 1000);
  $('#serverName').textContent = data.server.name;
  $('#serverVer').textContent = `v${data.server.version}`;

  const pulse = startPulse($('#pulse'));
  const ms = $('#pingMs');
  const note = $('#pingNote');
  const history = [];
  const measure = async () => {
    const t = await ping();
    pulse.beat(t);
    document.querySelectorAll('.live-dot').forEach((d) => d.classList.toggle('is-down', t == null));
    if (t == null) { ms.textContent = '--'; note.textContent = '응답 없음 — 다시 시도 중'; return; }
    history.push(t);
    if (history.length > 20) history.shift();
    ms.textContent = t;
    const sorted = [...history].sort((a, b) => a - b);
    const mid = sorted[Math.floor(sorted.length / 2)];   // 가운데 값: 처음 한 번 느린 연결에 안 휘둘린다
    note.textContent = `이 브라우저 → 서버 왕복 · 보통 ${mid}ms · 최근 ${history.length}번`;
  };
  measure();
  setInterval(() => { if (!document.hidden) measure(); }, 4000);
}
