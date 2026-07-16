/**
 * 登录会话守护：
 * 1. 关页尽量拦截提示（站内跳转不拦）
 * 2. 真正离开时尽量发退出（站内跳转不发）
 * 3. 约 5 分钟无报平安则失效（心跳 + 服务端会话寿命）
 * 4. 超过 15 分钟无操作则退出
 */
(function () {
    var cfg = window.YC_SESSION_GUARD;
    if (!cfg || !cfg.enabled) return;

    var heartbeatUrl = cfg.heartbeatUrl || '';
    var beaconUrl = cfg.beaconUrl || '';
    var csrfToken = cfg.csrfToken || '';
    var channel = cfg.channel || 'all';
    var heartbeatMs = (cfg.heartbeatSeconds || 60) * 1000;
    var idleMs = (cfg.idleSeconds || 900) * 1000;
    var leaving = false;
    var lastActivity = Date.now();
    var warnOnLeave = true;
    var allowUnloadLogout = true;
    var unloadBeaconSent = false;

    function getCookie(name) {
        var m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)'));
        return m ? decodeURIComponent(m[1]) : '';
    }

    function resolveCsrf() {
        return csrfToken || getCookie('csrftoken') || '';
    }

    function postForm(url, extra) {
        if (!url) return;
        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', resolveCsrf());
        fd.append('channel', channel);
        if (extra) {
            Object.keys(extra).forEach(function (k) {
                fd.append(k, extra[k]);
            });
        }
        if (navigator.sendBeacon) {
            try {
                navigator.sendBeacon(url, fd);
                return;
            } catch (e) { /* 继续用 fetch */ }
        }
        try {
            fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', keepalive: true });
        } catch (e2) { /* 关页时可能失败，靠心跳超时兜底 */ }
    }

    function markInternalNavigation() {
        // 站内点链接 / 提交表单：不要弹离开提示，也不要退出登录
        warnOnLeave = false;
        allowUnloadLogout = false;
    }

    function heartbeat(asActivity) {
        if (!heartbeatUrl || leaving) return;
        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', resolveCsrf());
        fd.append('channel', channel);
        if (asActivity) fd.append('activity', '1');
        fetch(heartbeatUrl, { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.logout) {
                    leaving = true;
                    warnOnLeave = false;
                    allowUnloadLogout = false;
                    window.location.reload();
                }
            })
            .catch(function () { /* 网络抖动忽略 */ });
    }

    function markActivity() {
        lastActivity = Date.now();
    }

    function checkIdle() {
        if (leaving) return;
        if (Date.now() - lastActivity >= idleMs) {
            leaving = true;
            warnOnLeave = false;
            allowUnloadLogout = false;
            unloadBeaconSent = true;
            postForm(beaconUrl, {});
            setTimeout(function () {
                window.location.reload();
            }, 200);
        }
    }

    function onLeaveAttempt(e) {
        if (!warnOnLeave || leaving) return;
        e.preventDefault();
        e.returnValue = '';
        return '';
    }

    function sendUnloadLogout(e) {
        if (e && e.persisted) return;
        if (!allowUnloadLogout) return;
        if (unloadBeaconSent || leaving) return;
        unloadBeaconSent = true;
        leaving = true;
        warnOnLeave = false;
        postForm(beaconUrl, {});
    }

    document.addEventListener('click', function (e) {
        var a = e.target && e.target.closest ? e.target.closest('a') : null;
        if (!a || !a.href) return;
        try {
            var url = new URL(a.href, window.location.href);
            if (url.origin === window.location.origin) {
                markInternalNavigation();
            }
        } catch (err) { /* 忽略 */ }
    }, true);

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form) return;
        markInternalNavigation();
        if (form.action && String(form.action).indexOf('logout') !== -1) {
            leaving = true;
            unloadBeaconSent = true;
        }
    }, true);

    ['click', 'keydown', 'touchstart', 'mousemove', 'scroll'].forEach(function (evt) {
        window.addEventListener(evt, markActivity, { passive: true });
    });

    window.addEventListener('beforeunload', onLeaveAttempt);
    window.addEventListener('pagehide', sendUnloadLogout);

    markActivity();
    heartbeat(true);
    setInterval(function () { heartbeat(false); }, heartbeatMs);
    setInterval(checkIdle, 15000);
})();
