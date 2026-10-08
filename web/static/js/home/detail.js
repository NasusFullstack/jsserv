// home/detail — 작품 자세히 (겹치는 레이어). 카드의 그림이 그대로 커지며 열린다(FLIP).
// 주소가 /w/<작품> 으로 바뀌어서 링크를 보낼 수 있고, 뒤로 가기·Esc·바깥 누르기로 닫힌다.

import { $, h, icon, toast } from '../core/dom.js';
import { bytes, date, num } from '../core/format.js';
import { reduced } from '../core/motion.js';
import { mediaFor } from './works.js';

const root = () => $('#detail');
let fromCard = null;
let lastFocus = null;

export function openDetail(w, card = null, push = true) {
  const d = root();
  fromCard = card;
  lastFocus = document.activeElement;
  const sheet = d.querySelector('.detail__sheet');
  sheet.style.setProperty('--accent', w.accent || '#5eead4');
  const media = $('#detailMedia');
  media.replaceChildren(mediaFor(w));
  $('#detailBody').replaceChildren(...body(w));
  [...$('#detailBody').children].forEach((c, i) => c.style.setProperty('--i', i));

  d.hidden = false;
  document.body.style.overflow = 'hidden';
  sheet.scrollTop = 0;
  requestAnimationFrame(() => {
    d.classList.add('is-open');
    flip(card?.querySelector('.card__media'), media, false);
  });
  d.querySelector('.detail__close').focus({ preventScroll: true });
  if (push) history.pushState({ work: w.slug }, '', `/w/${w.slug}`);
  document.title = `${w.title} · ${document.querySelector('[data-site-name]')?.textContent || ''}`;
}

export function closeDetail(pop = false) {
  const d = root();
  if (d.hidden) return;
  const media = $('#detailMedia');
  d.classList.remove('is-open');
  const done = () => {
    d.hidden = true;
    document.body.style.overflow = '';
    lastFocus?.focus?.({ preventScroll: true });
  };
  const anim = flip(fromCard?.querySelector('.card__media'), media, true);
  if (anim) anim.finished.then(done, done); else setTimeout(done, 300);
  d.querySelector('.detail__sheet').animate([{ opacity: 1 }, { opacity: 0 }], { duration: 380, easing: 'ease-in', fill: 'forwards' })
    .finished.then(() => d.querySelector('.detail__sheet').getAnimations().forEach((a) => a.cancel()), () => {});
  if (!pop && location.pathname.startsWith('/w/')) history.pushState({}, '', '/');
  document.title = document.querySelector('[data-site-name]')?.textContent || document.title;
}

/** 카드 그림 자리 ↔ 자세히 그림 자리를 잇는 움직임 */
function flip(fromEl, toEl, reverse) {
  if (reduced() || !fromEl) {
    if (!reverse) toEl.closest('.detail__sheet').animate([{ opacity: 0, transform: 'translateY(30px) scale(.98)' }, { opacity: 1, transform: 'none' }], { duration: 450, easing: 'cubic-bezier(.16,1,.3,1)' });
    return null;
  }
  const a = fromEl.getBoundingClientRect();
  const b = toEl.getBoundingClientRect();
  const t = `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${a.width / b.width}, ${a.height / b.height})`;
  const frames = [{ transform: t, borderRadius: '22px' }, { transform: 'none', borderRadius: '0px' }];
  return toEl.animate(reverse ? frames.reverse() : frames, {
    duration: reverse ? 420 : 650,
    easing: reverse ? 'cubic-bezier(.65,0,.35,1)' : 'cubic-bezier(.16,1,.3,1)',
    fill: 'both',
  });
}

