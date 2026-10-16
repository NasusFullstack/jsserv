// admin/dotpot — 화분키우기 게임 서버 관리: 유저(로우 데이터)·재화 뿌리기(모두/고른 유저)·차단과 해제·내려받기.
// 유저 = 게임이 처음 켤 때 만든 무작위 번호(이름·계정 없음). 컴퓨터 = 되돌릴 수 없는 지문.

import { h, toast } from '../core/dom.js';
import { call, session } from './session.js';

const API = '/dotpot/api/admin';
let tab = 'installs';
let picked = new Set();       // 체크한 유저 (재화 뿌리기 대상)
let query = '';
let sort = 'last_seen';

const kst = (t) => (t ? new Date(t * 1000).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }) : '-');
const short = (s) => (s ? `${s.slice(0, 8)}…` : '-');

export function renderDotpot(view) {
  view.replaceChildren(
    h('header.view__head', h('div', h('h1.view__title', '화분키우기'),
      h('p.view__sub', '꾸러미·뽑기는 서버가 정합니다 · 재화 뿌리기 · 버그·조작 의심 유저/컴퓨터 차단'))),
    h('div.dp-cards', h('p.empty-note', '불러오는 중…')),
    h('nav.dp-tabs', [['installs', '유저'], ['events', '재화 뿌리기·이벤트'], ['bans', '차단'], ['rates', '확률'], ['export', '내려받기']].map(([k, label]) =>
      h('button.btn.btn--sm' + (tab === k ? '.btn--primary' : '.btn--ghost'), { onclick: () => { tab = k; renderDotpot(view); } }, label))),
    h('section.dp-body', h('p.empty-note', '불러오는 중…')));
  call('GET', `${API}/summary`).then((s) => {
    view.querySelector('.dp-cards').replaceChildren(...[
      ['유저', s.installs], ['오늘 켬', s.active_1d], ['7일 켬', s.active_7d], ['남은 꾸러미 합', s.bundles_total],
      ['남은 뽑기권 합', s.tickets_total], ['오늘 뽑기', s.draws_1d], ['오늘 고급', s.premium_1d], ['오늘 거절', s.rejects_1d], ['차단 중', s.bans_active],
    ].map(([k, v]) => h('div.dp-card', h('small', k), h('b.mono', String(v)))));
  }).catch((e) => toast(e.message, true));
  const body = view.querySelector('.dp-body');
  ({ installs: drawInstalls, events: drawEvents, bans: drawBans, rates: drawRates, export: drawExport })[tab](body, view);
}

// ---------- 유저 ----------
async function drawInstalls(body, view) {
  const res = await call('GET', `${API}/installs?q=${encodeURIComponent(query)}&sort=${sort}&limit=300`).catch((e) => { toast(e.message, true); return null; });
  if (!res) return;
  const search = h('input.cinput', { placeholder: '유저 아이디·컴퓨터 지문 앞자리', value: query, onchange: (e) => { query = e.target.value.trim(); renderDotpot(view); } });
  const sorter = h('select.cinput.admin-select', { onchange: (e) => { sort = e.target.value; renderDotpot(view); } },
    [['last_seen', '최근 켠 순'], ['created', '등록 순'], ['bundles', '꾸러미 많은 순'], ['rejects', '거절 많은 순']].map(([v, l]) => h('option', { value: v, selected: sort === v }, l)));
  const pickInfo = h('span.view__sub', `체크 ${picked.size}개 (재화 뿌리기 대상)`);
  const rows = res.installs.map((i) => {
    const box = h('input', { type: 'checkbox', checked: picked.has(i.id), onchange: (e) => { if (e.target.checked) picked.add(i.id); else picked.delete(i.id); pickInfo.textContent = `체크 ${picked.size}개 (재화 뿌리기 대상)`; } });
    return h('tr' + (i.ban ? '.dp-banned' : ''),
      h('td', box),
      h('td.mono', h('a', { href: '#', onclick: (e) => { e.preventDefault(); drawOne(body, view, i.id); } }, short(i.id))),
      h('td', kst(i.last_seen)), h('td.mono', i.ver || '-'),
      h('td.num', String(i.bundles)), h('td.num', String(i.tickets)), h('td.num', String(i.draws)), h('td.num', String(i.rejects)),
      h('td', i.ban ? h('span.badge.is-hidden', `차단: ${i.ban}`) : ''));
  });
  body.replaceChildren(
    h('div.dp-tools', search, sorter, h('button.btn.btn--ghost.btn--sm', { onclick: () => { res.installs.forEach((i) => picked.add(i.id)); renderDotpot(view); } }, '보이는 것 모두 체크'),
      h('button.btn.btn--ghost.btn--sm', { onclick: () => { picked.clear(); renderDotpot(view); } }, '체크 비우기'), pickInfo),
    h('p.view__sub', `모두 ${res.total}명 · 아이디를 누르면 그 유저의 기록(로우 데이터)`),
    h('div.dp-scroll', h('table.table', h('thead', h('tr', h('th', ''), h('th', '유저 아이디'), h('th', '마지막 켬'), h('th', '판'),
      h('th.num', '꾸러미'), h('th.num', '뽑기권'), h('th.num', '뽑기'), h('th.num', '거절'), h('th', '차단'))), h('tbody', rows))));
}

