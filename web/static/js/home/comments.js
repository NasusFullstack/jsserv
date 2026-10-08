// home/comments — 작품 자세히 아래의 댓글.
//
//   깊이는 2: 본댓 → 답글. 답글에 다시 답하면 깊이를 늘리지 않고 "@닉네임"을 붙여 그 글 바로 밑에 놓는다
//   (순서는 서버가 정해서 준다 — features/site/comment_rules.py). 답글이 2개 이상이면 접어 두고 펼친다.
//   계정이 없어서 닉네임 + 비밀번호(지울 때 씀). 닉네임은 이 브라우저가 기억한다.
//   글은 언제나 글자로만 넣는다(태그가 들어 있어도 실행되지 않음).

import { h, toast } from '../core/dom.js';
import { sendJSON, getJSON } from '../core/api.js';
import { ago } from '../core/format.js';

const NICK_KEY = 'jsserv.nick';
const PAGE = 20;
const remember = { get: () => { try { return localStorage.getItem(NICK_KEY) || ''; } catch { return ''; } },
  set: (v) => { try { localStorage.setItem(NICK_KEY, v); } catch { /* 괜찮다 */ } } };
let lastPw = '';    // 이 화면에서 쓴 비밀번호 (지울 때 다시 안 쳐도 되게, 저장은 안 함)

