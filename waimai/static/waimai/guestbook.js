/* 留言板：确认弹窗 + Ajax 提交 + 编号复制 + 防连点 */
(function () {
  var form = document.getElementById('guestbook-new-form');
  if (!form) return;

  var confirmModal = document.getElementById('guestbook-confirm-modal');
  var resultModal = document.getElementById('guestbook-result-modal');
  var nameInput = document.getElementById('guestbook-guest-name');
  var emailInput = document.getElementById('guestbook-guest-email');
  var bodyInput = document.getElementById('guestbook-body');
  var hiddenPwd = document.getElementById('guestbook-hidden-password');
  var confirmName = document.getElementById('guestbook-confirm-name');
  var confirmEmail = document.getElementById('guestbook-confirm-email');
  var confirmPwd = document.getElementById('guestbook-confirm-password');
  var confirmSubmit = document.getElementById('guestbook-confirm-submit');
  var submitting = false;

  function csrfToken() {
    var el = form.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function showModal(modal) {
    if (!modal) return;
    modal.hidden = false;
  }

  function hideModal(modal) {
    if (!modal) return;
    modal.hidden = true;
  }

  function setSubmitting(on) {
    submitting = on;
    if (!confirmSubmit) return;
    confirmSubmit.disabled = on;
    confirmSubmit.textContent = on ? '提交中…' : '确认提交';
  }

  [confirmModal, resultModal].forEach(function (modal) {
    if (!modal) return;
    var backdrop = modal.querySelector('.yc-notice-backdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function () {
        if (!submitting) hideModal(modal);
      });
    }
  });

  var cancelBtn = document.getElementById('guestbook-confirm-cancel');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', function () {
      if (!submitting) hideModal(confirmModal);
    });
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    if (confirmName && nameInput) {
      confirmName.value = nameInput.value || '';
    } else if (confirmName) {
      confirmName.value = '';
    }
    if (confirmEmail && emailInput) {
      confirmEmail.value = emailInput.value || '';
    }
    if (confirmPwd) confirmPwd.value = '';
    showModal(confirmModal);
  });

  if (confirmSubmit) {
    confirmSubmit.addEventListener('click', function () {
      if (submitting) return;

      if (nameInput && confirmName) nameInput.value = confirmName.value;
      if (emailInput && confirmEmail) emailInput.value = confirmEmail.value;
      if (hiddenPwd && confirmPwd) hiddenPwd.value = confirmPwd.value;

      setSubmitting(true);
      var idemKey = '';
      if (window.YcIdempotency && typeof window.YcIdempotency.newKey === 'function') {
        idemKey = window.YcIdempotency.newKey();
      }
      var fd = new FormData(form);
      if (window.YcIdempotency && typeof window.YcIdempotency.applyToFormData === 'function') {
        window.YcIdempotency.applyToFormData(fd, idemKey);
      }
      var headers = {
        'X-YC-Guestbook': '1',
        'X-CSRFToken': csrfToken(),
        Accept: 'application/json',
      };
      if (window.YcIdempotency && typeof window.YcIdempotency.applyToHeaders === 'function') {
        headers = window.YcIdempotency.applyToHeaders(headers, idemKey);
      }
      fetch(form.action, {
        method: 'POST',
        body: fd,
        headers: headers,
        credentials: 'same-origin',
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          setSubmitting(false);
          hideModal(confirmModal);
          if (!result.ok || !result.data.ok) {
            var err = (result.data && result.data.error) || '提交失败，请稍后再试';
            alert(err);
            return;
          }
          var data = result.data;
          var codeEl = document.getElementById('guestbook-result-code');
          var titleEl = document.getElementById('guestbook-result-title');
          var msgEl = document.getElementById('guestbook-result-msg');
          if (codeEl) codeEl.value = data.public_code || '';
          if (titleEl) {
            titleEl.textContent = data.result_title || data.message || '留言已提交';
          }
          if (msgEl) {
            msgEl.textContent = data.result_message || '请复制保存留言编号，以便日后查看回复。';
          }
          if (bodyInput) bodyInput.value = '';
          showModal(resultModal);
        })
        .catch(function () {
          setSubmitting(false);
          hideModal(confirmModal);
          alert('网络异常，请检查网络后重试');
        });
    });
  }

  var copyBtn = document.getElementById('guestbook-copy-code');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var codeEl = document.getElementById('guestbook-result-code');
      if (!codeEl || !codeEl.value) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(codeEl.value);
      } else {
        codeEl.select();
        document.execCommand('copy');
      }
      copyBtn.textContent = '已复制';
      setTimeout(function () {
        copyBtn.textContent = '复制';
      }, 1500);
    });
  }

  var resultClose = document.getElementById('guestbook-result-close');
  if (resultClose) {
    resultClose.addEventListener('click', function () {
      hideModal(resultModal);
    });
  }
})();
