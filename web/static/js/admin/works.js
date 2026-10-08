// admin/works — 작품 관리: 왼쪽 목록, 오른쪽 편집(정보 → 저장), 그 아래 파일(대표 그림·스크린샷·다운로드·웹 빌드).
// 파일은 고르거나 끌어다 놓으면 바로 올라간다(진행 막대). 정보는 「저장」을 눌러야 반영된다.

import { h, icon, toast } from '../core/dom.js';
import { bytes, date, num } from '../core/format.js';
import { paintCover } from '../fx/cover.js';
import { call, upload } from './session.js';

let selected = null;      // 작품 주소 이름, 또는 'new'

export function renderWorks(view, data, refresh) {
  const works = data.works;
  if (selected !== 'new' && !works.some((w) => w.slug === selected)) selected = works[0]?.slug || 'new';
  const current = works.find((w) => w.slug === selected) || null;

  const list = h('aside.wlist.glass',
    h('button.btn.btn--primary.btn--sm.wlist__new', { onclick: () => { selected = 'new'; renderWorks(view, data, refresh); } }, icon('plus'), h('span', '새 작품')),
    works.map((w) => h('button.wlist__item', {
      'aria-current': w.slug === selected ? 'true' : 'false',
      onclick: () => { selected = w.slug; renderWorks(view, data, refresh); },
    },
    h('span.wlist__thumb', thumb(w)),
    h('span.wlist__text', h('b', w.title), h('small', [w.kind, w.status].filter(Boolean).join(' · ') || w.slug)),
    w.hidden ? h('span.badge.is-hidden', '숨김') : null)));

  const after = async (slug) => { if (slug) selected = slug; await refresh('works'); };
  view.replaceChildren(
    h('header.view__head', h('div', h('h1.view__title', '작품'),
      h('p.view__sub', `${works.length}개 · 위에서부터 순서대로 사이트에 나옵니다 (순서 숫자가 작을수록 앞)`))),
    h('div.works-admin', list, editor(current, data.limits, after)));
}

function thumb(w) {
  if (w.cover) return h('img', { src: w.cover, alt: '' });
  const c = h('canvas');
  requestAnimationFrame(() => paintCover(c, { seed: w.slug, accent: w.accent, title: w.title }));
  return c;
}

function field(label, name, value, { hint, area, wide, type = 'text', list, max, placeholder } = {}) {
  const attrs = { name, type, maxlength: max, list, placeholder };
  const input = area ? h('textarea', { name, maxlength: max, placeholder }, value ?? '') : h('input', { ...attrs, value: value ?? '' });
  return h(`label.field${wide ? '.wide' : ''}`, h('span.field__label', label), input, hint ? h('span.field__hint', hint) : null);
}

