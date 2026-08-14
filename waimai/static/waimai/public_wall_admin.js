/* 公开留言壁管理：先记下点的是哪颗按钮，再关按钮防连点 */
(function () {
  var forms = document.querySelectorAll('.js-public-wall-mod');
  if (!forms.length) return;

  forms.forEach(function (form) {
    form.addEventListener('submit', function (ev) {
      if (form.getAttribute('data-busy') === '1') {
        ev.preventDefault();
        return;
      }
      var btn = ev.submitter;
      if (btn && btn.classList.contains('js-public-wall-delete')) {
        if (!window.confirm('确定删除该楼？库里会留下，大厅上看不到原文，楼号还在。')) {
          ev.preventDefault();
          return;
        }
      }
      var actionInput = form.querySelector('.js-public-wall-action');
      if (actionInput && btn && btn.name === 'action') {
        actionInput.value = btn.value || '';
      }
      form.setAttribute('data-busy', '1');
      var keyInput = form.querySelector('[name=idempotency_key]');
      if (keyInput && window.YcIdempotency && typeof window.YcIdempotency.newKey === 'function') {
        keyInput.value = window.YcIdempotency.newKey();
      }
      if (btn) btn.disabled = true;
    });
  });
})();
