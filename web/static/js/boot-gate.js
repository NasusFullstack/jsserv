// 첫 방문(이 탭에서 처음)이고 움직임을 줄이는 설정이 아니면, 그리기 전에 부팅 화면을 켠다.
// 모듈이 아닌 작은 동기 스크립트라서 첫 화면이 깜빡이지 않는다. 나머지는 home/main.js 가 한다.
(function () {
  try {
    var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce && !sessionStorage.getItem('jsserv.booted')) document.documentElement.classList.add('booting');
  } catch (e) { /* 저장소를 못 쓰면 부팅 화면 없이 */ }
})();
