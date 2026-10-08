// admin/settings — 사이트 설정: 이름·한 줄 소개·소개 글·흐르는 띠 글자·연락처.

import { h, toast } from '../core/dom.js';
import { call } from './session.js';

export function renderSettings(view, data, onSaved) {
  const s = data.site;
  const field = (label, name, value, { hint, area, wide, type = 'text', max } = {}) => {
    const input = area
      ? h('textarea', { name, maxlength: max }, value || '')
      : h('input', { name, type, value: value || '', maxlength: max });
    return h(`label.field${wide ? '.wide' : ''}`, h('span.field__label', label), input, hint ? h('span.field__hint', hint) : null);
  };
  const form = h('form.panel.glass.form-grid',
    field('사이트 이름', 'name', s.name, { hint: '첫 화면에 크게 나오는 이름. 길이에 맞춰 글자 크기가 바뀝니다.', max: 40 }),
    field('흐르는 띠 글자', 'roles', (s.roles || []).join(', '), { hint: '쉼표로 나눔. 예: GAME, APP, SERVER', max: 200 }),
    field('한 줄 소개', 'headline', s.headline, { wide: true, hint: '이름 아래 한 줄. 링크를 보낼 때 미리보기 설명으로도 쓰입니다.', max: 100 }),
    field('소개 글', 'about', s.about, { wide: true, area: true, hint: '맨 아래 연락 칸에 나옵니다.', max: 800 }),
    field('메일', 'email', s.email, { type: 'email', max: 120 }),
    field('GitHub 주소', 'github', s.github, { type: 'url', max: 300 }),
    h('div.wide', { style: { display: 'flex', 'justify-content': 'flex-end' } },
      h('button.btn.btn--primary', { type: 'submit' }, '저장')));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = Object.fromEntries(['name', 'headline', 'about', 'email', 'github'].map((k) => [k, f.get(k)]));
    body.roles = String(f.get('roles') || '').split(',').map((x) => x.trim()).filter(Boolean);
    try {
      await call('PUT', '/api/admin/settings', body);
      toast('저장했습니다. 사이트에 바로 반영됩니다');
      onSaved();
    } catch (err) {
      toast(err.message, true);
    }
  });

  view.replaceChildren(
    h('header.view__head', h('div', h('h1.view__title', '사이트 설정'), h('p.view__sub', '사이트 전체에 나오는 글. 작품은 「작품」에서 고칩니다.'))),
    form);
}
