/* 注册页：年龄二选一；须先点开并阅读隐私条款 */
(function () {
  var form = document.querySelector('[data-yc-tour="buyer-register-form"]');
  if (!form) return;
  var adult = document.getElementById('id_age_adult');
  var minor = document.getElementById('id_age_minor');
  var agree = document.getElementById('id_agree_privacy');
  var openLink = document.getElementById('privacy-policy-open');
  var submitBtn = document.getElementById('register-submit');
  var viewed = form.getAttribute('data-privacy-viewed') === '1';

  function syncAge() {
    if (!adult || !minor) return;
    if (adult.checked) {
      minor.checked = false;
      minor.disabled = true;
    } else {
      minor.disabled = false;
    }
    if (minor.checked) {
      adult.checked = false;
      adult.disabled = true;
    } else if (!adult.checked) {
      adult.disabled = false;
    }
  }

  function canSubmit() {
    var ageOk = !!(adult && minor && (adult.checked ^ minor.checked));
    var agreeOk = !!(agree && agree.checked);
    return agreeOk && ageOk;
  }

  function refreshSubmit() {
    if (!submitBtn) return;
    submitBtn.disabled = !canSubmit();
  }

  if (adult) adult.addEventListener('change', function () { syncAge(); refreshSubmit(); });
  if (minor) minor.addEventListener('change', function () { syncAge(); refreshSubmit(); });
  if (agree) agree.addEventListener('change', refreshSubmit);

  if (openLink) {
    openLink.addEventListener('click', function (e) {
      var url = openLink.getAttribute('href');
      if (url) {
        fetch(url, { credentials: 'same-origin' }).catch(function () { /* 打开新页仍会记一次 */ });
        /* 用程序开新页，方便条款页「关闭本页」能关掉 */
        var opened = window.open(url, '_blank');
        if (opened) e.preventDefault();
      }
      viewed = true;
      form.setAttribute('data-privacy-viewed', '1');
      refreshSubmit();
    });
  }

  syncAge();
  refreshSubmit();
})();
