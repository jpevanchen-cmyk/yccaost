/* 待支付倒计时：只显示服务器算好的剩余秒数，到 0 灰掉按钮并刷新 */
(function () {
    var root = document.querySelector('[data-yc-pay-countdown]');
    if (!root) return;
    var remain = parseInt(root.getAttribute('data-remain-sec') || '0', 10);
    var label = root.querySelector('[data-yc-pay-countdown-label]');
    var lockSel = root.getAttribute('data-lock-selector') || '';
    function pad(n) {
        return n < 10 ? '0' + n : String(n);
    }
    function fmt(sec) {
        if (sec < 0) sec = 0;
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        return m + '分' + pad(s) + '秒';
    }
    function lockPay() {
        if (!lockSel) return;
        document.querySelectorAll(lockSel).forEach(function (el) {
            if (el.tagName === 'A') {
                el.classList.add('btn-disabled');
                el.setAttribute('aria-disabled', 'true');
                el.addEventListener('click', function (ev) { ev.preventDefault(); });
                el.style.pointerEvents = 'none';
                el.style.opacity = '0.5';
            } else {
                el.disabled = true;
            }
        });
    }
    function tick() {
        if (label) label.textContent = '请在 ' + fmt(remain) + ' 内完成支付';
        if (remain <= 0) {
            lockPay();
            if (label) label.textContent = '支付时限已到';
            window.setTimeout(function () { window.location.reload(); }, 400);
            return;
        }
        remain -= 1;
        window.setTimeout(tick, 1000);
    }
    tick();
})();
