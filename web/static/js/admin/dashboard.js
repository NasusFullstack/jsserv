// admin/dashboard — 대시보드: 오늘 숫자, 30일 흐름(방문자·플레이·다운로드를 따로따로), 들어온 곳, 작품별, 서버 상태.
// 세 가지는 크기가 달라서 한 그래프에 겹치지 않고 작은 그래프 셋으로 나눈다(같은 축에 섞으면 작은 쪽이 안 보임).

import { h } from '../core/dom.js';
import { barChart } from '../core/barchart.js';
import { bytes, num, uptime, ago } from '../core/format.js';

const SERIES = [
  ['visitors', '방문자', '명', 'var(--s-visitors)'],
  ['plays', '플레이', '명', 'var(--s-plays)'],
  ['downloads', '다운로드', '명', 'var(--s-downloads)'],
];

export function renderDashboard(view, data, reload) {
  const { stats, server, works, services } = data;
  const days = stats.days;
  const yesterday = days.at(-2) || {};

  const kpi = (label, key, color) => {
    const today = stats.today[key];
    const diff = today - (yesterday[key] || 0);
    return h('div.tile.glass', { style: { '--c': color } },
      h('span.tile__label', h('i'), `오늘 ${label}`),
      h('span.tile__value', num(today),
        key !== 'views' && diff ? h(`span.delta.${diff > 0 ? 'up' : 'down'}`, `${diff > 0 ? '▲' : '▼'} ${num(Math.abs(diff))}`) : null),
      h('span.tile__sub', `누적 ${num(stats.total[key])} · 어제 ${num(yesterday[key] || 0)}`));
  };

  const charts = SERIES.map(([key, label, unit, color]) => {
    const plot = h('div.mini-chart');
    const box = h('figure.panel.glass', h('figcaption.panel__title', `최근 30일 ${label}`, h('span.mono', `합 ${num(days.reduce((s, d) => s + d[key], 0))}`)), plot);
    requestAnimationFrame(() => barChart(plot, { data: days.map((d) => ({ day: d.day, value: d[key] })), color, unit, label: `최근 30일 ${label}` }));
    return box;
  });

  const maxRef = Math.max(1, ...stats.refs.map((r) => r.n));
  const refs = h('section.panel.glass',
    h('h2.panel__title', '들어온 곳', h('span.mono', '최근 30일')),
    stats.refs.length
      ? h('ul.refs', stats.refs.map((r, i) => h('li', { style: { '--w': `${(r.n / maxRef) * 100}%`, '--i': i } }, h('span', r.host), h('b', num(r.n)))))
      : h('p.empty-note', '다른 사이트에서 타고 온 방문이 아직 없습니다. (주소를 직접 쳤거나 즐겨찾기로 온 방문은 여기 안 나옵니다)'));

  const perWork = h('section.panel.glass',
    h('h2.panel__title', '작품별', h('span.mono', '누적 · 하루 한 번씩 센 사람 수')),
    h('table.table',
      h('thead', h('tr', h('th', '작품'), h('th.num', '플레이'), h('th.num', '다운로드'), h('th.num', '댓글'))),
      h('tbody', works.map((w) => h('tr',
        h('td', h('span.dot', { style: { '--c': w.accent || 'var(--mint)' } }), w.title, w.hidden ? h('span.badge.is-hidden', { style: { 'margin-left': '8px' } }, '숨김') : null),
        h('td.num', w.play ? num(w.plays) : '-'),
        h('td.num', w.download || w.release ? num(w.downloads) : '-'),
        h('td.num', num(w.comments || 0)))))));

  const disk = server.disk;
  const usedPct = disk ? (disk.used / disk.total) * 100 : 0;
  const ipNote = server.ip_source === 'peer'
    ? h('div.note.is-warn', h('span', '⚠'), h('span', h('b', '손님 주소를 nginx 가 안 넘겨줍니다. '), '모든 방문이 같은 주소로 보여 방문자가 적게 셀 수 있습니다. nginx 설정에 ', h('code', 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;'), ' 한 줄이 필요합니다.'))
    : server.ip_source
      ? h('div.note.is-good', h('span', '✓'), h('span', `손님 주소를 ${server.ip_source} 헤더로 확인하고 있습니다. 방문자 수가 제대로 셉니다.`))
      : h('div.note', h('span', '·'), h('span', '아직 방문 기록이 없어 손님 주소 확인 방식을 모릅니다.'));
  const serverBox = h('section.panel.glass',
    h('h2.panel__title', '서버', h('span.mono', `${server.name} v${server.version}`)),
    h('dl.kv',
      h('dt', '가동 시간'), h('dd', uptime(server.uptime)),
      h('dt', 'Python'), h('dd', server.python),
      h('dt', '데이터 자리'), h('dd.mono', server.data_dir),
      ...Object.entries(server.sizes).flatMap(([k, v]) => [h('dt', k), h('dd', bytes(v))])),
    disk ? h('div', { style: { 'margin-top': '16px' } },
      h('div.panel__title', { style: { margin: 0, 'font-size': '13px' } }, '디스크', h('span.mono', `${bytes(disk.used)} / ${bytes(disk.total)} · 남은 ${bytes(disk.free)}`)),
      h('div.meter', h('i', { style: { '--w': `${usedPct.toFixed(1)}%` } }))) : null,
    h('div', { style: { 'margin-top': '16px' } }, ipNote));

  const featureBox = h('section.panel.glass',
    h('h2.panel__title', '올라와 있는 기능', h('span.mono', `${services.length}개`)),
    h('table.table', h('tbody', services.map((s) => h('tr',
      h('td', h('span.dot', { style: { '--c': 'var(--good)' } }), h('b.mono', s.name)),
      h('td', s.about),
      h('td.num.mono', `v${s.version}`))))));

  view.replaceChildren(
    h('header.view__head',
      h('div', h('h1.view__title', '대시보드'), h('p.view__sub', `${ago(server.time)} 기준 · 하루의 경계는 한국 시간 0시`)),
      h('div.view__tools', h('button.btn.btn--ghost.btn--sm', { onclick: reload }, '새로고침'))),
    h('div.kpis', kpi('방문자', 'visitors', 'var(--s-visitors)'), kpi('페이지뷰', 'views', 'var(--ink-3)'),
      kpi('플레이', 'plays', 'var(--s-plays)'), kpi('다운로드', 'downloads', 'var(--s-downloads)')),
    h('div.grid-3', charts),
    h('div.grid-2', { style: { 'margin-top': '18px' } }, refs, perWork),
    h('div.grid-2', { style: { 'margin-top': '18px' } }, serverBox, featureBox));
}
