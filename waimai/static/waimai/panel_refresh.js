/**
 * 野草 Panel 静默刷新（进度 80 · 全站共用核心）
 * - 标记 data-yc-panel="容器 id" 的表单走 Ajax，不整页刷新
 * - 清单下拉 data-yc-panel-picker 换清单（方案甲：replaceState，不 reload）
 * - 现金月份 data-yc-cash-month-picker 换汇总（同样不 reload）
 * - 等待逻辑：等本次 HTTP **服务器响应**（非 navigator.onLine / WiFi 恢复）
 * - 0 秒起全屏锁；5 秒转圈；20 秒 Abort；超时后「再试一次」复用同一幂等编号（幂等第 12 步）
 * - 无脚本时原 form POST / GET 仍可用
 */
(function () {
    var HEADER = 'YecaoPanel';
    var SHOP_CART_PANEL_ID = 'shop-cart-shell';
    var MENU_CATALOG_PANEL_ID = 'menu-panel-body';
    var WORKBENCH_PANEL_IDS = [
        'work-orders-panel-body',
        'work-kitchen-panel-body',
        'work-waiter-panel-body',
        'work-rider-panel-body',
        'work-cashier-panel-body',
        'work-cash-manage-panel-body',
    ];
    var SELLER_CASH_MANAGE_PANEL_ID = 'cash-manage-panel-body';
    var PANEL_WAIT_SPIN_MS = 5000;
    var PANEL_TIMEOUT_MS = 20000;
    /* 带文件上传：放宽等待（慢网传安装包可达数分钟）；与会话忙任务配合 */
    var PANEL_UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;
    var PANEL_TIMEOUT_MESSAGE = '服务器可能走丢了，请检查网络';
    var loadingOverlay = null;
    /* Panel 等待锁屏计数：并发请求时只拦一次滚动、最后一次解锁才放开 */
    var panelWaitLockCount = 0;
    var panelWaitScrollBlocker = null;
    var panelWaitKeyBlocker = null;

    /** 锁屏期间禁止滚轮/触摸滑动（不用 overflow:hidden，滚动条保持可见） */
    function blockPanelWaitWheelTouch(e) {
        e.preventDefault();
    }

    function blockPanelWaitScrollKeys(e) {
        var k = e.key;
        if (k === ' ' || k === 'PageUp' || k === 'PageDown' ||
            k === 'ArrowUp' || k === 'ArrowDown' || k === 'Home' || k === 'End') {
            e.preventDefault();
        }
    }

    function lockPanelWaitScroll() {
        if (panelWaitLockCount > 0) {
            panelWaitLockCount += 1;
            return;
        }
        panelWaitLockCount = 1;
        panelWaitScrollBlocker = blockPanelWaitWheelTouch;
        panelWaitKeyBlocker = blockPanelWaitScrollKeys;
        document.addEventListener('wheel', panelWaitScrollBlocker, { passive: false, capture: true });
        document.addEventListener('touchmove', panelWaitScrollBlocker, { passive: false, capture: true });
        document.addEventListener('keydown', panelWaitKeyBlocker, true);
        document.body.classList.add('yc-panel-wait-locked');
    }

    function unlockPanelWaitScroll() {
        if (panelWaitLockCount <= 0) {
            return;
        }
        panelWaitLockCount -= 1;
        if (panelWaitLockCount > 0) {
            return;
        }
        if (panelWaitScrollBlocker) {
            document.removeEventListener('wheel', panelWaitScrollBlocker, { capture: true });
            document.removeEventListener('touchmove', panelWaitScrollBlocker, { capture: true });
            panelWaitScrollBlocker = null;
        }
        if (panelWaitKeyBlocker) {
            document.removeEventListener('keydown', panelWaitKeyBlocker, true);
            panelWaitKeyBlocker = null;
        }
        document.body.classList.remove('yc-panel-wait-locked');
    }

    function isShopCartPanel(panelId) {
        return panelId === SHOP_CART_PANEL_ID;
    }

    function isMenuCatalogPanel(panelId) {
        return panelId === MENU_CATALOG_PANEL_ID;
    }

    function isWorkbenchPanel(panelId) {
        return WORKBENCH_PANEL_IDS.indexOf(panelId) >= 0;
    }

    function isCashManagePanel(panelId) {
        return panelId === SELLER_CASH_MANAGE_PANEL_ID
            || panelId === 'work-cash-manage-panel-body';
    }

    function isProductImageManagePanel(panelId) {
        return (panelId || '').indexOf('product-image-manage-') === 0;
    }

    function isOperatingStatusPanel(panelId) {
        return panelId === 'operating-status-panel';
    }

    function panelNeedsIdempotency(panelId) {
        return isShopCartPanel(panelId)
            || isMenuCatalogPanel(panelId)
            || isWorkbenchPanel(panelId)
            || isCashManagePanel(panelId)
            || isProductImageManagePanel(panelId)
            || isOperatingStatusPanel(panelId);
    }

    function ensureLoadingOverlay() {
        if (loadingOverlay) return loadingOverlay;
        loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'yc-panel-loading';
        loadingOverlay.setAttribute('aria-live', 'polite');
        loadingOverlay.hidden = true;
        loadingOverlay.innerHTML = '<div class="yc-panel-loading-box">'
            + '<div class="yc-panel-loading-spinner" aria-hidden="true"></div>'
            + '<p class="yc-panel-loading-text">正在读取数据…</p></div>';
        document.body.appendChild(loadingOverlay);
        return loadingOverlay;
    }

    function formDataHasUploadFiles(fd) {
        if (!fd || typeof FormData === 'undefined' || !(fd instanceof FormData)) return false;
        try {
            var it = fd.entries();
            var step = it.next();
            while (!step.done) {
                var val = step.value[1];
                if (typeof File !== 'undefined' && val instanceof File && val.size > 0) {
                    return true;
                }
                step = it.next();
            }
        } catch (e) { /* 旧环境忽略 */ }
        return false;
    }

    function formatUploadBytes(n) {
        var x = Number(n) || 0;
        if (x < 1024) return Math.round(x) + ' B';
        if (x < 1024 * 1024) return (x / 1024).toFixed(1) + ' KB';
        return (x / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function formatUploadEta(seconds) {
        var s = Math.max(0, Math.round(Number(seconds) || 0));
        if (s < 60) return s + ' 秒';
        var m = Math.floor(s / 60);
        var r = s % 60;
        if (m < 60) return m + ' 分' + (r ? r + ' 秒' : '');
        var h = Math.floor(m / 60);
        return h + ' 小时' + (m % 60) + ' 分';
    }

    /** 等待服务器 HTTP 响应：0 秒起锁屏；普通请求 5 秒转圈、20 秒 Abort；上传则显示进度并放宽超时 */
    function beginPanelWait(opts) {
        opts = opts || {};
        var uploadMode = !!opts.uploadMode;
        var timeoutMs = opts.timeoutMs != null ? opts.timeoutMs : PANEL_TIMEOUT_MS;
        var overlay = ensureLoadingOverlay();
        var textEl = overlay.querySelector('.yc-panel-loading-text');
        var slowTimer = null;
        var timeoutTimer = null;
        var abortController = new AbortController();

        function setProgressText(text) {
            if (textEl) textEl.textContent = text || '';
        }

        lockPanelWaitScroll();
        overlay.hidden = false;
        overlay.classList.add('is-blocking');
        overlay.classList.remove('is-visible');
        setProgressText(uploadMode ? '正在上传文件…' : '正在读取数据…');

        if (uploadMode) {
            overlay.classList.add('is-visible');
        } else {
            slowTimer = setTimeout(function () {
                overlay.classList.add('is-visible');
            }, PANEL_WAIT_SPIN_MS);
        }
        timeoutTimer = setTimeout(function () {
            abortController.abort();
        }, timeoutMs);
        return {
            signal: abortController.signal,
            uploadMode: uploadMode,
            setProgressText: setProgressText,
            finish: function () {
                clearTimeout(slowTimer);
                clearTimeout(timeoutTimer);
                overlay.hidden = true;
                overlay.classList.remove('is-blocking', 'is-visible');
                setProgressText('正在读取数据…');
                unlockPanelWaitScroll();
            },
            errorMessage: function (err) {
                /* 超时/连不上：指本次请求未收到服务器响应，不是 navigator.onLine */
                if (err && (err.name === 'AbortError' || err.message === 'Failed to fetch')) {
                    return PANEL_TIMEOUT_MESSAGE;
                }
                return (err && err.message) ? err.message : '操作未成功，请稍后再试';
            },
        };
    }

    function panelXhrWithUploadProgress(url, options, wait) {
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            var headers = options.headers || {};
            var lastLoaded = 0;
            var lastTs = Date.now();
            var busyStarted = false;

            function startBusy() {
                if (busyStarted) return;
                busyStarted = true;
                if (window.YcSessionGuard && window.YcSessionGuard.beginBusy) {
                    window.YcSessionGuard.beginBusy();
                }
            }

            function stopBusy() {
                if (!busyStarted) return;
                busyStarted = false;
                if (window.YcSessionGuard && window.YcSessionGuard.endBusy) {
                    window.YcSessionGuard.endBusy();
                }
            }

            xhr.open(options.method || 'POST', url, true);
            xhr.withCredentials = true;
            Object.keys(headers).forEach(function (k) {
                if (!k) return;
                /* multipart 边界须由浏览器自动带，勿手写 Content-Type */
                if (String(k).toLowerCase() === 'content-type') return;
                try { xhr.setRequestHeader(k, headers[k]); } catch (e) { /* 忽略 */ }
            });

            xhr.upload.onprogress = function (ev) {
                startBusy();
                if (window.YcSessionGuard && window.YcSessionGuard.pingBusy) {
                    window.YcSessionGuard.pingBusy();
                }
                if (!ev.lengthComputable || !ev.total) {
                    wait.setProgressText('正在上传文件…已传 ' + formatUploadBytes(ev.loaded));
                    return;
                }
                var pct = Math.min(99, Math.round((ev.loaded / ev.total) * 100));
                var now = Date.now();
                var dt = (now - lastTs) / 1000;
                var speed = dt > 0.25 ? (ev.loaded - lastLoaded) / dt : 0;
                var remain = speed > 1 ? (ev.total - ev.loaded) / speed : 0;
                var line = '上传中 ' + pct + '%（' + formatUploadBytes(ev.loaded)
                    + ' / ' + formatUploadBytes(ev.total) + '）';
                if (speed > 1) {
                    line += ' · 约 ' + formatUploadBytes(speed) + '/秒 · 大约还要 ' + formatUploadEta(remain);
                }
                wait.setProgressText(line);
                lastLoaded = ev.loaded;
                lastTs = now;
            };

            xhr.upload.onload = function () {
                wait.setProgressText('文件已传完，正在保存…');
            };

            xhr.onreadystatechange = function () {
                if (xhr.readyState !== 4) return;
                stopBusy();
                if (wait.signal && wait.signal.aborted) {
                    reject(Object.assign(new Error(PANEL_TIMEOUT_MESSAGE), { name: 'AbortError' }));
                    return;
                }
                resolve({
                    ok: xhr.status >= 200 && xhr.status < 300,
                    status: xhr.status,
                    text: function () { return Promise.resolve(xhr.responseText || ''); },
                    json: function () {
                        try {
                            return Promise.resolve(JSON.parse(xhr.responseText || '{}'));
                        } catch (e) {
                            return Promise.reject(e);
                        }
                    },
                });
            };

            xhr.onerror = function () {
                stopBusy();
                reject(new Error('Failed to fetch'));
            };

            xhr.onabort = function () {
                stopBusy();
                reject(Object.assign(new Error(PANEL_TIMEOUT_MESSAGE), { name: 'AbortError' }));
            };

            if (wait.signal) {
                wait.signal.addEventListener('abort', function () {
                    try { xhr.abort(); } catch (e) { /* 忽略 */ }
                });
            }

            startBusy();
            xhr.send(options.body || null);
        });
    }

    function panelFetch(url, options) {
        options = options || {};
        var hasFiles = formDataHasUploadFiles(options.body);
        var wait = beginPanelWait({
            uploadMode: hasFiles,
            timeoutMs: hasFiles ? PANEL_UPLOAD_TIMEOUT_MS : PANEL_TIMEOUT_MS,
        });
        var run = hasFiles
            ? panelXhrWithUploadProgress(url, options, wait)
            : fetch(url, {
                method: options.method || 'GET',
                credentials: 'same-origin',
                headers: options.headers || {},
                signal: wait.signal,
                body: options.body,
            });
        return run
            .then(function (response) {
                wait.finish();
                return response;
            })
            .catch(function (err) {
                wait.finish();
                var msg = wait.errorMessage(err);
                var wrapped = new Error(msg);
                throw wrapped;
            });
    }

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
        if (window.ycRebindWaiterTableBoard) {
            window.ycRebindWaiterTableBoard(panelEl);
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

    function isPanelTimeoutMessage(text) {
        return text === PANEL_TIMEOUT_MESSAGE;
    }

    function showPanelTimeoutRetryNotice(message, onRetry, onDismiss) {
        var hint = message + '\n\n若网络已恢复，可点「再试一次」；服务器若已成功处理，不会重复改数据。';
        if (window.YcNotice && typeof window.YcNotice.show === 'function') {
            window.YcNotice.show({
                level: 'error',
                text: hint,
                mustAck: true,
                retryLabel: '再试一次',
                onRetry: onRetry,
                onClose: onDismiss,
            });
            return;
        }
        if (window.confirm(hint + '\n\n是否现在再试一次？')) {
            onRetry();
        } else if (typeof onDismiss === 'function') {
            onDismiss();
        }
    }

    function submitPanelFormRequest(ctx) {
        var form = ctx.form;
        var panelId = ctx.panelId;
        var panelEl = ctx.panelEl;
        var submitter = ctx.submitter;
        var submitBtn = ctx.submitBtn;
        var shopCartState = ctx.shopCartState;
        var idemKey = ctx.idemKey || '';

        var postUrl = form.getAttribute('action') || window.location.href;
        var headers = { 'X-Requested-With': HEADER };
        var token = csrfToken(form);
        if (token) headers['X-CSRFToken'] = token;

        var fd = new FormData(form);
        appendFormSubmitter(fd, submitter);

        if (panelNeedsIdempotency(panelId) && window.YcIdempotency) {
            if (!idemKey) {
                idemKey = window.YcIdempotency.newKey();
            }
            headers = window.YcIdempotency.applyToHeaders(headers, idemKey);
            fd = window.YcIdempotency.applyToFormData(fd, idemKey);
        }

        var retryCtx = {
            form: form,
            panelId: panelId,
            panelEl: panelEl,
            submitter: submitter,
            submitBtn: submitBtn,
            shopCartState: shopCartState,
            idemKey: idemKey,
        };

        return panelFetch(postUrl, {
            method: 'POST',
            body: fd,
            headers: headers,
        })
            .then(parsePanelResponse)
            .then(function (data) {
                applyPanelHtml(panelEl, data.html);
                if (isShopCartPanel(panelId)) {
                    if (window.YcaoShopCart && window.YcaoShopCart.afterPanelReplace && shopCartState) {
                        window.YcaoShopCart.afterPanelReplace(shopCartState);
                    }
                } else if (data.message) {
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
                return data;
            })
            .catch(function (err) {
                var level = 'error';
                var mustAck = true;
                var errText = err.message || '操作未成功，请稍后再试';
                if (errText && (
                    errText.indexOf('未结束订单') >= 0
                    || errText.indexOf('正在使用中') >= 0
                )) {
                    level = 'warning';
                }

                function dismissPanelError() {
                    if (isShopCartPanel(panelId) && window.YcaoShopCart && window.YcaoShopCart.onPanelError) {
                        window.YcaoShopCart.onPanelError(shopCartState);
                    }
                    if (submitBtn) submitBtn.disabled = false;
                }

                if (isPanelTimeoutMessage(errText) && panelNeedsIdempotency(panelId) && idemKey) {
                    showPanelTimeoutRetryNotice(errText, function () {
                        if (submitBtn) submitBtn.disabled = true;
                        submitPanelFormRequest(retryCtx).catch(function () {
                            /* 二次失败仍走同一套提示 */
                        });
                    }, dismissPanelError);
                    return;
                }

                if (isShopCartPanel(panelId) && window.YcaoShopCart && window.YcaoShopCart.onPanelError) {
                    window.YcaoShopCart.onPanelError(shopCartState);
                }
                if (window.YcNotice && typeof window.YcNotice.show === 'function') {
                    window.YcNotice.show({ level: level, text: errText, mustAck: mustAck });
                } else {
                    window.alert(errText);
                }
                if (submitBtn) submitBtn.disabled = false;
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

        var shopCartState = null;
        if (isShopCartPanel(panelId) && window.YcaoShopCart) {
            shopCartState = {
                checkoutValues: window.YcaoShopCart.preserveCheckoutFields
                    ? window.YcaoShopCart.preserveCheckoutFields() : {},
                drawerWasOpen: window.YcaoShopCart.wasDrawerOpen
                    ? window.YcaoShopCart.wasDrawerOpen() : false,
            };
        }

        submitPanelFormRequest({
            form: form,
            panelId: panelId,
            panelEl: panelEl,
            submitter: submitter,
            submitBtn: submitBtn,
            shopCartState: shopCartState,
        });
    }

    /** GET 换 Panel（清单下拉、现金月份等：只换 HTML + replaceState） */
    function switchPanelGet(panelId, targetUrl, options) {
        options = options || {};
        var panelEl = resolvePanelEl(panelId);
        if (!panelEl) return false;
        var urlObj = new URL(targetUrl, window.location.href);
        var fetchUrl = urlObj.pathname + (urlObj.search ? urlObj.search : '');
        panelFetch(fetchUrl, {
            method: 'GET',
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
        panelFetch: panelFetch,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
