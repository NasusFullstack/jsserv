// core/api — 서버와 주고받기. 화면 코드는 fetch 를 직접 부르지 않고 이것만 쓴다.

export async function getJSON(url, options = {}) {
  const res = await fetch(url, { cache: 'no-store', ...options });
  let body = null;
  try { body = await res.json(); } catch { /* 본문 없음 */ }
  if (!res.ok) {
    const err = new Error((body && body.error) || `요청 실패 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body;
}

export const overview = () => getJSON('/api/overview');

/** JSON 을 보내고 JSON 을 받는다 (댓글 쓰기·지우기) */
export const sendJSON = (method, url, body) => getJSON(url, {
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/** 서버까지 한 번 다녀오는 시간(ms). 실패하면 null */
export async function ping() {
  const t = performance.now();
  try {
    const res = await fetch('/health', { cache: 'no-store' });
    if (!res.ok) return null;
    await res.text();
    return Math.round(performance.now() - t);
  } catch { return null; }
}