async function drawOne(body, view, id) {
  const d = await call('GET', `${API}/installs/${id}`).catch((e) => { toast(e.message, true); return null; });
  if (!d) return;
  const i = d.install;
  const table = (title, list, cols) => h('div.dp-raw', h('h3', `${title} (${list.length})`),
    list.length ? h('div.dp-scroll', h('table.table', h('thead', h('tr', cols.map((c) => h('th', c)))),
      h('tbody', list.map((r) => h('tr', cols.map((c) => h('td.mono', /(^at$|drawn|created|last_seen|rewarded_at)/.test(c) ? kst(r[c]) : String(r[c] ?? '')))))))) : h('p.empty-note', '없음'));
  const reason = h('input.cinput', { placeholder: '차단 사유 (예: 중복 보상 버그 사용)' });
  const ban = async (kind) => {
    if (!reason.value.trim()) { toast('차단 사유를 적어 주세요', true); return; }
    try { await call('POST', `${API}/bans`, { kind, value: id, reason: reason.value.trim() }); toast('차단했습니다'); drawOne(body, view, id); } catch (e) { toast(e.message, true); }
  };
  const db = h('input.cinput.dp-num', { type: 'number', value: 0 });
  const dt = h('input.cinput.dp-num', { type: 'number', value: 0 });
  const adjReason = h('input.cinput', { placeholder: '고친 이유' });
  body.replaceChildren(
    h('button.btn.btn--ghost.btn--sm', { onclick: () => renderDotpot(view) }, '← 목록'),
    h('h2.dp-h', `유저 ${i.id}`),
    h('p.view__sub', `등록 ${kst(i.created)} · 마지막 ${kst(i.last_seen)} · 판 ${i.ver || '-'} · 꾸러미 ${i.bundles} · 뽑기권 ${i.tickets} · 예전 판에서 옮김 ${i.migrated_bundles || i.migrated_tickets ? `꾸러미 ${i.migrated_bundles}·뽑기권 ${i.migrated_tickets}` : '없음'}`),
    h('p.view__sub.mono', `컴퓨터 지문 ${i.device || '(아직 없음)'}${d.same_device.length ? ` · 같은 컴퓨터 다른 유저 ${d.same_device.length}명` : ''}`),
    d.ban ? h('p.dp-alert', `차단 중 (${d.ban.kind === 'device' ? '컴퓨터' : '유저'}) · 사유: ${d.ban.reason} · ${kst(d.ban.at)}`) : '',
    h('div.dp-tools', reason, h('button.btn.btn--danger.btn--sm', { onclick: () => ban('install') }, '이 유저 차단'),
      h('button.btn.btn--danger.btn--sm', { onclick: () => ban('device') }, '이 컴퓨터 차단')),
    h('div.dp-tools', h('span', '꾸러미 ±'), db, h('span', '뽑기권 ±'), dt, adjReason,
      h('button.btn.btn--ghost.btn--sm', { onclick: async () => {
        try { await call('POST', `${API}/installs/${id}/adjust`, { bundles: +db.value || 0, tickets: +dt.value || 0, reason: adjReason.value || '관리' }); toast('고쳤습니다'); drawOne(body, view, id); } catch (e) { toast(e.message, true); }
      } }, '개수 고치기')),
    table('장부 (개수가 바뀐 모든 일)', d.ledger, ['at', 'reason', 'd_bundles', 'd_tickets', 'ref']),
    table('거절 (버그·조작 의심)', d.rejects, ['at', 'reason', 'detail']),
    table('씨앗 (used = 상인에게 맡김 · src = fuse 상인에게 받음)', d.seeds, ['drawn', 'sid', 'kind', 'ptype', 'rare', 'n', 'legacy', 'src', 'used', 'rewarded', 'rewarded_at']),
    table('화분 (src = draw 뽑기 · kiln 공방 · seed:… 기본 화분 · legacy 예전 판, used = 공방에 맡김)', d.pots, ['drawn', 'pid', 'size', 'lux', 'n', 'src', 'used']),
    table('받은 도전과제', d.achievements || [], ['at', 'key']),
    table('일일 퀘스트 (care1·care3 = 물·영양 1·3번, draw1 = 꾸러미 열기)', d.daily || [], ['day', 'key', 'at', 'water', 'food']),
    table('받은 이벤트', d.grants, ['at', 'event']));
}

