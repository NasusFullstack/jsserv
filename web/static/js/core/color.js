// core/color — 색 계산 (작품마다 강조 색에서 그림 색을 뽑을 때).

export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return [94, 234, 212];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > .5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, s * 100, l * 100];
}

export const hsl = (h, s, l, a = 1) => `hsla(${((h % 360) + 360) % 360}, ${s}%, ${l}%, ${a})`;

/** 강조 색 → 그림에 쓸 색 묶음 (원색, 옆 색, 먼 색, 어두운 바탕) */
export function paletteFrom(hex) {
  const [h, s] = rgbToHsl(hexToRgb(hex));
  const sat = Math.max(55, Math.min(90, s));
  return {
    h,
    sat,
    main: (a = 1) => hsl(h, sat, 62, a),
    side: (a = 1) => hsl(h + 48, sat, 66, a),
    far: (a = 1) => hsl(h - 60, sat * .8, 58, a),
    deep: hsl(h, 40, 6),
    mid: hsl(h + 20, 45, 13),
  };
}

/** 글자 → 씨앗 (같은 글자면 언제나 같은 그림) */
export function seedOf(text) {
  let x = 2166136261;
  for (const c of String(text)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619); }
  return x >>> 0;
}

/** 씨앗으로 도는 난수 0~1 */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
