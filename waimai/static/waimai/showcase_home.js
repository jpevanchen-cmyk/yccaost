/* 展示主页：吸顶导航与回顶部 */
(function () {
  var btn = document.getElementById('showcase-back-top');
  if (!btn) return;
  function onScroll() {
    btn.hidden = window.scrollY < 240;
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  btn.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
})();
