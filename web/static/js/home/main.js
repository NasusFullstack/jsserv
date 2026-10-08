// home/main — 첫 화면 조립. 순서: 배경 레이어 켜기 → 자료 받기(부팅 화면과 동시에) → 각 칸 그리기 → 나타나기.
//
//   core/   통신·DOM·형식·색·움직임·그래프 (화면을 모름)
//   fx/     효과 하나당 파일 하나 (자료를 모름)
//   home/   칸 하나당 파일 하나 (자료를 받아 core·fx 로 그림)

import { $, $$, toast } from '../core/dom.js';
import { overview } from '../core/api.js';
import { startParallax } from '../fx/parallax.js';
import { startField } from '../fx/field.js';
import { wireInteractions } from '../fx/interact.js';
import { revealAll } from '../fx/reveal.js';
import { runBoot } from '../fx/boot.js';
import { renderHero } from './hero.js';
import { findWork, renderWorks } from './works.js';
import { openDetail, wireDetail } from './detail.js';
import { renderLab } from './lab.js';
import { renderVisits } from './visits.js';
import { renderContact } from './contact.js';

const EMPTY = {
  site: { name: document.querySelector('[data-site-name]')?.textContent || '', roles: [] },
  server: { name: 'jsserv', version: '?', uptime: 0 },
  services: [],
  stats: { today: { visitors: 0, views: 0 }, total: { visitors: 0 }, days: Array.from({ length: 14 }, (_, i) => ({ day: `----${i}`, visitors: 0 })) },
  works: [],
};

async function main() {
  startParallax();
  startField($('#field'));

  const load = overview();
  await runBoot(load);
  let data;
  try {
    data = await load;
  } catch (e) {
    data = EMPTY;
    toast('서버에서 자료를 못 받았습니다. 잠시 뒤 새로고침 해 주세요', true);
  }

  document.body.classList.add('is-ready');
  renderHero(data);
  renderWorks(data.works, openDetail);
  wireDetail(findWork);
  renderLab(data);
  renderVisits(data);
  renderContact(data.site);
  wireInteractions();
  revealAll();
  watchSections();
}

/** 지금 보고 있는 구역을 머리 메뉴에 표시 */
function watchSections() {
  const links = new Map($$('.topnav a').map((a) => [a.getAttribute('href').slice(1), a]));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      links.forEach((a) => a.classList.remove('is-here'));
      links.get(e.target.id)?.classList.add('is-here');
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  links.forEach((_, id) => { const s = document.getElementById(id); if (s) io.observe(s); });
}

main();
