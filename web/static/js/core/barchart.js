// core/barchart — 막대그래프 하나 (계열 하나). 첫 화면과 관리 화면이 같이 쓴다.
//
// 규칙: 막대 사이 2px 틈, 위쪽만 4px 둥글게(바닥에 붙음), 눈금선 3줄은 흐리게,
// 계열이 하나라서 범례 없이 제목이 이름을 대신한다. 마우스를 올리면 막대마다 말풍선.
// 글을 못 보는 사람을 위해 같은 숫자를 표로도 숨겨 둔다.

import { h } from './dom.js';
import { num, md } from './format.js';

function niceMax(v) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function barPath(x, y, w, base, r) {
  const hgt = base - y;
  if (hgt <= 0) return '';
  r = Math.min(r, w / 2, hgt);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

/**
 * barChart(상자, { data: [{ day, value }], color, unit: '명', label: '방문자' })
 * 상자 크기가 바뀌면 다시 그린다. 지우는 함수를 돌려준다.
 */
export function barChart(box, { data, color, unit = '', label = '' }) {
  box.classList.add('bars');
  const tip = h('div.tip');
  const table = h('table.sr-only', h('caption', label),
    h('tr', h('th', '날짜'), h('th', label)),
    data.map((d) => h('tr', h('td', d.day), h('td', num(d.value) + unit))));

  const draw = () => {
    const W = Math.max(240, box.clientWidth);
    const H = Math.max(140, box.clientHeight || 200);
    const pad = { l: 34, r: 6, t: 10, b: 24 };
    const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
    const iw = W - pad.l - pad.r;
    const ih = H - pad.t - pad.b;
    const step = iw / data.length;
    const gap = 2;
    const bw = Math.min(step - gap, Math.max(4, step * .62));   // 가는 막대: 칸의 62%
    const base = pad.t + ih;
    const y = (v) => pad.t + ih - (v / max) * ih;

    const svg = h('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': label });
    const grid = h('g.grid');
    [0, .5, 1].forEach((f) => {
      const v = max * f;
      grid.append(h('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v) }),
        h('text', { x: pad.l - 8, y: y(v) + 4, 'text-anchor': 'end' }, num(v)));
    });
    svg.append(grid);

    const bars = h('g');
    const hits = h('g');
    data.forEach((d, i) => {
      const x = pad.l + i * step + (step - bw) / 2;
      const bar = h('path.bar', { d: barPath(x, y(d.value), bw, base, 4), fill: color });
      bars.append(bar);
      const hit = h('rect.hit', { x: pad.l + i * step, y: pad.t, width: step, height: ih });
      const show = () => {
        box.classList.add('is-hover');
        bars.querySelectorAll('.is-on').forEach((b) => b.classList.remove('is-on'));
        bar.classList.add('is-on');
        tip.replaceChildren(h('span', d.day), h('b', num(d.value)), ` ${unit}`);
        tip.style.left = `${((x + bw / 2) / W) * 100}%`;
        tip.style.top = `${Math.min(y(d.value), base - 8)}px`;
        tip.classList.add('is-on');
      };
      hit.addEventListener('pointerenter', show);
      hit.addEventListener('pointerdown', show);
      hits.append(hit);
    });
    svg.append(bars);

    // 아래 날짜: 처음·가운데·끝만
    const xl = h('g.xlab');
    const marks = new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]);
    marks.forEach((i) => {
      if (!data[i]) return;
      const anchor = i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle';
      const x = i === 0 ? pad.l : i === data.length - 1 ? W - pad.r : pad.l + i * step + step / 2;
      xl.append(h('text', { x, y: H - 4, 'text-anchor': anchor }, i === data.length - 1 ? '오늘' : md(data[i].day)));
    });
    svg.append(xl, hits);
    if (data.every((d) => !d.value)) {
      svg.append(h('text.empty', { x: pad.l + iw / 2, y: pad.t + ih / 2, 'text-anchor': 'middle' }, '아직 기록이 없습니다'));
    }
    svg.addEventListener('pointerleave', () => {
      box.classList.remove('is-hover');
      tip.classList.remove('is-on');
    });
    box.replaceChildren(svg, tip, table);
  };

  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(box);
  return () => ro.disconnect();
}
