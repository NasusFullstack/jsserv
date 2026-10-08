// fx/boot — 첫 방문 부팅 화면. 몇 줄이 찍히고 막대가 차면 위로 걷히며 사이트가 드러난다.
// boot-gate.js 가 html.booting 을 붙였을 때만 돈다. 누르면 바로 건너뛴다. 이 탭에서는 한 번만.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runBoot(dataPromise) {
  const html = document.documentElement;
  const boot = document.getElementById('boot');
  if (!html.classList.contains('booting') || !boot) return;
  const lines = document.getElementById('bootLines');
  const bar = document.getElementById('bootBar');
  let skip = false;
  boot.addEventListener('pointerdown', () => { skip = true; }, { once: true });
  addEventListener('keydown', () => { skip = true; }, { once: true });

  const say = async (text, cls = '', wait = 140) => {
    const p = document.createElement('p');
    if (cls) p.className = cls;
    lines.append(p);
    for (let i = 1; i <= text.length && !skip; i += 2) {
      p.textContent = text.slice(0, i);
      await sleep(8);
    }
    p.textContent = text;
    if (!skip) await sleep(wait);
  };
  const progress = (p) => bar.parentElement.style.setProperty('--p', p);

  await say('> jsserv://boot', 'p', 120);
  progress(.25);
  let data = null;
  try { data = await Promise.race([dataPromise, sleep(1500)]); } catch { /* 아래에서 처리 */ }
  const works = data?.works?.length;
  await say(`  works ........... ${works ?? '?'}`, '', 90);
  progress(.6);
  await say(`  visitors today .. ${data?.stats?.today?.visitors ?? '?'}`, '', 90);
  progress(.85);
  await say('  status .......... ONLINE', 'ok', 160);
  progress(1);
  if (!skip) await sleep(220);

  try { sessionStorage.setItem('jsserv.booted', '1'); } catch { /* 저장 안 돼도 괜찮다 */ }
  boot.classList.add('is-done');
  await sleep(skip ? 250 : 600);
  html.classList.remove('booting');
  setTimeout(() => boot.remove(), 400);
}