function editor(w, limits, after) {
  const isNew = !w;
  const v = w || { kind: '게임', status: '개발 중', year: String(new Date().getFullYear()), accent: '#5eead4', order: 10, tags: [] };
  const form = h('form.panel.glass.form-grid',
    isNew ? field('주소 이름', 'slug', '', { hint: '영어 소문자·숫자·- (예: my-game). 주소 /w/이름 · /p/이름 에 쓰이고, 나중에 못 바꿉니다.', max: 32, placeholder: 'my-game' }) : null,
    field('제목', 'title', v.title, { max: 60 }),
    field('종류', 'kind', v.kind, { list: 'kinds', max: 12, hint: '같은 종류끼리 첫 화면에서 골라 볼 수 있습니다' }),
    field('상태', 'status', v.status, { list: 'statuses', max: 12 }),
    field('버전', 'version', v.version_own ?? v.version, { max: 30, placeholder: w?.release?.tag ? `비우면 릴리스 이름 (${w.release.tag})` : 'v1.0' }),
    field('한 줄 소개', 'tagline', v.tagline, { wide: true, max: 140 }),
    field('설명', 'desc', v.desc, { wide: true, area: true, max: 3000, hint: '줄바꿈 그대로 나옵니다' }),
    field('태그', 'tags', (v.tags || []).join(', '), { wide: true, hint: '쉼표로 나눔, 10개까지', max: 230 }),
    field('플레이 주소', 'play_url', v.play_url, { hint: '이미 다른 곳에 있는 게임이면 주소를 (예: /game/). 아래에 웹 빌드를 올리면 그쪽이 먼저입니다.', max: 300, placeholder: '/game/ 또는 https://…' }),
    field('소스 코드 주소', 'source', v.source, { max: 300, placeholder: 'https://github.com/…' }),
    field('GitHub 릴리스', 'release', v.release_repo, {
      max: 140,
      placeholder: '주인/저장소 (예: NasusFullstack/chat)',
      hint: !v.release_repo ? '적어 두면 그 저장소의 최신 릴리스 파일이 다운로드 버튼으로 자동으로 나옵니다 (30분마다 확인)'
        : w?.release ? `지금 읽힌 최신: ${w.release.tag} · 파일 ${w.release.assets.length}개` : '아직 못 읽었습니다 (저장소 이름이나 공개 여부를 확인)',
    }),
    field('만든 해', 'year', v.year, { max: 10 }),
    field('순서', 'order', v.order ?? 0, { type: 'number' }),
    field('강조 색', 'accent', v.accent || '#5eead4', { type: 'color', hint: '카드 빛·그림 색' }),
    h('label.field.field--check', h('input', { type: 'checkbox', name: 'hidden', checked: !!v.hidden }), h('span', '숨기기 (사이트에 안 보임 — 만드는 중일 때)')),
    h('datalist#kinds', ['게임', '앱', '도구', '웹', '서버', '실험'].map((k) => h('option', { value: k }))),
    h('datalist#statuses', ['개발 중', '베타', '공개', '운영 중', '중단'].map((k) => h('option', { value: k }))));

  const status = h('span', isNew ? '새 작품' : `마지막 저장 ${date(w.updated)}`);
  const saveBtn = h('button.btn.btn--primary', { type: 'button' }, isNew ? '만들기' : '저장');
  const bar = h('div.save-bar', status, saveBtn);
  form.addEventListener('input', () => { bar.classList.add('is-dirty'); status.textContent = '저장하지 않은 변경이 있습니다'; });
  form.addEventListener('submit', (e) => e.preventDefault());

  saveBtn.addEventListener('click', async () => {
    const f = new FormData(form);
    const slug = isNew ? String(f.get('slug') || '').trim() : w.slug;
    const body = {
      title: f.get('title'), kind: f.get('kind'), status: f.get('status'), version: f.get('version'),
      year: f.get('year'), tagline: f.get('tagline'), desc: f.get('desc'),
      tags: String(f.get('tags') || '').split(',').map((x) => x.trim()).filter(Boolean),
      play_url: f.get('play_url'), source: f.get('source'), release: f.get('release'), accent: f.get('accent'),
      order: Number(f.get('order') || 0), hidden: f.get('hidden') === 'on',
    };
    saveBtn.disabled = true;
    try {
      await call('PUT', `/api/admin/works/${encodeURIComponent(slug)}`, body);
      toast(isNew ? '만들었습니다. 이제 그림과 파일을 올릴 수 있습니다' : '저장했습니다');
      await after(slug);
    } catch (err) {
      toast(err.message, true);
      saveBtn.disabled = false;
    }
  });

  const head = h('div.editor__bar',
    h('h2', isNew ? '새 작품' : w.title),
    !isNew ? h('span.editor__url.mono', '사이트 주소 ', h('a', { href: `/w/${w.slug}`, target: '_blank', rel: 'noopener' }, `/w/${w.slug}`)) : null);

  const parts = [head, form, bar];
  if (!isNew) {
    parts.push(h('div.files', coverBox(w, limits, after), shotsBox(w, limits, after), downloadBox(w, limits, after), buildBox(w, limits, after)));
    parts.push(h('div.danger-zone',
      h('span', '작품을 지우면 그림·다운로드 파일·웹 빌드도 같이 지워지고 되돌릴 수 없습니다.'),
      h('button.btn.btn--danger.btn--sm', {
        onclick: async () => {
          if (!confirm(`「${w.title}」을(를) 지울까요? 되돌릴 수 없습니다.`)) return;
          try { await call('DELETE', `/api/admin/works/${w.slug}`); toast('지웠습니다'); await after(null); } catch (err) { toast(err.message, true); }
        },
      }, icon('trash'), h('span', '작품 지우기'))));
  }
  return h('div.editor', parts);
}

/** 고르거나 끌어다 놓는 올리기 칸 */
function drop(label, accept, onFiles, multiple = false) {
  const input = h('input', { type: 'file', accept, multiple });
  const text = h('span', label);
  const box = h('label.drop', icon('upload'), text, input, h('i.drop__bar'));
  const run = async (files) => {
    if (!files.length) return;
    box.classList.add('is-busy');
    const setP = (p) => box.style.setProperty('--p', p);
    try {
      await onFiles([...files], setP, (msg) => { text.textContent = msg; });
    } catch (err) {
      toast(err.message, true);
    } finally {
      box.classList.remove('is-busy');
      setP(0);
      text.textContent = label;
      input.value = '';
    }
  };
  input.addEventListener('change', () => run(input.files));
  box.addEventListener('dragover', (e) => { e.preventDefault(); box.classList.add('is-over'); });
  box.addEventListener('dragleave', () => box.classList.remove('is-over'));
  box.addEventListener('drop', (e) => { e.preventDefault(); box.classList.remove('is-over'); run(e.dataTransfer.files); });
  return box;
}

const removeBtn = (w, what, label, after) => h('button.btn.btn--danger.btn--sm', {
  onclick: async () => {
    if (!confirm(`${label}을(를) 지울까요?`)) return;
    try { await call('DELETE', `/api/admin/works/${w.slug}/${what}`); toast('지웠습니다'); await after(); } catch (err) { toast(err.message, true); }
  },
}, icon('trash'), h('span', '지우기'));

