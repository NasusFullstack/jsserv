// core/format — 숫자·날짜·크기를 사람이 읽는 꼴로.

const nf = new Intl.NumberFormat('ko-KR');
export const num = (n) => nf.format(Math.round(n || 0));

export function bytes(n) {
  if (n == null) return '-';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}

/** '2026-10-08T12:00:00+09:00' → '2026.10.08' */
export function date(iso) {
  if (!iso) return '-';
  return iso.slice(0, 10).replaceAll('-', '.');
}

/** '2026-10-08' → '10.08' */
export const md = (day) => day.slice(5).replace('-', '.');

/** 초 → '3일 04:12:55' */
export function uptime(s) {
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400);
  const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${d ? d + '일 ' : ''}${hh}:${mm}:${ss}`;
}

/** 지금 한국 시각 'HH:MM:SS' */
export function kstClock() {
  return new Date().toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
}

/** 언제였는지: '방금', '3시간 전', '2026.10.01' */
export function ago(iso) {
  if (!iso) return '-';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return '방금';
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}일 전`;
  return date(iso);
}
