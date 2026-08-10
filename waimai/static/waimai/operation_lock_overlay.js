(function () {
    var overlay = document.getElementById('yc-operation-lock-overlay');
    if (!overlay) {
        return;
    }
    var form = overlay.querySelector('.yc-operation-lock-form');
    var errEl = overlay.querySelector('.yc-operation-lock-error');
    var unlockUrl = overlay.dataset.unlockUrl;
    var csrf = overlay.dataset.csrfToken || '';
    if (!form || !unlockUrl) {
        return;
    }
    form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var pinInput = form.querySelector('[name=pin]');
        var pin = pinInput ? pinInput.value.trim() : '';
        if (!pin) {
            if (errEl) {
                errEl.textContent = '请输入 PIN';
                errEl.hidden = false;
            }
            return;
        }
        if (errEl) {
            errEl.hidden = true;
            errEl.textContent = '';
        }
        var body = 'pin=' + encodeURIComponent(pin)
            + '&ajax=1'
            + '&csrfmiddlewaretoken=' + encodeURIComponent(csrf);
        fetch(unlockUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: body,
        })
            .then(function (resp) {
                return resp.json().then(function (data) {
                    return { ok: resp.ok, data: data };
                });
            })
            .then(function (result) {
                if (result.ok && result.data && result.data.ok) {
                    window.location.reload();
                    return;
                }
                if (errEl) {
                    errEl.textContent = (result.data && result.data.message) || 'PIN 不正确';
                    errEl.hidden = false;
                }
            })
            .catch(function () {
                if (errEl) {
                    errEl.textContent = '解锁失败，请检查网络后重试';
                    errEl.hidden = false;
                }
            });
    });
})();