// ---------- 재화 뿌리기 · 이벤트 ----------
async function drawEvents(body, view) {
  const res = await call('GET', `${API}/events`).catch((e) => { toast(e.message, true); return null; });
  if (!res) return;
  const useB = h('input', { type: 'checkbox', checked: true });
  const nB = h('input.cinput.dp-num', { type: 'number', min: 1, max: 99, value: 1 });
  const useT = h('input', { type: 'checkbox' });
  const nT = h('input.cinput.dp-num', { type: 'number', min: 1, max: 99, value: 1 });
  const useG = h('input', { type: 'checkbox' });
  const nG = h('input.cinput.dp-num', { type: 'number', min: 1, max: 99, value: 1 });
  const msg = h('input.cinput', { placeholder: '우편 내용 (예: 추석 선물이에요!)', maxlength: 60 });
  const toAll = h('input', { type: 'radio', name: 'dpto', checked: !picked.size });
  const toPicked = h('input', { type: 'radio', name: 'dpto', checked: !!picked.size });
  const when = h('input.cinput', { type: 'datetime-local' });
  const incNew = h('input', { type: 'checkbox', checked: true });
  const pk = installPicker(picked, () => { if (picked.size) toPicked.checked = true; });
  const pickLabel = h('label', toPicked, ' 고른 유저에게만 (', pk.count, '명)');
  const send = async () => {
    const b = useB.checked ? +nB.value || 0 : 0;
    const t = useT.checked ? +nT.value || 0 : 0;
    const g = useG.checked ? +nG.value || 0 : 0;
    if (b + t + g <= 0) { toast('뿌릴 재화를 체크하고 개수를 넣어 주세요', true); return; }
    const targets = toPicked.checked ? [...picked] : null;
    if (targets && !targets.length) { toast('아래 목록에서 받을 유저를 체크해 주세요', true); return; }
    const who = targets ? `고른 유저 ${targets.length}명(${targets.slice(0, 3).map(short).join(', ')}${targets.length > 3 ? ' …' : ''})` : '모두';
    if (!confirm(`${who}에게 ${b ? `꾸러미 ${b}개 ` : ''}${t ? `화분 뽑기권 ${t}장 ` : ''}${g ? `배경 뽑기권 ${g}장 ` : ''}을 ${when.value ? when.value.replace('T', ' ') + '에' : '지금'} 뿌릴까요?`)) return;
    try {
      await call('POST', `${API}/events`, { bundles: b, tickets: t, bg: g, msg: msg.value, targets, start_at: when.value || '', include_new: incNew.checked });
      toast('뿌렸습니다 — 1.5.0부터는 게임 우편함에 와서 「받기」로 받고, 예전 버전은 켤 때 바로 받아요');
      renderDotpot(view);
    } catch (e) { toast(e.message, true); }
  };
  body.replaceChildren(
    h('div.dp-form',
      h('h3', '재화 뿌리기'),
      h('label.dp-row', useB, h('span', '씨앗 꾸러미'), nB, h('span', '개')),
      h('label.dp-row', useT, h('span', '화분 뽑기권'), nT, h('span', '장')),
      h('label.dp-row', useG, h('span', '배경 뽑기권'), nG, h('span', '장')),
      h('label.dp-row', h('span', '알림 글'), msg),
      h('div.dp-row', h('label', toAll, ' 모두에게'), pickLabel),
      pk.el,
      h('label.dp-row', h('span', '보낼 시각 (비우면 지금, 한국 시간)'), when),
      h('label.dp-row', incNew, h('span', '모두에게일 때: 이벤트 뒤 7일 안에 처음 켠 사람도 받기')),
      h('button.btn.btn--primary', { onclick: send }, '뿌리기')),
    h('h3', '지금까지 이벤트'),
    res.events.length ? h('div.dp-scroll', h('table.table', h('thead', h('tr', ['번호', '보냄', '끝', '꾸러미', '화분 뽑기권', '배경 뽑기권', '대상', '받음', '글', ''].map((c) => h('th', c)))),
      h('tbody', res.events.map((e) => h('tr' + (e.cancelled ? '.dp-banned' : ''),
        h('td.mono', String(e.id)), h('td', kst(e.start_at)), h('td', kst(e.end_at)), h('td.num', String(e.bundles)), h('td.num', String(e.tickets)), h('td.num', String(e.bg_tickets || 0)),
        h('td', e.target_all ? '모두' : `고른 ${e.targets}명`), h('td.num', String(e.granted)), h('td', e.msg),
        h('td', e.cancelled ? '취소됨' : h('button.btn.btn--ghost.btn--sm', { onclick: async () => {
          if (!confirm('이 이벤트를 취소할까요? (이미 받은 사람은 그대로)')) return;
          try { await call('POST', `${API}/events/${e.id}/cancel`); renderDotpot(view); } catch (er) { toast(er.message, true); }
        } }, '취소'))))))) : h('p.empty-note', '아직 없음'));
}

