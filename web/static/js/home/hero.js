// home/hero — 첫 화면: 이름(글자 쪼개기·지지직), 한 줄 소개, 실시간 판(숫자·14일 선), 흐르는 띠, 시계.

import { $, $$, h } from '../core/dom.js';
import { kstClock, num } from '../core/format.js';
import { countUp, glitch, splitLetters } from '../fx/text.js';

export function renderHero(data) {
  const { site, stats, works } = data;
  $$('[data-site-name]').forEach((el) => { el.textContent = site.name; });
  document.title = document.title || site.name;

  const name = $('#heroName');
  splitLetters(name);
  fitName(name);
  glitch(name);
  if (site.headline) $('#heroHeadline').textContent = site.headline;
  $('#heroCount').textContent = `${String(works.length).padStart(2, '0')} WORKS`;
  $('#liveToday').textContent = num(stats.today.visitors);

  // 실시간 판: 첫 화면이 다 나타난 뒤 숫자가 올라간다
  const plays = works.reduce((s, w) => s + (w.plays || 0), 0);
  setTimeout(() => {
    countUp($('#statToday'), stats.today.visitors);
    countUp($('#statTotal'), stats.total.visitors);
    countUp($('#statWorks'), works.length);
    countUp($('#statPlays'), plays);
  }, 1100);
  sparkline($('#spark'), stats.days.map((d) => d.visitors));

  marquee(site.roles?.length ? site.roles : ['GAME', 'APP', 'SERVER', 'TOOL', 'WEB']);
  clock();
}

/** 이름이 한 줄에 꽉 차도록 글자 크기를 맞춘다 (이름을 관리 화면에서 바꿔도 안 넘친다) */
function fitName(el) {
  const fit = () => {
    el.style.removeProperty('--name-size');
    const box = el.parentElement.clientWidth;
    const size = parseFloat(getComputedStyle(el).fontSize);
    // 글자 칸 너비의 합 (움직이는 중인 글자의 기울기는 offsetWidth 에 안 들어간다)
    const width = [...el.children].reduce((s, c) => s + c.offsetWidth, 0);
    const natural = width / size;                        // 글자 크기 1px 당 너비
    const target = Math.max(32, Math.min(184, (box * .98) / natural));
    el.style.setProperty('--name-size', `${target.toFixed(1)}px`);
    // 단어 전체에 그라데이션 하나가 걸치도록, 글자마다 자기 자리(px)를 알려 준다
    let x = 0;
    [...el.children].forEach((c) => { c.style.setProperty('--off', `${x}px`); x += c.offsetWidth; });
    el.style.setProperty('--ww', `${x}px`);
  };
  fit();
  document.fonts?.ready.then(fit);
  let t;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(fit, 120); });
}

function sparkline(svg, values) {
  const W = 300, H = 64, pad = 6;
  const max = Math.max(1, ...values);
  const pts = values.map((v, i) => [
    pad + (i / Math.max(1, values.length - 1)) * (W - pad * 2),
    H - pad - (v / max) * (H - pad * 2),
  ]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
  const area = `${line}L${pts.at(-1)[0]},${H}L${pts[0][0]},${H}Z`;
  const defs = h('defs', h('linearGradient#sparkFill', { x1: 0, y1: 0, x2: 0, y2: 1 },
    h('stop', { offset: 0, 'stop-color': '#5eead4', 'stop-opacity': .35 }),
    h('stop', { offset: 1, 'stop-color': '#5eead4', 'stop-opacity': 0 })));
  const pathLine = h('path.spark-line', { d: line });
  const [lx, ly] = pts.at(-1);
  svg.replaceChildren(defs, h('path.spark-area', { d: area }), pathLine, h('circle.spark-dot', { cx: lx, cy: ly, r: 4 }));
  svg.setAttribute('aria-label', `최근 14일 방문자: 오늘 ${values.at(-1)}명, 가장 많은 날 ${Math.max(...values)}명`);
  // 선이 왼쪽에서부터 그려진다
  const len = pathLine.getTotalLength?.() || 600;
  pathLine.style.strokeDasharray = len;
  pathLine.style.strokeDashoffset = len;
  pathLine.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
    { duration: 1800, delay: 1300, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'forwards' });
}

function marquee(roles) {
  const track = $('#marquee');
  // 두 번 이어 붙여야 끊김 없이 돈다
  const words = [];
  while (words.length < 10) words.push(...roles);
  const make = () => words.map((w) => h('span', w));
  track.replaceChildren(...make(), ...make());
}

function clock() {
  const el = $('#clock');
  const tick = () => { el.textContent = `KST ${kstClock()}`; };
  tick();
  setInterval(tick, 1000);
}
