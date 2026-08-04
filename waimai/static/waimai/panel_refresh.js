/**
 * 野草 Panel 静默刷新（进度 80 · 全站共用核心）
 * - 标记 data-yc-panel="容器 id" 的表单走 Ajax，不整页刷新
 * - 清单下拉 data-yc-panel-picker 换清单（方案甲：replaceState，不 reload）
 * - 现金月份 data-yc-cash-month-picker 换汇总（同样不 reload）
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
        bindCashMonthPickers(panelEl);
        if (window.ycRebindSellerPanelFold) {
            window.ycRebindSellerPanelFold(panelEl);
        }
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

    // 被点击的提交按钮名不会自动进 FormData，需手动补上（兜底；模板优先用 hidden 字段）
    var lastSubmitterByForm = new WeakMap();

    function appendFormSubmitter(fd, submitter) {
        if (!submitter || !submitter.name || submitter.disabled) return;
        if (submitter.type === 'submit' || submitter.type === 'image' ||
            (submitter.tagName === 'BUTTON' && !submitter.type)) {
            fd.set(submitter.name, submitter.value || '1');
        }
    }

    function resolveSubmitter(form, explicit) {
        if (explicit && explicit.name) return explicit;
        var clicked = lastSubmitterByForm.get(form);
        if (clicked && clicked.name) return clicked;
        var named = form.querySelectorAll(
            'button[type="submit"][name], input[type="submit"][name], button[name]:not([type])'
        );
        if (named.length === 1) return named[0];
        return explicit || null;
    }

    function trackPanelFormClicks(form) {
        form.addEventListener('click', function (ev) {
            var btn = ev.target && ev.target.closest
                ? ev.target.closest('button, input[type="submit"], input[type="image"]')
                : null;
            if (!btn || !form.contains(btn)) return;
            if (btn.type === 'submit' || btn.type === 'image' ||
                (btn.tagName === 'BUTTON' && (!btn.type || btn.type === 'submit'))) {
                lastSubmitterByForm.set(form, btn);
            }
        }, true);
    }

    function bindPanelForms(root) {
        var scope = root || document;
        scope.querySelectorAll('form[data-yc-panel]').forEach(function (form) {
            if (form.dataset.ycPanelBound === '1') return;
            form.dataset.ycPanelBound = '1';
            trackPanelFormClicks(form);
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
        var submitter = resolveSubmitter(form, e.submitter || null);
        lastSubmitterByForm.delete(form);
        var submitBtn = submitter || form.querySelector('button[type="submit"], input[type="submit"]');
        if (submitBtn && submitBtn.disabled) return;
        if (submitBtn) submitBtn.disabled = true;

        var postUrl = form.getAttribute('action') || window.location.href;
        var headers = { 'X-Requested-With': HEADER };
        var token = csrfToken(form);
        if (token) headers['X-CSRFToken'] = token;

        var fd = new FormData(form);
        appendFormSubmitter(fd, submitter);

        fetch(postUrl, {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
            headers: headers,
        })
            .then(parsePanelResponse)
            .then(function (data) {
                applyPanelHtml(panelEl, data.html);
                if (data.message) {
                    showMessage('ok', data.message);
                }
                if (data.extra && data.extra.scroll_to) {
                    var anchor = document.getElementById(data.extra.scroll_to);
                    if (anchor) {
                        if (anchor.tagName === 'DETAILS') {
                            anchor.open = true;
                        } else {
                            var fold = anchor.closest('details');
                            if (fold) fold.open = true;
                        }
                        anchor.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }
                } else if (data.scroll_to) {
                    var anchor2 = document.getElementById(data.scroll_to);
                    if (anchor2) {
                        anchor2.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }
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

    /** GET 换 Panel（清单下拉、现金月份等：只换 HTML + replaceState） */
    function switchPanelGet(panelId, targetUrl, options) {
        options = options || {};
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
                if (options.openFoldId) {
                    var fold = document.getElementById(options.openFoldId);
                    if (fold && typeof fold.open === 'boolean') fold.open = true;
                }
                if (window.ycRebindSellerPanelFold) {
                    window.ycRebindSellerPanelFold(panelEl);
                }
            })
            .catch(function (err) {
                showMessage('error', err.message || '切换未成功，请稍后再试');
            });
        return true;
    }

    /** 清单下拉换 Panel（方案甲：只换 HTML + replaceState） */
    function switchProfile(profileId, targetUrl) {
        return switchPanelGet('menu-panel-body', targetUrl, { openFoldId: 'menu-panel' });
    }

    /** 现金管理 · 汇总月份下拉（不整页 reload） */
    function bindCashMonthPickers(root) {
        var scope = root || document;
        scope.querySelectorAll('[data-yc-cash-month-picker]').forEach(function (sel) {
            if (sel.dataset.ycCashMonthPickerBound === '1') return;
            sel.dataset.ycCashMonthPickerBound = '1';
            sel.addEventListener('change', function () {
                var panelId = sel.getAttribute('data-yc-cash-month-picker');
                if (!panelId) return;
                var u = new URL(window.location.href);
                u.searchParams.set('cash_month', sel.value);
                switchPanelGet(panelId, u.toString(), { openFoldId: 'cash-manage-daily' });
            });
        });
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
        bindCashMonthPickers(document);
    }

    window.YcaoPanel = {
        bind: bindPanelForms,
        refreshHeader: HEADER,
        switchProfile: switchProfile,
        switchPanelGet: switchPanelGet,
        tryNavigateProfileSwitch: tryNavigateProfileSwitch,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
