/**
 * 野草全站提示弹窗（成功 / 警告 / 错误）
 * - 页面加载时自动展示 Django messages 与 YC_NOTICE_BOOT
 * - 其它脚本可调用 window.YcNotice.show({ level, text, mustAck })
 */
(function () {
    var LEVELS = {
        ok: { icon: '✅', cls: 'is-ok', defaultAck: false },
        success: { icon: '✅', cls: 'is-ok', defaultAck: false },
        warning: { icon: '⚠️', cls: 'is-warn', defaultAck: true },
        warn: { icon: '⚠️', cls: 'is-warn', defaultAck: true },
        error: { icon: '⚠️', cls: 'is-error', defaultAck: true },
    };

    var modal = null;
    var textEl = null;
    var iconEl = null;
    var boxEl = null;
    var closeBtn = null;
    var onClose = null;

    function normLevel(level) {
        var key = (level || 'ok').toLowerCase();
        return LEVELS[key] ? key : 'ok';
    }

    function ensureModal() {
        if (modal) return modal;
        modal = document.getElementById('yc-notice-modal');
        if (!modal) return null;
        textEl = modal.querySelector('.yc-notice-text');
        iconEl = modal.querySelector('.yc-notice-icon');
        boxEl = modal.querySelector('.yc-notice-box');
        closeBtn = modal.querySelector('.yc-notice-close');
        var backdrop = modal.querySelector('.yc-notice-backdrop');
        function close() {
            modal.hidden = true;
            if (typeof onClose === 'function') {
                var fn = onClose;
                onClose = null;
                fn();
            }
        }
        if (closeBtn) closeBtn.addEventListener('click', close);
        if (backdrop) backdrop.addEventListener('click', close);
        return modal;
    }

    function show(opts) {
        var m = ensureModal();
        if (!m || !textEl || !boxEl) return;
        var level = normLevel(opts && opts.level);
        var meta = LEVELS[level] || LEVELS.ok;
        var mustAck = opts && typeof opts.mustAck === 'boolean'
            ? opts.mustAck
            : meta.defaultAck;
        textEl.textContent = (opts && opts.text) || '';
        if (iconEl) iconEl.textContent = meta.icon;
        boxEl.classList.remove('is-ok', 'is-warn', 'is-error');
        boxEl.classList.add(meta.cls);
        if (closeBtn) {
            closeBtn.textContent = mustAck ? '知道了' : '关闭';
        }
        onClose = opts && opts.onClose ? opts.onClose : null;
        m.hidden = false;
        if (!mustAck) {
            var delay = Number(opts && opts.autoCloseMs) || 3200;
            window.setTimeout(function () {
                if (!m.hidden) {
                    m.hidden = true;
                    if (typeof onClose === 'function') {
                        var fn = onClose;
                        onClose = null;
                        fn();
                    }
                }
            }, delay);
        }
    }

    function showQueue(items) {
        if (!items || !items.length) return;
        var idx = 0;
        function next() {
            if (idx >= items.length) return;
            var item = items[idx++];
            show({
                level: item.level,
                text: item.text,
                mustAck: item.mustAck,
                onClose: next,
            });
        }
        next();
    }

    function readBoot() {
        var items = [];
        var bootEl = document.getElementById('yc-notice-boot');
        if (bootEl && bootEl.textContent) {
            try {
                var boot = JSON.parse(bootEl.textContent);
                if (Array.isArray(boot)) items = items.concat(boot);
            } catch (e) { /* 忽略 */ }
        }
        var msgEl = document.getElementById('yc-notice-messages');
        if (msgEl && msgEl.textContent) {
            try {
                var msgs = JSON.parse(msgEl.textContent);
                if (Array.isArray(msgs)) items = items.concat(msgs);
            } catch (e) { /* 忽略 */ }
        }
        return items;
    }

    function init() {
        ensureModal();
        var items = readBoot();
        if (items.length) showQueue(items);
    }

    window.YcNotice = { show: show, showQueue: showQueue };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
