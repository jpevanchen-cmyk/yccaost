/* 公开留言壁：提交前写入幂等编号，防止连点出两楼 */
(function () {
  var form = document.getElementById('public-wall-form');
  if (!form) return;

  var submitBtn = document.getElementById('public-wall-submit');
  var keyInput = form.querySelector('[name=idempotency_key]');
  var submitting = false;

  form.addEventListener('submit', function (ev) {
    if (submitting) {
      ev.preventDefault();
      return;
    }
    submitting = true;
    if (keyInput && !keyInput.value && window.YcIdempotency && typeof window.YcIdempotency.newKey === 'function') {
      keyInput.value = window.YcIdempotency.newKey();
    }
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '正在贴上…';
    }
  });
})();