function coverBox(w, limits, after) {
  return h('section.file-box',
    h('h3', '대표 그림', h('small', `긴 변 1920 WebP 로 줄여 보관 · ${bytes(limits.image)}까지`)),
    h('div.preview', thumb(w)),
    w.cover ? null : h('p.field__hint', '없으면 강조 색으로 그린 그림이 대신 나옵니다.'),
    drop(w.cover ? '다른 그림으로 바꾸기' : '그림을 고르거나 끌어다 놓기', 'image/png,image/jpeg,image/webp,image/gif', async ([file], setP, say) => {
      say('올리는 중…');
      await upload(`/api/admin/works/${w.slug}/cover`, file, setP);
      toast('대표 그림을 바꿨습니다');
      await after();
    }),
    w.cover ? h('div.file-box__row', removeBtn(w, 'cover', '대표 그림', after)) : null);
}

function shotsBox(w, limits, after) {
  const left = limits.shots - w.shots.length;
  return h('section.file-box',
    h('h3', '스크린샷', h('small', `${w.shots.length} / ${limits.shots}장`)),
    w.shots.length ? h('div.shots', w.shots.map((src) => {
      const name = src.split('/').pop();
      return h('div.shot', h('img', { src, alt: '' }), h('button', {
        'aria-label': '이 스크린샷 지우기',
        onclick: async () => {
          if (!confirm('이 스크린샷을 지울까요?')) return;
          try { await call('DELETE', `/api/admin/works/${w.slug}/shots/${name}`); await after(); } catch (err) { toast(err.message, true); }
        },
      }, icon('trash')));
    })) : h('p.field__hint', '작품 자세히 화면 아래에 모아서 보여 줍니다.'),
    left > 0 ? drop(`그림 여러 장 고르기 (${left}장 더)`, 'image/png,image/jpeg,image/webp,image/gif', async (files, setP, say) => {
      const list = files.slice(0, left);
      for (let i = 0; i < list.length; i++) {
        say(`올리는 중 ${i + 1} / ${list.length}`);
        await upload(`/api/admin/works/${w.slug}/shots`, list[i], (p) => setP((i + p) / list.length));
      }
      toast(`스크린샷 ${list.length}장을 올렸습니다`);
      await after();
    }, true) : null);
}

function downloadBox(w, limits, after) {
  const d = w.download;
  return h('section.file-box',
    h('h3', '다운로드 파일', h('small', `zip·exe·apk 등 · ${bytes(limits.download)}까지`)),
    d ? h('div.file-box__now', h('b', d.name), h('span.mono', `${bytes(d.bytes)} · ${date(d.updated)} · 받은 사람 ${num(w.downloads)}`))
      : h('p.field__hint', '올리면 작품에 「다운로드」 버튼이 생깁니다. 새로 올리면 바뀝니다.'),
    drop(d ? '새 파일로 바꾸기' : '파일을 고르거나 끌어다 놓기', '.zip,.7z,.rar,.exe,.msi,.apk,.dmg,.html,.pdf,.jar', async ([file], setP, say) => {
      say(`올리는 중… ${bytes(file.size)}`);
      await upload(`/api/admin/works/${w.slug}/download?name=${encodeURIComponent(file.name)}`, file, setP);
      toast('다운로드 파일을 올렸습니다');
      await after();
    }),
    d ? h('div.file-box__row', h('a.btn.btn--ghost.btn--sm', { href: `/dl/${w.slug}` }, icon('download'), h('span', '받아 보기')), removeBtn(w, 'download', '다운로드 파일', after)) : null);
}

function buildBox(w, limits, after) {
  const b = w.build;
  return h('section.file-box',
    h('h3', '웹 빌드 (브라우저에서 플레이)', h('small', `zip · ${bytes(limits.build)}까지`)),
    b ? h('div.file-box__now', h('b', `파일 ${num(b.files)}개`), h('span.mono', `${bytes(b.bytes)} · ${date(b.updated)}`))
      : h('p.field__hint', 'index.html 이 들어 있는 zip 을 올리면 /p/' + w.slug + '/ 에서 바로 플레이됩니다. (Godot·Unity 웹 내보내기, HTML5 게임 등)'),
    drop(b ? '새 빌드로 바꾸기' : 'zip 을 고르거나 끌어다 놓기', '.zip', async ([file], setP, say) => {
      say(`올리는 중… ${bytes(file.size)}`);
      await upload(`/api/admin/works/${w.slug}/build`, file, (p) => { setP(p); if (p >= 1) say('푸는 중…'); });
      toast('웹 빌드를 올렸습니다');
      await after();
    }),
    b ? h('div.file-box__row', h('a.btn.btn--ghost.btn--sm', { href: `/p/${w.slug}/`, target: '_blank', rel: 'noopener' }, icon('play'), h('span', '열어 보기')), removeBtn(w, 'build', '웹 빌드', after)) : null);
}
