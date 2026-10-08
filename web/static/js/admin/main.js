// admin/main — 관리 화면 조립: 잠금 화면 → 열쇠 확인 → 메뉴(대시보드·작품·설정) → 고칠 때마다 다시 받아 그리기.
//
//   session.js    열쇠 보관과 서버 요청
//   dashboard.js  숫자·그래프·서버 상태
//   works.js      작품 편집과 파일 올리기
//   comments.js   댓글 (작성자 답글·지우기)
//   settings.js   사이트 설정

import { $, $$, toast } from '../core/dom.js';
import { AuthError, call, session } from './session.js';
import { renderDashboard } from './dashboard.js';
import { renderWorks } from './works.js';
import { renderSettings } from './settings.js';
import { renderComments } from './comments.js';

const views = { dash: renderDashboard, works: renderWorks, comments: renderComments, settings: renderSettings };
let current = 'dash';
let data = null;

async function load() {
  data = await call('GET', '/api/admin/overview');
  $$('[data-site-name]').forEach((el) => { el.textContent = data.site.name; });
}

function show(name) {
  current = name;
  $$('.side__nav button').forEach((b) => b.setAttribute('aria-current', b.dataset.view === name ? 'page' : 'false'));
  Object.keys(views).forEach((k) => { $(`#view-${k}`).hidden = k !== name; });
  const view = $(`#view-${name}`);
  view.style.animation = 'none';
  void view.offsetWidth;          // 메뉴를 바꿀 때마다 들어오는 움직임을 다시
  view.style.animation = '';
  views[name](view, data, refresh);
  try { history.replaceState(null, '', `#${name}`); } catch { /* 괜찮다 */ }
}

/** 고친 뒤 다시 받아서 지금 화면(또는 to)을 다시 그린다 */
async function refresh(to) {
  try {
    await load();
    show(typeof to === 'string' ? to : current);
  } catch (err) {
    handle(err);
  }
}

function handle(err) {
  if (err instanceof AuthError) { lock(err.message); return; }
  toast(err.message, true);
}

function lock(message = '') {
  session.key = '';
  $('#console').hidden = true;
  $('#lock').hidden = false;
  $('#lockErr').textContent = message;
  $('#key').value = '';
  setTimeout(() => $('#key').focus(), 50);
}

async function unlock() {
  await load();
  $('#lock').hidden = true;
  $('#console').hidden = false;
  const want = location.hash.slice(1);
  show(views[want] ? want : 'dash');
}

function main() {
  $('#lockForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || $('.lock__go');
    session.key = $('#key').value.trim();
    btn.disabled = true;
    $('#lockErr').textContent = '';
    try {
      await unlock();
    } catch (err) {
      session.key = '';
      $('#lockErr').textContent = err.message;
      $('#lock').classList.remove('is-shake');
      void $('#lock').offsetWidth;
      $('#lock').classList.add('is-shake');
    } finally {
      btn.disabled = false;
    }
  });
  $$('.side__nav button').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));
  $('#lockBtn').addEventListener('click', () => lock('잠갔습니다'));

  if (session.key) unlock().catch((err) => lock(err instanceof AuthError ? err.message : ''));
  else lock();
}

main();
