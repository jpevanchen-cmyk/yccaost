/**
 * 野草 Panel 静默刷新（进度 80 · 全站共用核心）
 * - 标记 data-yc-panel="容器 id" 的表单走 Ajax，不整页刷新
 * - 清单下拉 data-yc-panel-picker 换清单（方案甲：replaceState，不 reload）
 * - 无脚本时原 form POST / GET 仍可用
 */
(function () {
    var HEADER = 'YecaoPanel';

    function csrfToken(form) {
        if (form) {
            var input = form.querySelector('[name=csrfmiddlewaretoken]');
            if (input && input.value) return input.value;
        }
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function showMessage(level, text) {
        if (!text) return;
        if (window.YcNotice && typeof window.YcNotice.show === 'function') {
            window.YcNotice.show({ level: level || 'ok', text: text });
            return;
        }
        window.alert(text);
    }

    function resolvePanelEl(panelId) {
        if (!panelId) return null;
        return document.getElementById(panelId);
    }

    function afterPanelReplace(panelEl) {
        bindPanelForms(panelEl);
        bindProfilePickers(panelEl);
        if (window.ycSellerUnsavedGuard && window.ycSellerUnsavedGuard.registerForm) {
            panelEl.querySelectorAll('form[data-unsaved-guard]').forEach(function (form) {
                window.ycSellerUnsavedGuard.registerForm(form);
            });
        }
    }

    function applyPanelHtml(panelEl, html) {
        if (!panelEl || html === undefined || html === null) return;
        panelEl.innerHTML = html;
        afterPanelReplace(panelEl);
    }

    function parsePanelResponse(response) {
        return response.text().then(function (text) {
            var data = null;
            if (text) {
                try {
                    data = JSON.parse(text);
                } catch (e) {
                    data = null;
                }
            }
            if (response.status === 403) {
                throw new Error('安全码失效或未带上，请刷新页面后重试');
            }
            if (!response.ok || !data || data.ok !== true) {
                if (data && data.message) {
                    throw new Error(data.message);
                }
                if (!response.ok) {
                    throw new Error('服务器未返回有效结果，请稍后再试');
                }
                throw new Error('操作未成功，请稍后再试');
            }
            return data;
        });
    }

    function bindPanelForms(root) {
        var scope = root || document;
        scope.querySelectorAll('form[data-yc-panel]').forEach(function (form) {
            if (form.dataset.ycPanelBound === '1') return;
            form.dataset.ycPanelBound = '1';
            form.addEventListener('submit', onFormSubmit);
        });
    }

    function onFormSubmit(e) {
        var form = e.target;
        if (!form || !form.getAttribute('data-yc-panel')) return;
        var panelId = form.getAttribute('data-yc-panel');
        var panelEl = resolvePanelEl(panelId);
        if (!panelEl) return;

        e.preventDefault();
        var submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn && submitBtn.disabled) return;
        if (submitBtn) submitBtn.disabled = true;

        var postUrl = form.getAttribute('action') || window.location.href;
        var headers = { 'X-Requested-With': HEADER };
        var token = csrfToken(form);
        if (token) headers['X-CSRFToken'] = token;

        fetch(postUrl, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
            headers: headers,
        })
            .then(parsePanelResponse)
            .then(function (data) {
                applyPanelHtml(panelEl, data.html);
                if (data.message) {
                    showMessage('ok', data.message);
                }
                if (submitBtn) submitBtn.disabled = false;
            })
            .catch(function (err) {
                var level = 'error';
                var mustAck = true;
                if (err.message && (
                    err.message.indexOf('未结束订单') >= 0
                    || err.message.indexOf('正在使用中') >= 0
                )) {
                    level = 'warning';
                }
                if (window.YcNotice && typeof window.YcNotice.show === 'function') {
                    window.YcNotice.show({ level: level, text: err.message || '操作未成功，请稍后再试', mustAck: mustAck });
                } else {
                    window.alert(err.message || '操作未成功，请稍后再试');
                }
                if (submitBtn) submitBtn.disabled = false;
            });
    }

    /** 清单下拉换 Panel（方案甲：只换 HTML + replaceState） */
    function switchProfile(profileId, targetUrl) {
        var panelId = 'menu-panel-body';
        var panelEl = resolvePanelEl(panelId);
        if (!panelEl) return false;
        var urlObj = new URL(targetUrl, window.location.href);
        var fetchUrl = urlObj.pathname + (urlObj.search ? urlObj.search : '');
        fetch(fetchUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': HEADER },
        })
            .then(parsePanelResponse)
            .then(function (data) {
                applyPanelHtml(panelEl, data.html);
                var historyUrl = urlObj.pathname + urlObj.search + urlObj.hash;
                window.history.replaceState(null, '', historyUrl);
                var fold = document.getElementById('menu-panel');
                if (fold && typeof fold.open === 'boolean') fold.open = true;
            })
            .catch(function (err) {
                showMessage('error', err.message || '切换清单未成功，请稍后再试');
            });
        return true;
    }

    function bindProfilePickers(root) {
        var scope = root || document;
        scope.querySelectorAll('[data-yc-panel-picker]').forEach(function (sel) {
            if (sel.dataset.ycPanelPickerBound === '1') return;
            sel.dataset.ycPanelPickerBound = '1';
            /* change 仍由 seller_unsaved_guard.js 统一处理（含未保存拦截） */
        });
    }

    function tryNavigateProfileSwitch(url) {
        try {
            var target = new URL(url, window.location.href);
            var cur = new URL(window.location.href);
            if (target.pathname !== cur.pathname) return false;
            if (!target.searchParams.has('profile')) return false;
            return switchProfile(target.searchParams.get('profile'), target.toString());
        } catch (e) {
            return false;
        }
    }

    function init() {
        bindPanelForms(document);
        bindProfilePickers(document);
    }

    window.YcaoPanel = {
        bind: bindPanelForms,
        refreshHeader: HEADER,
        switchProfile: switchProfile,
        tryNavigateProfileSwitch: tryNavigateProfileSwitch,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
