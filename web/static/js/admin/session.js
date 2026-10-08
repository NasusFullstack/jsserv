// admin/session — 열쇠를 들고 서버와 주고받기.
// 열쇠는 이 탭의 sessionStorage 에만 둔다(탭을 닫으면 사라짐). 요청마다 X-Admin-Key 헤더로 보낸다.

const KEY = 'jsserv.admin';

export const session = {
  get key() { try { return sessionStorage.getItem(KEY) || ''; } catch { return this._k || ''; } },
  set key(v) { try { if (v) sessionStorage.setItem(KEY, v); else sessionStorage.removeItem(KEY); } catch { this._k = v; } },
};

export class AuthError extends Error {}

/** JSON 요청. 403 이면 AuthError (열쇠가 틀렸거나 잠김) */
export async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    cache: 'no-store',
    headers: { 'X-Admin-Key': session.key, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* 본문 없음 */ }
  if (res.status === 403 || res.status === 429) throw new AuthError(data?.error || '열쇠가 맞지 않습니다');
  if (!res.ok) throw new Error(data?.error || `실패 (${res.status})`);
  return data;
}

/** 파일 올리기 (진행률을 알려 준다). onProgress(0~1) */
export function upload(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.setRequestHeader('X-Admin-Key', session.key);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* 본문 없음 */ }
      if (xhr.status === 403 || xhr.status === 429) reject(new AuthError(data?.error || '열쇠가 맞지 않습니다'));
      else if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data?.error || `실패 (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error('연결이 끊겼습니다'));
    xhr.send(file);
  });
}