function body(w) {
  const meta = h('div.detail__meta',
    w.kind ? h('span.pill', h('i'), w.kind) : null,
    w.status ? h('span.pill', w.status) : null,
    w.version ? h('span.pill.mono', w.version) : null);
  const actions = h('div.detail__actions',
    w.play ? h('a.btn.btn--accent', { href: w.play, target: '_blank', rel: 'noopener' }, icon('play'), h('span', '플레이')) : null,
    w.download ? h('a.btn.btn--ghost', { href: w.download.url, download: '' }, icon('download'),
      h('span', `다운로드 · ${bytes(w.download.bytes)}`)) : null,
    ...(w.release?.assets || []).map((a) => h('a.btn.btn--ghost', { href: a.url, title: `GitHub 릴리스 ${w.release.tag}` },
      icon('download'), h('span', `${a.name} · ${bytes(a.bytes)}`))),
    w.source ? h('a.btn.btn--ghost', { href: w.source, target: '_blank', rel: 'noopener' }, icon('code'), h('span', '소스 코드')) : null,
    h('button.btn.btn--ghost.btn--sm', { onclick: () => share(w) }, icon('link'), h('span', '링크 복사')));
  actions.querySelectorAll('svg').forEach((s) => { s.style.cssText = 'width:18px;height:18px'; });

  const facts = h('dl.detail__facts',
    fact('종류', w.kind),
    fact('상태', w.status),
    fact('버전', w.version),
    fact('만든 해', w.year),
    w.play ? fact('플레이한 사람', num(w.plays)) : null,
    w.download || w.release ? fact('받은 사람', num(w.downloads)) : null,
    w.download ? fact('파일', w.download.name) : null,
    w.release ? releaseFact(w.release) : null,
    fact('고친 날', date(w.updated)));
  const out = [
    meta,
    h('h2.detail__title#detailTitle', w.title),
    w.tagline ? h('p.detail__tagline', w.tagline) : null,
    actions,
    h('div.detail__grid', h('p.detail__desc', w.desc || '설명이 아직 없습니다.'), facts),
  ];
  if (w.tags?.length) out.splice(4, 0, h('ul.tags', { style: { 'margin-top': '18px' } }, w.tags.map((t) => h('li.tag', t))));
  if (w.shots?.length) {
    out.push(h('div.detail__shots', h('h3', '스크린샷'),
      w.shots.map((src) => h('button', { onclick: () => lightbox(src), 'aria-label': '크게 보기' },
        h('img', { src, alt: '', loading: 'lazy' })))));
  }
  return out.filter(Boolean);
}

function releaseFact(r) {
  return h('div', h('dt', '최신 릴리스'),
    h('dd', h('a', { href: r.url, target: '_blank', rel: 'noopener', style: { color: 'var(--accent)' } }, `${r.tag} ↗`),
      r.published ? h('span', { style: { display: 'block', 'font-weight': 400, color: 'var(--ink-3)', 'font-size': '12px' } }, date(r.published)) : null));
}

function fact(k, v) {
  if (!v) return null;
  return h('div', h('dt', k), h('dd', v));
}

async function share(w) {
  const url = `${location.origin}/w/${w.slug}`;
  try {
    await navigator.clipboard.writeText(url);
    toast('링크를 복사했습니다');
  } catch {
    toast(url);
  }
}

function lightbox(src) {
  const lb = $('#lightbox');
  lb.querySelector('img').src = src;
  lb.hidden = false;
  lb.onclick = () => { lb.hidden = true; };
}

export function wireDetail(find) {
  const d = root();
  d.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeDetail(); });
  addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('#lightbox').hidden) { $('#lightbox').hidden = true; return; }
    closeDetail();
  });
  addEventListener('popstate', () => {
    const m = location.pathname.match(/^\/w\/([a-z0-9-]+)/);
    const w = m && find(m[1]);
    if (w) openDetail(w, null, false); else closeDetail(true);
  });
  // /w/<작품> 으로 바로 들어왔으면 열어 둔다
  const m = location.pathname.match(/^\/w\/([a-z0-9-]+)/);
  const w = m && find(m[1]);
  if (w) setTimeout(() => openDetail(w, null, false), 600);
}
