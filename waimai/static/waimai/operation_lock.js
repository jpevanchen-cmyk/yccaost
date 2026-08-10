(function () {
    if (!window.YC_OPERATION_LOCK || !window.YC_OPERATION_LOCK.enabled) {
        return;
    }
    var touchUrl = window.YC_OPERATION_LOCK.touchUrl;
    var csrf = window.YC_OPERATION_LOCK.csrfToken;
    if (!touchUrl) {
        return;
    }
    var lastTouch = 0;
    function touchActivity() {
        var now = Date.now();
        if (now - lastTouch < 30000) {
            return;
        }
        lastTouch = now;
        var body = 'csrfmiddlewaretoken=' + encodeURIComponent(csrf || '');
        fetch(touchUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body,
        }).catch(function () {});
    }
    ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'].forEach(function (ev) {
        document.addEventListener(ev, touchActivity, { passive: true });
    });
    setInterval(touchActivity, 60000);
})();
