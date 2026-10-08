// home/contact — 연락 칸: 소개 글과 메일·GitHub 버튼. 메일 버튼은 주소를 복사도 해 준다.

import { $, h, icon, toast } from '../core/dom.js';
import { magnetic } from '../fx/interact.js';

export function renderContact(site) {
  $('#about').textContent = site.about || '';
  $('#year').textContent = new Date().getFullYear();
  const links = [];
  if (site.email) {
    links.push(h('a.btn.btn--primary', {
      href: `mailto:${site.email}`,
      onclick: () => { navigator.clipboard?.writeText(site.email).then(() => toast(`${site.email} 복사했습니다`), () => {}); },
    }, icon('mail'), h('span', site.email)));
  }
  if (site.github) {
    links.push(h('a.btn.btn--ghost', { href: site.github, target: '_blank', rel: 'noopener' },
      icon('github'), h('span', site.github.replace(/^https?:\/\/(www\.)?/, ''))));
  }
  const box = $('#contactLinks');
  box.replaceChildren(...links);
  box.querySelectorAll('.btn').forEach((b) => magnetic(b, .2));
}