export function mountComments(box, work, onCount) {
  const st = { threads: [], count: 0, open: new Set(), reply: null, del: null, shown: PAGE, fresh: null };
  // 다시 그려도 쓰던 글이 날아가지 않게 글쓰기 칸은 만들어 둔 것을 계속 쓴다
  let mainForm = null;
  let replyBox = null;    // { id, el }
  let delBox = null;      // { id, el }
  const url = `/api/works/${encodeURIComponent(work.slug)}/comments`;

  const apply = (data, fresh = null) => {
    st.threads = data.threads;
    st.count = data.count;
    st.fresh = fresh;
    onCount?.(data.count);
    render();
    if (fresh) {
      const el = box.querySelector(`[data-cid="${fresh}"]`);
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  };

  // ---- 글쓰기 칸 (본댓·답글 같이 씀) ----
  const form = ({ parent = null, mention = null, onCancel = null } = {}) => {
    const nick = h('input.cinput', { name: 'nick', maxlength: 20, placeholder: '닉네임', value: remember.get(), autocomplete: 'nickname', required: true });
    const pw = h('input.cinput', { name: 'password', type: 'password', maxlength: 40, minlength: 4, placeholder: '비밀번호 (지울 때)', value: lastPw, autocomplete: 'new-password', required: true });
    const body = h('textarea.cinput.cinput--body', { name: 'body', maxlength: 1000, rows: parent ? 2 : 3, required: true,
      placeholder: mention ? `@${mention} 에게 답글` : parent ? '답글 달기' : '작품에 대한 생각을 남겨 주세요' });
    const trap = h('input.hp', { name: 'website', tabindex: -1, autocomplete: 'off', 'aria-hidden': 'true' });   // 로봇 함정
    const left = h('span.cform__left.mono', '0 / 1000');
    const send = h('button.btn.btn--primary.btn--sm', { type: 'submit' }, parent ? '답글 쓰기' : '댓글 쓰기');
    body.addEventListener('input', () => { left.textContent = `${body.value.length} / 1000`; });
    const f = h(`form.cform${parent ? '.cform--reply' : ''}`,
      h('div.cform__who', nick, pw), body, trap,
      h('div.cform__foot', left, onCancel ? h('button.btn.btn--ghost.btn--sm', { type: 'button', onclick: onCancel }, '취소') : null, send));
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      send.disabled = true;
      try {
        const data = await sendJSON('POST', url, { nick: nick.value, password: pw.value, body: body.value, parent, website: trap.value });
        remember.set(nick.value.trim());
        lastPw = pw.value;
        body.value = '';
        left.textContent = '0 / 1000';
        if (parent) {
          const top = topOf(data.threads, data.id);
          if (top) st.open.add(top);
          st.reply = null;
          replyBox = null;
        }
        apply(data, data.id);
        toast(parent ? '답글을 달았습니다' : '댓글을 남겼습니다');
      } catch (err) {
        toast(err.message, true);
      } finally {
        send.disabled = false;
      }
    });
    if (parent) requestAnimationFrame(() => body.focus());
    return f;
  };

  // ---- 지우기: 그 자리에서 비밀번호를 묻는다 ----
  const delForm = (c) => {
    const pw = h('input.cinput', { type: 'password', placeholder: '쓸 때 넣은 비밀번호', value: lastPw, maxlength: 40 });
    const f = h('form.cdel', pw,
      h('button.btn.btn--danger.btn--sm', { type: 'submit' }, '지우기'),
      h('button.btn.btn--ghost.btn--sm', { type: 'button', onclick: () => { st.del = null; render(); } }, '취소'));
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = await sendJSON('DELETE', `/api/comments/${c.id}`, { password: pw.value });
        st.del = null;
        delBox = null;
        apply(data);
        toast('지웠습니다');
      } catch (err) {
        toast(err.message, true);
      }
    });
    requestAnimationFrame(() => pw.focus());
    return f;
  };

  // ---- 글 하나 ----
  const item = (c, isReply) => {
    const cls = `li.c${isReply ? '.c--reply' : ''}${c.deleted ? '.c--deleted' : ''}${st.fresh === c.id ? '.is-new' : ''}`;
    if (c.deleted) return h(cls, { data: { cid: c.id } }, h('p.c__body', '삭제된 댓글입니다'));
    const actions = h('div.c__actions',
      h('button', { type: 'button', onclick: () => { st.reply = st.reply === c.id ? null : c.id; st.del = null; render(); } }, '답글'),
      c.owner ? null : h('button', { type: 'button', onclick: () => { st.del = st.del === c.id ? null : c.id; st.reply = null; render(); } }, '삭제'));
    return h(cls, { data: { cid: c.id } },
      h('div.c__head', h('b.c__nick', c.nick), c.owner ? h('span.c__owner', '작성자') : null, h('time.c__time', { datetime: c.created, title: c.created.replace('T', ' ').slice(0, 16) }, ago(c.created))),
      h('p.c__body', c.mention ? h('span.c__at', `@${c.mention}`) : null, c.body),
      actions,
      st.del === c.id ? keep('del', c.id, () => delForm(c)) : null,
      st.reply === c.id ? keep('reply', c.id, () => form({ parent: c.id, mention: isReply ? c.nick : null, onCancel: () => { st.reply = null; render(); } })) : null);
  };

  // ---- 본댓 하나와 그 답글들 (2개 이상이면 접힘) ----
  const thread = (t) => {
    const n = t.replies.length;
    const open = n < 2 || st.open.has(t.id);
    const toggle = n >= 2 ? h('button.c__more', {
      type: 'button',
      'aria-expanded': open ? 'true' : 'false',
      onclick: () => { if (open) st.open.delete(t.id); else st.open.add(t.id); render(); },
    }, h('i', { 'aria-hidden': 'true' }), open ? '답글 숨기기' : `답글 ${n}개 보기`) : null;
    return h('li.cthread',
      h('ol.cthread__top', item(t, false)),
      n ? h('div.c__replies', toggle, open ? h('ol', t.replies.map((r) => item(r, true))) : null) : null);
  };

  /** 같은 글의 답글·지우기 칸이면 만들어 둔 것을 다시 쓴다 */
  const keep = (kind, id, make) => {
    const slot = kind === 'reply' ? replyBox : delBox;
    if (slot && slot.id === id) return slot.el;
    const made = { id, el: make() };
    if (kind === 'reply') replyBox = made; else delBox = made;
    return made.el;
  };

  const render = () => {
    const list = st.threads.slice(0, st.shown);
    if (st.reply === null) replyBox = null;
    if (st.del === null) delBox = null;
    mainForm ||= form();
    box.replaceChildren(...[      // replaceChildren 은 null 을 "null" 글자로 넣어서 걸러 낸다
      h('div.comments__head', h('h3', '댓글 ', h('span', String(st.count))), h('span.comments__note', '닉네임과 비밀번호만 있으면 됩니다. 비밀번호는 지울 때 씁니다.')),
      mainForm,
      st.threads.length
        ? h('ol.clist', list.map(thread))
        : h('p.comments__empty', '첫 댓글을 남겨 보세요.'),
      st.threads.length > st.shown ? h('button.btn.btn--ghost.btn--sm.comments__more', {
        type: 'button', onclick: () => { st.shown += PAGE; render(); },
      }, `댓글 더 보기 (${st.threads.length - st.shown})`) : null,
    ].filter(Boolean));
  };

  box.replaceChildren(h('p.comments__empty', '댓글을 불러오는 중…'));
  getJSON(url).then((data) => apply(data)).catch(() => box.replaceChildren(h('p.comments__empty', '댓글을 불러오지 못했습니다.')));
}

/** 새 글 번호가 들어 있는 본댓 번호 (답글을 달면 그 본댓을 펼쳐 둔다) */
function topOf(threads, id) {
  for (const t of threads) {
    if (t.id === id || t.replies.some((r) => r.id === id)) return t.id;
  }
  return null;
}
