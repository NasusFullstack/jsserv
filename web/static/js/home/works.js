// home/works — 작품 칸: 종류별 칩(필터)과 카드 목록. 카드를 누르면 home/detail 이 연다.

import { $, h, icon } from '../core/dom.js';
import { num } from '../core/format.js';
import { paintCover } from '../fx/cover.js';
import { tilt } from '../fx/interact.js';
import { reveal } from '../fx/reveal.js';

let all = [];
let openDetail = () => {};

export function renderWorks(works, onOpen) {
  all = works;
  openDetail = onOpen;
  chips();
  grid('전체');
}

function chips() {
  const box = $('#chips');
  const kinds = ['전체', ...new Set(all.map((w) => w.kind).filter(Boolean))];
  if (kinds.length <= 2) { box.replaceChildren(); return; }   // 종류가 하나뿐이면 칩이 필요 없다
  box.replaceChildren(...kinds.map((k, i) => h('button.chip', {
    role: 'tab',
    'aria-selected': i === 0 ? 'true' : 'false',
    onclick: (e) => {
      box.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-selected', 'false'));
      e.currentTarget.setAttribute('aria-selected', 'true');
      grid(k);
    },
  }, k, h('span.mono', String(k === '전체' ? all.length : all.filter((w) => w.kind === k).length)))));
}

function grid(kind) {
  const box = $('#worksGrid');
  const list = kind === '전체' ? all : all.filter((w) => w.kind === kind);
  if (!list.length) {
    box.replaceChildren(h('p.works__empty', '아직 올린 작품이 없습니다.'));
    return;
  }
  const cards = list.map((w, i) => card(w, i === 0 && list.length !== 2));
  box.dataset.count = Math.min(list.length, 3);
  box.replaceChildren(...cards);
  cards.forEach((c, i) => {
    c.style.setProperty('--i', i % 3);
    reveal(c);
    tilt(c, 6);
  });
}

/** 작품 그림. 움직이는 그림이면 기본은 첫 장(가벼움), animate 면 움직이는 것 */
export function mediaFor(w, cls = '', animate = false) {
  if (w.cover) {
    const still = w.cover_still && !animate;
    return h(`img${cls}`, { src: still ? w.cover_still : w.cover, alt: '', loading: 'lazy', decoding: 'async', data: still ? { anim: w.cover, still: w.cover_still } : null });
  }
  const cv = h(`canvas${cls}`, { 'aria-hidden': 'true' });
  // 크기가 정해진 뒤에 그린다
  requestAnimationFrame(() => paintCover(cv, { seed: w.slug, accent: w.accent, title: w.title }));
  return cv;
}

function card(w, featured) {
  const el = h(`article.card.reveal${featured ? '.is-featured' : ''}`, {
    tabindex: 0,
    role: 'button',
    'aria-label': `${w.title} 자세히 보기`,
    style: w.accent ? { '--accent': w.accent } : null,
    onclick: () => openDetail(w, el),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(w, el); } },
  },
  h('div.card__media',
    mediaFor(w),
    h('div.card__badges',
      w.kind ? h('span.pill', h('i'), w.kind) : h('span'),
      w.status ? h('span.pill', w.status) : null),
    w.play ? h('span.card__play', { 'aria-hidden': 'true' }, icon('play')) : null),
  h('div.card__body',
    h('div.card__meta.mono', w.year ? h('b', w.year) : null, w.version ? h('span', w.version) : null),
    h('h3.card__title', w.title),
    w.tagline ? h('p.card__tagline', w.tagline) : null,
    w.tags?.length ? h('ul.tags', w.tags.slice(0, 5).map((t) => h('li.tag', t))) : null,
    h('div.card__foot',
      h('span.card__nums.mono',
        w.play ? h('span', { title: '플레이한 사람' }, `▶ ${num(w.plays)}`) : null,
        w.download || w.release ? h('span', { title: '받은 사람' }, `↓ ${num(w.downloads)}`) : null),
      h('span.card__go', '자세히', icon('arrow')))));
  el.querySelector('.card__go svg').style.cssText = 'width:14px;height:14px';
  // 움직이는 대표 그림은 마우스를 올렸을 때만 움직인다 (목록 전체가 한꺼번에 움직이면 무겁다)
  const img = el.querySelector('img[data-anim]');
  if (img) {
    el.addEventListener('pointerenter', () => { img.src = img.dataset.anim; });
    el.addEventListener('pointerleave', () => { img.src = img.dataset.still; });
  }
  return el;
}

export function findWork(slug) {
  return all.find((w) => w.slug === slug);
}