// ---------- 유저 고르기 목록 (재화 뿌리기·차단이 같이 씀) ----------
// set = 고른 유저 아이디들 (화면을 다시 그려도 유지). 찾기는 유저 아이디 앞자리·컴퓨터 지문
function installPicker(set, onChange) {
  const count = h('b.mono', String(set.size));
  const box = h('div.dp-scroll.dp-pick', h('p.empty-note', '불러오는 중…'));
  let shown = [];
  const changed = () => { count.textContent = String(set.size); if (onChange) onChange(); };
  const draw = () => {
    if (!shown.length) { box.replaceChildren(h('p.empty-note', '맞는 유저가 없습니다')); return; }
    box.replaceChildren(h('table.table', h('thead', h('tr', h('th', ''), h('th', '유저 아이디'), h('th', '마지막 켬'), h('th', '판'), h('th.num', '꾸러미'), h('th.num', '뽑기권'), h('th.num', '거절'), h('th', '차단'))),
      h('tbody', shown.map((i) => h('tr' + (i.ban ? '.dp-banned' : ''),
        h('td', h('input', { type: 'checkbox', checked: set.has(i.id), onchange: (e) => { if (e.target.checked) set.add(i.id); else set.delete(i.id); changed(); } })),
        h('td.mono', { title: i.id }, i.id), h('td', kst(i.last_seen)), h('td.mono', i.ver || '-'),
        h('td.num', String(i.bundles)), h('td.num', String(i.tickets)), h('td.num', String(i.rejects)), h('td', i.ban ? `차단: ${i.ban}` : ''))))));
  };
  const load = async (q) => {
    const r = await call('GET', `${API}/installs?q=${encodeURIComponent(q)}&sort=last_seen&limit=300`).catch((e) => { toast(e.message, true); return null; });
    if (!r) return;
    shown = r.installs;
    draw();
  };
  let timer = 0;
  const find = h('input.cinput', { placeholder: '유저 아이디(앞자리)·컴퓨터 지문으로 찾기', oninput: (e) => { clearTimeout(timer); timer = setTimeout(() => load(e.target.value.trim()), 250); } });
  const el = h('div',
    h('div.dp-tools', find,
      h('button.btn.btn--ghost.btn--sm', { onclick: () => { shown.forEach((i) => set.add(i.id)); changed(); draw(); } }, '보이는 것 모두 체크'),
      h('button.btn.btn--ghost.btn--sm', { onclick: () => { set.clear(); changed(); draw(); } }, '체크 비우기')),
    box);
  load('');
  return { el, count };
}

