// home/visits — 방문 칸: 숫자판 4개와 최근 14일 방문자 막대그래프.

import { $, h } from '../core/dom.js';
import { barChart } from '../core/barchart.js';
import { countUp } from '../fx/text.js';
import { reveal } from '../fx/reveal.js';
import { spotlight } from '../fx/interact.js';

export function renderVisits(data) {
  const { today, total, days } = data.stats;
  const plays = data.works.reduce((s, w) => s + (w.plays || 0), 0);
  const downloads = data.works.reduce((s, w) => s + (w.downloads || 0), 0);
  const tiles = [
    ['오늘 방문자', today.visitors, `페이지 ${today.views}번 열림`, 'var(--s-visitors)'],
    ['누적 방문자', total.visitors, '하루 한 번씩 센 합', 'var(--s-visitors)'],
    ['누적 플레이', plays, '작품을 연 사람 (하루 한 번)', 'var(--s-plays)'],
    ['누적 다운로드', downloads, '파일을 받은 사람 (하루 한 번)', 'var(--s-downloads)'],
  ];
  const box = $('#tiles');
  box.replaceChildren(...tiles.map(([label, value, sub, c], i) => {
    const v = h('span.tile__value', '0');
    const el = h('div.tile.glass.reveal', { style: { '--c': c, '--i': i } },
      h('span.tile__label', h('i'), label), v, h('span.tile__sub', sub));
    reveal(el, () => countUp(v, value));
    spotlight(el);
    return el;
  }));

  const plot = $('#visitChart');
  reveal(plot.closest('.chart'), () => barChart(plot, {
    data: days.map((d) => ({ day: d.day, value: d.visitors })),
    color: 'var(--s-visitors)',
    unit: '명',
    label: '최근 14일 방문자',
  }));
}
