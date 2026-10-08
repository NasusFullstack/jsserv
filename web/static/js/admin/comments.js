// admin/comments — 모든 작품의 최근 댓글. 작성자로 답글 달기, 아무 글이나 지우기.
// 같은 사람인지는 글쓴이 지문(IP 를 거꾸로 알 수 없는 12자리)으로 본다.

import { h, toast } from '../core/dom.js';
import { ago } from '../core/format.js';
import { call } from './session.js';

let filter = '';

export function renderComments(view, data) {
  view.replaceChildren(
    h('header.view__head', h('div', h('h1.view__title', '댓글'), h('p.view__sub', '최근 200개 · 작성자로 답글을 달면 사이트에 「작성자」 표시가 붙습니다'))),
    h('p.empty-note', '불러오는 중…'));
  call('GET', '/api/admin/comments').then((res) => draw(view, data, res)).catch((err) => toast(err.message, true));
}

function draw(view, data, res) {
  const works = data.works;
  const select = h('select.cinput.admin-select', { onchange: (e) => { filter = e.target.value; draw(view, data, res); } },
    h('option', { value: '' }, `모든 작품 (${res.comments.length})`),
    works.map((w) => h('option', { value: w.slug, selected: filter === w.slug }, `${w.title} (${res.counts[w.slug] || 0})`)));
  const list = res.comments.filter((c) => !filter || c.slug === filter);

  const row = (c) => {
    const slot = h('div');
    const reply = () => {
      if (slot.firstChild) { slot.replaceChildren(); return; }
      const body = h('textarea.cinput', { rows: 2, maxlength: 1000, placeholder: `${c.nick} 에게 작성자로 답글` });
      const f = h('form.admin-reply', body, h('button.btn.btn--primary.btn--sm', { type: 'submit' }, '작성자로 답글'));
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
          await call('POST', `/api/admin/works/${c.slug}/comments`, { body: body.value, parent: c.id });
          toast('답글을 달았습니다');
          renderComments(view, data);
        } catch (err) { toast(err.message, true); }
      });
      slot.replaceChildren(f);
      body.focus();
    };
    const remove = async () => {
      if (!confirm(`「${c.nick}」의 글을 지울까요?\n\n${c.body.slice(0, 120)}`)) return;
      try { await call('DELETE', `/api/admin/comments/${c.id}`); toast('지웠습니다'); renderComments(view, data); } catch (err) { toast(err.message, true); }
    };
    return h('li.admin-c',
      h('div.admin-c__head',
        h('a.admin-c__work', { href: `/w/${c.slug}`, target: '_blank', rel: 'noopener' }, c.work),
        h('b', c.nick), c.owner ? h('span.badge', '작성자') : null, c.is_reply ? h('span.badge', '답글') : null,
        h('span.mono.admin-c__who', { title: '글쓴이 지문 (같은 값이면 같은 사람)' }, c.who || ''),
        h('time', { title: c.created }, ago(c.created))),
      h('p.admin-c__body', c.mention ? h('b', `@${c.mention} `) : null, c.body),
      h('div.admin-c__tools',
        h('button.btn.btn--ghost.btn--sm', { onclick: reply }, '답글'),
        h('button.btn.btn--danger.btn--sm', { onclick: remove }, '지우기')),
      slot);
  };

  view.replaceChildren(
    h('header.view__head',
      h('div', h('h1.view__title', '댓글'), h('p.view__sub', '최근 200개 · 작성자로 답글을 달면 사이트에 「작성자」 표시가 붙습니다')),
      h('div.view__tools', select)),
    list.length ? h('ul.admin-cs.panel.glass', list.map(row)) : h('p.empty-note', '아직 댓글이 없습니다.'));
}