// ---------- 차단 ----------
let showAll = false;
const banPick = new Set();   // 차단할 유저 (재화 뿌리기 대상과 따로)
async function drawBans(body, view) {
  const res = await call('GET', `${API}/bans?active=${showAll ? 0 : 1}`).catch((e) => { toast(e.message, true); return null; });
  if (!res) return;
  const reason = h('input.cinput', { placeholder: '차단 사유 (예: 중복 보상 버그 사용)', maxlength: 200 });
  const pk = installPicker(banPick);
  const doBan = async (kind) => {
    const why = reason.value.trim();
    if (!banPick.size) { toast('아래 목록에서 차단할 유저를 체크해 주세요', true); return; }
    if (!why) { toast('차단 사유를 적어 주세요', true); return; }
    const what = kind === 'device' ? '컴퓨터' : '유저';
    if (!confirm(`고른 유저 ${banPick.size}명의 ${what}을(를) 차단할까요?\n사유: ${why}${kind === 'device' ? '\n(그 컴퓨터에서 새로 깔아도 막힙니다)' : ''}`)) return;
    const fail = [];
    for (const id of [...banPick]) {
      try { await call('POST', `${API}/bans`, { kind, value: id, reason: why }); } catch (e) { fail.push(`${short(id)} ${e.message}`); }
    }
    if (fail.length) toast(`일부 실패: ${fail.join(' · ')}`, true); else toast(`${banPick.size}명 차단했습니다`);
    banPick.clear();
    renderDotpot(view);
  };
  body.replaceChildren(
    h('div.dp-form',
      h('h3', '차단하기'),
      h('label.dp-row', h('span', '사유'), reason),
      h('div.dp-row', h('span', '고른 유저 '), pk.count, h('span', '명')),
      pk.el,
      h('div.dp-tools',
        h('button.btn.btn--danger.btn--sm', { onclick: () => doBan('install') }, '고른 유저 차단'),
        h('button.btn.btn--danger.btn--sm', { onclick: () => doBan('device') }, '고른 유저의 컴퓨터 차단'))),
    h('h3', '차단 목록'),
    h('div.dp-tools', h('label', h('input', { type: 'checkbox', checked: showAll, onchange: (e) => { showAll = e.target.checked; renderDotpot(view); } }), ' 푼 것도 보기')),
    res.bans.length ? h('div.dp-scroll', h('table.table', h('thead', h('tr', ['번호', '종류', '대상', '사유', '차단한 때', '상태', ''].map((c) => h('th', c)))),
      h('tbody', res.bans.map((b) => h('tr',
        h('td.mono', String(b.id)), h('td', b.kind === 'device' ? '컴퓨터' : '유저'), h('td.mono', { title: b.value }, short(b.value)), h('td', b.reason), h('td', kst(b.at)),
        h('td', b.active ? '차단 중' : `풂 ${kst(b.lifted_at)}${b.lift_note ? ` (${b.lift_note})` : ''}`),
        h('td', b.active ? h('button.btn.btn--ghost.btn--sm', { onclick: async () => {
          const note = prompt('푸는 이유 (비워도 됨)', '') ?? null;
          if (note === null) return;
          try { await call('POST', `${API}/bans/${b.id}/lift`, { note }); toast('풀었습니다'); renderDotpot(view); } catch (e) { toast(e.message, true); }
        } }, '차단 풀기') : '')))))) : h('p.empty-note', '차단 중인 것이 없습니다'));
}

