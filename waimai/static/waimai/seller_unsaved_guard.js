/**
 * 卖家后台：未保存修改统一拦截（全站共用，各页表单仅加 data-unsaved-guard）
 */
(function () {
    var STORAGE_KEY = 'yc_seller_pending_nav';
    var modal = null;
    var pendingUrl = '';
    var pendingOnCancel = null;
    var lastDirtyForm = null;

    function serializeForm(form) {
        var fd = new FormData(form);
        var parts = [];
        fd.forEach(function (value, key) {
            if (key === 'csrfmiddlewaretoken') return;
            parts.push(key + '=' + String(value));
        });
        parts.sort();
        return parts.join('&');
    }

    function setDirty(form, dirty) {
        if (dirty) {
            form.setAttribute('data-unsaved-dirty', '1');
            lastDirtyForm = form;
        } else {
            form.removeAttribute('data-unsaved-dirty');
            if (lastDirtyForm === form) lastDirtyForm = null;
        }
    }

    function checkDirty(form) {
        var initial = form.getAttribute('data-unsaved-initial') || '';
        setDirty(form, serializeForm(form) !== initial);
    }

    function getDirtyForm() {
        if (lastDirtyForm && lastDirtyForm.getAttribute('data-unsaved-dirty') === '1') {
            return lastDirtyForm;
        }
        return document.querySelector('form[data-unsaved-dirty="1"]');
    }

    function initGuardedForm(form) {
        form.setAttribute('data-unsaved-initial', serializeForm(form));
        form.addEventListener('input', function () { checkDirty(form); });
        form.addEventListener('change', function () { checkDirty(form); });
        form.addEventListener('submit', function () {
            form.setAttribute('data-unsaved-initial', serializeForm(form));
            setDirty(form, false);
        });
    }

    function ensureModal() {
        if (modal) return modal;
        modal = document.getElementById('seller-unsaved-modal');
        if (!modal) return null;

        modal.querySelector('[data-unsaved-action="save"]').addEventListener('click', onSave);
        modal.querySelector('[data-unsaved-action="discard"]').addEventListener('click', onDiscard);
        modal.querySelector('[data-unsaved-action="cancel"]').addEventListener('click', onCancel);
        modal.querySelector('.seller-unsaved-backdrop').addEventListener('click', onCancel);
        return modal;
    }

    function showModal() {
        var m = ensureModal();
        if (m) m.hidden = false;
    }

    function hideModal() {
        if (modal) modal.hidden = true;
        pendingUrl = '';
        pendingOnCancel = null;
    }

    function navigateAway(url) {
        if (url === '__back__') {
            window.history.back();
            return;
        }
        window.location.href = url;
    }

    function onSave() {
        var form = getDirtyForm();
        var url = pendingUrl;
        hideModal();
        if (!form || !url) return;
        try {
            sessionStorage.setItem(STORAGE_KEY, url);
        } catch (e) { /* 忽略 */ }
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
        } else {
            form.submit();
        }
    }

    function onDiscard() {
        var url = pendingUrl;
        document.querySelectorAll('form[data-unsaved-guard]').forEach(function (f) {
            setDirty(f, false);
        });
        hideModal();
        if (url) navigateAway(url);
    }

    function onCancel() {
        if (typeof pendingOnCancel === 'function') pendingOnCancel();
        hideModal();
    }

    function confirmLeave(url, onCancel) {
        if (!getDirtyForm()) {
            navigateAway(url);
            return;
        }
        pendingUrl = url;
        pendingOnCancel = onCancel || null;
        showModal();
    }

    function shouldGuardHref(href) {
        if (!href || href.indexOf('javascript:') === 0 || href === '#') return false;
        try {
            var target = new URL(href, window.location.href);
            var cur = new URL(window.location.href);
            if (target.pathname !== cur.pathname) return true;
            if (target.search !== cur.search) return true;
            if (target.hash !== cur.hash) return true;
        } catch (e) {
            return true;
        }
        return false;
    }

    function isSellerNavLink(el) {
        return el.closest('.seller-tabs-desktop, .seller-tabs-mobile, .page-back-btn, .seller-dish-row a');
    }

    function bindNavigation() {
        document.addEventListener('click', function (e) {
            var a = e.target.closest('a[href]');
            if (!a || a.hasAttribute('data-unsaved-skip')) return;
            if (!isSellerNavLink(a) && !a.closest('.seller-dish-row')) return;
            var href = a.getAttribute('href');
            if (!shouldGuardHref(href)) return;
            if (!getDirtyForm()) return;
            e.preventDefault();
            e.stopPropagation();
            confirmLeave(a.href);
        }, true);

        var historyBtn = document.querySelector('.page-back-btn--history');
        if (historyBtn) {
            historyBtn.addEventListener('click', function (e) {
                if (!getDirtyForm()) return;
                e.preventDefault();
                confirmLeave('__back__');
            });
        }

        var menuSel = document.getElementById('menu-profile-select');
        if (menuSel) {
            var lastVal = menuSel.value;
            menuSel.addEventListener('focus', function () { lastVal = menuSel.value; });
            menuSel.addEventListener('change', function () {
                var u = new URL(window.location.href);
                u.searchParams.set('profile', menuSel.value);
                u.searchParams.delete('edit');
                u.hash = 'menu-panel';
                var target = u.toString();
                if (!getDirtyForm()) {
                    window.location.href = target;
                    return;
                }
                menuSel.value = lastVal;
                confirmLeave(target, function () { menuSel.value = lastVal; });
            });
        }

        window.addEventListener('beforeunload', function (e) {
            if (!getDirtyForm()) return;
            e.preventDefault();
            e.returnValue = '';
        });
    }

    function resumePendingNavigation() {
        var pending = null;
        try {
            pending = sessionStorage.getItem(STORAGE_KEY);
            if (pending) sessionStorage.removeItem(STORAGE_KEY);
        } catch (e) { /* 忽略 */ }
        if (!pending) return;
        setTimeout(function () { navigateAway(pending); }, 0);
    }

    function init() {
        document.querySelectorAll('form[data-unsaved-guard]').forEach(initGuardedForm);
        ensureModal();
        bindNavigation();
        resumePendingNavigation();
    }

    window.ycSellerUnsavedGuard = {
        confirmLeave: confirmLeave,
        isDirty: function () { return !!getDirtyForm(); },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
