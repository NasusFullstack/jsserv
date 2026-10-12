// admin/settings — 사이트 설정: 이름·한 줄 소개·소개 글·흐르는 띠 글자·연락처,
// 간판 그림(링크 미리보기에 뜨는 그림), 검색엔진 소유 확인 코드(구글·네이버).

import { h, icon, toast } from '../core/dom.js';
import { call, upload } from './session.js';

export function renderSettings(view, data, onSaved) {
  const s = data.site;
  const field = (label, name, value, { hint, area, wide, type = 'text', max, placeholder } = {}) => {
    const input = area
      ? h('textarea', { name, maxlength: max, placeholder }, value || '')
      : h('input', { name, type, value: value || '', maxlength: max, placeholder });
    return h(`label.field${wide ? '.wide' : ''}`, h('span.field__label', label), input, hint ? h('span.field__hint', hint) : null);
  };
  const form = h('form.panel.glass.form-grid',
    field('사이트 이름 (간판)', 'name', s.name, { hint: '첫 화면·브라우저 탭·검색 결과·링크 미리보기에 나오는 이름입니다.', max: 40 }),
    field('흐르는 띠 글자', 'roles', (s.roles || []).join(', '), { hint: '쉼표로 나눔. 예: GAME, APP, SERVER', max: 200 }),
    field('한 줄 소개', 'headline', s.headline, { wide: true, hint: '이름 아래 한 줄. 검색 결과·링크 미리보기 설명으로도 쓰입니다.', max: 100 }),
    field('소개 글', 'about', s.about, { wide: true, area: true, hint: '맨 아래 연락 칸에 나옵니다.', max: 800 }),
    field('메일', 'email', s.email, { type: 'email', max: 120 }),
    field('GitHub 주소', 'github', s.github, { type: 'url', max: 300 }),
    field('구글 확인 코드', 'google_verify', s.google_verify, {
      max: 120, placeholder: 'google-site-verification 의 content 값',
      hint: '구글 서치 콘솔 → 속성 추가 → URL 접두어 → 「HTML 태그」에 나오는 코드. 태그를 통째로 붙여 넣어도 됩니다.',
    }),
    field('네이버 확인 코드', 'naver_verify', s.naver_verify, {
      max: 120, placeholder: 'naver-site-verification 의 content 값',
      hint: '네이버 서치어드바이저 → 사이트 등록 → 「HTML 태그」 방식의 코드.',
    }),
    h('div.wide', { style: { display: 'flex', 'justify-content': 'flex-end' } },
      h('button.btn.btn--primary', { type: 'submit' }, '저장')));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = Object.fromEntries(['name', 'headline', 'about', 'email', 'github', 'google_verify', 'naver_verify'].map((k) => [k, f.get(k)]));
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
    h('header.view__head', h('div', h('h1.view__title', '사이트 설정'), h('p.view__sub', '사이트 전체에 나오는 글과 간판. 작품은 「작품」에서 고칩니다.'))),
    brandBox(s, onSaved),
    form);
}

/** 간판 그림: 카톡·페북 등에 사이트 링크를 보낼 때 뜨는 그림 (1200×630 으로 맞춰 보관) */
function brandBox(s, onSaved) {
  const img = h('img', { src: `/og/site.jpg?t=${Date.now()}`, alt: '지금 간판 그림' });
  const input = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif' });
  const text = h('span', '새 간판 그림을 고르거나 끌어다 놓기');
  const drop = h('label.drop', icon('upload'), text, input, h('i.drop__bar'));
  const send = async (file) => {
    if (!file) return;
    drop.classList.add('is-busy');
    text.textContent = '올리는 중…';
    try {
      await upload('/api/admin/site/og', file, (p) => drop.style.setProperty('--p', p));
      toast('간판 그림을 바꿨습니다. 카톡은 예전 미리보기를 한동안 기억할 수 있습니다');
      onSaved();
    } catch (err) {
      toast(err.message, true);
    } finally {
      drop.classList.remove('is-busy');
      drop.style.setProperty('--p', 0);
      text.textContent = '새 간판 그림을 고르거나 끌어다 놓기';
      input.value = '';
    }
  };
  input.addEventListener('change', () => send(input.files[0]));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('is-over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('is-over'); send(e.dataTransfer.files[0]); });
  const reset = s.og_image ? h('button.btn.btn--danger.btn--sm', {
    type: 'button',
    onclick: async () => {
      if (!confirm('기본 간판 그림으로 되돌릴까요?')) return;
      try { await call('DELETE', '/api/admin/site/og'); toast('기본 간판 그림으로 되돌렸습니다'); onSaved(); } catch (err) { toast(err.message, true); }
    },
  }, icon('trash'), h('span', '기본 그림으로')) : null;
  return h('section.panel.glass.brand-box',
    h('h2.panel__title', '간판 그림', h('span.mono', '1200 × 630 · 링크 미리보기')),
    h('div.brand-box__row',
      h('div.preview.brand-box__img', img),
      h('div.brand-box__side',
        h('p.field__hint', '사이트 주소를 카톡·페이스북·디스코드 등에 보낼 때 뜨는 그림입니다. 올린 그림은 가운데를 기준으로 1200×630 에 맞춰 잘립니다.'),
        h('p.field__hint', '작품 주소(/w/작품)를 보내면 그 작품의 대표 그림이 대신 뜹니다.'),
        drop,
        reset)));
}