// ---------- 확률 ----------
// 서버가 뽑을 때 쓰는 확률. 바꾸면 다음 뽑기부터 바로 적용, 게임 안 「고급 나무 n%」 글자는 켤 때·뽑을 때 받아 맞춤
const pct = (v) => +(v * 100).toFixed(2);
async function drawRates(body, view) {
  const res = await call('GET', `${API}/rates`).catch((e) => { toast(e.message, true); return null; });
  if (!res) return;
  const inputs = {};
  const out = h('div');
  const val = (k) => Math.max(0, +inputs[k].value || 0) / 100;
  const out2 = h('div');
  const out3 = h('div');
  const sizeKeys = ['kiln_small', 'kiln_big', 'kiln_huge'];
  function preview() {
    const p = val('premium'), t = val('tree'), r = val('rare');
    const card = (k, v) => h('div.dp-card', h('small', k), h('b.mono', `${pct(v)}%`));
    out.replaceChildren(
      h('p.view__sub', '꾸러미 하나를 열면 실제로 이렇게 나와요 (시즌 고급 나무는 그 달에만 종류에 끼어요)'),
      h('div.dp-cards', inputs.mystic ? card('신비한 꽃 5종 합 (게임엔 안 보임)', val('mystic')) : '', card('고급 나무', p), card('묘목 (나무)', (1 - p) * t), card('꽃 씨앗', (1 - p) * (1 - t)), card('그중 신비한', (1 - p) * r), card('고급 화분 (화분 뽑기)', val('lux'))));
    if (inputs.fruit_rot) {
      const gs = ['fruit_rot', 'fruit_meh', 'fruit_good', 'fruit_dept'].map(val), norm = 1 - gs.reduce((a, b) => a + b, 0);
      out3.replaceChildren(
        h('p.view__sub', norm >= 0 ? '열매 하나가 떨어지면 이렇게 나와요 (일반 = 나머지, 좋음·백화점급은 고급 열매 능력만큼 곱해서 오름)' : '⚠ 등급 합이 100% 를 넘어요 — 저장할 수 없어요'),
        h('div.dp-cards', card('썩음', gs[0]), card('그럭저럭', gs[1]), card('일반', Math.max(0, norm)), card('좋음', gs[2]), card('백화점급', gs[3]), card('만렙 능력 2개', val('abil_two'))));
    }
    if (!inputs.kiln_small) return;
    const sw = sizeKeys.map(val), sum = sw.reduce((a, b) => a + b, 0);
    const share = (i) => (sum > 0 ? sw[i] / sum : 1 / 3);
    out2.replaceChildren(
      h('p.view__sub', sum > 0 ? '맡기면 실제로 이렇게 나와요 (크기 비율은 셋의 합으로 나눠 씀)' : '⚠ 크기 비율이 모두 0% — 저장할 수 없어요'),
      h('div.dp-cards', card('상인: 고급 묘목', val('fuse')), card('공방: 고급 화분', val('kiln')),
        card('공방: 작은 화분', share(0)), card('공방: 큰 화분', share(1)), card('공방: 아주 큰 화분', share(2))));
  }
  const row = (k) => {
    const [lo, hi] = res.limits[k];
    const inp = h('input.cinput.dp-num', { type: 'number', step: 0.01, min: lo * 100, max: hi * 100, value: pct(res.rates[k]), oninput: preview });
    inputs[k] = inp;
    const changed = Math.abs(res.rates[k] - res.defaults[k]) > 1e-9;
    return h('div.dp-row',
      h('span.dp-rate-name', res.names[k]), inp, h('span', '%'),
      h('span.view__sub', `기본 ${pct(res.defaults[k])}% · ${lo * 100}~${hi * 100}%`),
      changed ? h('span.badge', '바꿈') : '',
      h('button.btn.btn--ghost.btn--sm', { onclick: () => { inp.value = pct(res.defaults[k]); preview(); } }, '기본값으로'));
  };
  const groups = res.groups || [['뽑기 확률', Object.keys(res.names)]];
  const sections = groups.map(([title, keys], gi) => [h('h3', title), ...keys.filter((k) => res.names[k]).map(row), [out, out2, out3][gi] || '']).flat();
  const note = h('input.cinput', { placeholder: '바꾼 이유 (예: 주말 고급 나무 이벤트)', maxlength: 200 });
  const save = async () => {
    const rates = {};
    for (const k of Object.keys(inputs)) rates[k] = Math.round(val(k) * 10000) / 10000;
    const diff = Object.keys(rates).filter((k) => Math.abs(rates[k] - res.rates[k]) > 1e-9);
    if (!diff.length) { toast('바뀐 확률이 없습니다'); return; }
    if (!confirm(`${diff.map((k) => `${res.names[k]}: ${pct(res.rates[k])}% → ${pct(rates[k])}%`).join('\n')}\n\n이렇게 바꿀까요? (다음 뽑기부터 바로)`)) return;
    try {
      await call('POST', `${API}/rates`, { rates, note: note.value });
      toast('확률을 바꿨습니다 — 게임 글자는 켤 때·뽑을 때 맞춰져요');
      renderDotpot(view);
    } catch (e) { toast(e.message, true); }
  };
  const name = (k) => res.names[k] || k;
  body.replaceChildren(
    h('div.dp-form',
      ...sections,
      h('label.dp-row', h('span', '메모'), note),
      h('button.btn.btn--primary', { onclick: save }, '확률 저장')),
    h('h3', '바뀐 기록'),
    res.log.length ? h('div.dp-scroll', h('table.table', h('thead', h('tr', ['바꾼 때', '확률', '전', '후', '메모'].map((c) => h('th', c)))),
      h('tbody', res.log.map((l) => h('tr', h('td', kst(l.at)), h('td', name(l.key)), h('td.num', `${pct(l.old)}%`), h('td.num', `${pct(l.new)}%`), h('td', l.note || '')))))) : h('p.empty-note', '아직 바꾼 적 없음'));
  preview();
}

// ---------- 내려받기 ----------
function drawExport(body) {
  const tables = [['installs', '유저'], ['ledger', '장부'], ['draws', '뽑기·상인·공방'], ['seeds', '씨앗'], ['pots', '화분'], ['achievements', '도전과제'], ['daily', '일일 퀘스트'], ['events', '이벤트'], ['grants', '받은 이벤트'], ['rejects', '거절'], ['bans', '차단'], ['rate_log', '확률 기록']];
  body.replaceChildren(h('p.view__sub', '표 전체를 CSV 로 (엑셀에서 열림). 비밀값 지문은 빠집니다.'),
    h('div.dp-tools', tables.map(([t, l]) => h('button.btn.btn--ghost.btn--sm', { onclick: async () => {
      try {
        const res = await fetch(`${API}/export/${t}`, { headers: { 'X-Admin-Key': session.key }, cache: 'no-store' });
        if (!res.ok) throw new Error(`실패 (${res.status})`);
        const url = URL.createObjectURL(await res.blob());
        const a = h('a', { href: url, download: `dotpot_${t}.csv` });
        document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } catch (e) { toast(e.message, true); }
    } }, l))));
}
