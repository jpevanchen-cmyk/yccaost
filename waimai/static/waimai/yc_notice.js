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
    /** 同页刷新时用于识别「这批提示已经弹过」 */
    var FP_STORAGE_KEY = 'yc_notice_fp';

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

    /** 从页面嵌入的 JSON 读取待弹提示 */
    function readItemsFromEl(el) {
        if (!el || !el.textContent) return [];
        try {
            var data = JSON.parse(el.textContent);
            if (Array.isArray(data)) return data;
            if (data && Array.isArray(data.items)) return data.items;
        } catch (e) { /* 忽略 */ }
        return [];
    }

    function readBoot() {
        var items = [];
        items = items.concat(readItemsFromEl(document.getElementById('yc-notice-boot')));
        items = items.concat(readItemsFromEl(document.getElementById('yc-notice-messages')));
        return items;
    }

    /** 弹过后立刻删掉嵌入数据，避免缓存页再次读取 */
    function clearBootSources() {
        ['yc-notice-messages', 'yc-notice-boot'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.parentNode) {
                el.parentNode.removeChild(el);
            }
        });
    }

    function bootFingerprint(items) {
        var path = window.location.pathname + window.location.search;
        try {
            return path + '|' + JSON.stringify(items);
        } catch (e) {
            return path + '|' + String(items.length);
        }
    }

    /** 是否为浏览器刷新（非保存后跳转） */
    function isPageReload() {
        try {
            var nav = performance.getEntriesByType('navigation')[0];
            return nav && nav.type === 'reload';
        } catch (e) {
            return false;
        }
    }

    /** 刷新且与上次已弹内容相同 → 不再弹 */
    function shouldSkipReplay(fingerprint) {
        if (!isPageReload()) return false;
        try {
            return sessionStorage.getItem(FP_STORAGE_KEY) === fingerprint;
        } catch (e) {
            return false;
        }
    }

    function rememberFingerprint(fingerprint) {
        try {
            sessionStorage.setItem(FP_STORAGE_KEY, fingerprint);
        } catch (e) { /* 隐私模式等忽略 */ }
    }

    function init() {
        ensureModal();
        var items = readBoot();
        clearBootSources();
        if (!items.length) return;
        var fp = bootFingerprint(items);
        if (shouldSkipReplay(fp)) return;
        rememberFingerprint(fp);
        showQueue(items);
    }

    window.YcNotice = { show: show, showQueue: showQueue };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
