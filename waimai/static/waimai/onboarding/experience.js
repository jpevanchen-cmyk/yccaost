/**
 * H4 新版新手体验（试运行）：幻灯片式小步演示（高亮 + 说明卡片 + 假输入）
 */
(function () {
    var boot = null;
    var activeTrack = null;
    var activeMajor = 0;
    var activeMicro = 0;
    var pendingPickerTrack = null;
    var tourRoot = null;
    var tourBackdrop = null;
    var tourSpotlight = null;
    var tourCard = null;
    var tourProgress = null;
    var tourTitle = null;
    var tourBody = null;
    var tourTips = null;
    var tourWarn = null;
    var tourAutoCountdown = null;
    var tourNextBtn = null;
    var tourPrevBtn = null;
    var tourNoAutoCb = null;
    var tourExitBtn = null;
    var noAutoAdvance = false;
    var NO_AUTO_KEY = 'yc_exp_no_auto_advance';
    var resizeHandler = null;
    var typingTimer = null;
    var positionTimer = null;
    var scrollSettleTimer = null;
    var tourNavInstant = false;
    var autoTimer = null;
    var menuAjaxPending = false;
    var productAjaxPending = false;

    function isTourVisible() {
        return !!(tourRoot && !tourRoot.hidden && activeTrack);
    }

    function cleanTourUrl() {
        if (!window.history || !window.history.replaceState || !boot) return;
        try {
            var url = new URL(window.location.href);
            var flag = boot.urlFlag || 'exp';
            if (!url.searchParams.has(flag)) return;
            url.searchParams.delete(flag);
            url.searchParams.delete(boot.urlTrack || 'exp_track');
            url.searchParams.delete(boot.urlMajor || 'exp_major');
            url.searchParams.delete(boot.urlMicro || 'exp_micro');
            var q = url.searchParams.toString();
            window.history.replaceState({}, '', url.pathname + (q ? '?' + q : '') + url.hash);
        } catch (e) { /* 忽略 */ }
    }
    function readBoot() {
        var el = document.getElementById('yc-experience-boot');
        if (!el || !el.textContent) return null;
        try {
            return JSON.parse(el.textContent);
        } catch (e) {
            return null;
        }
    }
    function $(id) {
        return document.getElementById(id);
    }
    function majors(track) {
        return (boot && boot.tracks && boot.tracks[track]) || [];
    }
    function currentMajor() {
        return majors(activeTrack)[activeMajor] || null;
    }
    function currentMicroStep() {
        var major = currentMajor();
        if (!major || !major.microSteps) return null;
        return major.microSteps[activeMicro] || null;
    }
    function saveSession() {
        if (!boot || !window.sessionStorage) return;
        if (activeTrack) {
            sessionStorage.setItem(boot.sessionTrackKey, activeTrack);
            sessionStorage.setItem(boot.sessionMajorKey, String(activeMajor));
            sessionStorage.setItem(boot.sessionMicroKey, String(activeMicro));
        } else {
            sessionStorage.removeItem(boot.sessionTrackKey);
            sessionStorage.removeItem(boot.sessionMajorKey);
            sessionStorage.removeItem(boot.sessionMicroKey);
        }
    }
    function clearSession() {
        var needCleanup = activeTrack === 'seller' && activeMajor >= 2;
        activeTrack = null;
        activeMajor = 0;
        activeMicro = 0;
        if (boot && window.sessionStorage) {
            sessionStorage.removeItem(boot.sessionTrackKey);
            sessionStorage.removeItem(boot.sessionMajorKey);
            sessionStorage.removeItem(boot.sessionMicroKey);
        }
        hideModal('experience-graduate-modal');
        stopTourUi();
        cleanTourUrl();
        if (needCleanup) {
            requestDemoCleanup();
        }
    }
    function getCsrfToken() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
    function requestDemoCleanup() {
        if (!boot || !boot.cleanupUrl) return;
        try {
            fetch(boot.cleanupUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
            }).catch(function () { /* 忽略 */ });
        } catch (e) { /* 忽略 */ }
    }
    function isWritableTourPage() {
        if (document.body.classList.contains('yc-exp-writable')) return true;
        var page = pageKeyFromPath();
        return !!(boot && boot.writablePages && boot.writablePages.indexOf(page) >= 0);
    }
    function isActionStep(step) {
        return !!(step && step.demoType === 'action');
    }
    function isSelectNameStep(step) {
        return !!(step && step.demoType === 'select_name');
    }
    function isCheckStep(step) {
        return !!(step && step.demoType === 'check');
    }
    function isTypeMultiStep(step) {
        return !!(step && step.demoType === 'type_multi');
    }
    function findCheckboxInTarget(el) {
        if (!el) return null;
        if (el.tagName === 'INPUT' && el.type === 'checkbox') return el;
        return el.querySelector('input[type="checkbox"]');
    }
    function runCheckDemo(el, step) {
        var cb = findCheckboxInTarget(el);
        if (!cb || cb.disabled) return;
        var shouldCheck = step && step.demoChecked !== false;
        if (cb.checked === shouldCheck) return;
        cb.checked = shouldCheck;
        cb.dispatchEvent(new Event('change', { bubbles: true }));
    }
    function runSelectChipsDemo(step) {
        if (!step || !step.demoChipLabels || !step.demoChipLabels.length) return;
        var gridId = step.demoChipGrid || 'table-chip-grid';
        var grid = document.getElementById(gridId);
        if (!grid) return;
        grid.querySelectorAll('.code-chip.is-selected').forEach(function (chip) {
            chip.classList.remove('is-selected');
        });
        var form = document.getElementById('table-batch-form');
        if (form) {
            form.querySelectorAll('input[name="selected_ids"]').forEach(function (el) {
                el.remove();
            });
        }
        step.demoChipLabels.forEach(function (label) {
            var chip = grid.querySelector('.code-chip[data-label="' + label + '"]');
            if (!chip) return;
            if (!chip.classList.contains('is-selected')) {
                chip.click();
            }
        });
    }
    function runMultiTypeDemo(step) {
        if (!step || !step.demoFields || !step.demoFields.length) return;
        step.demoFields.forEach(function (field) {
            if (!field || !field.selector || !field.text) return;
            var el = findTarget(field.selector);
            if (!el) return;
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                el.value = field.text;
            }
        });
    }
    function pickDemoDishId() {
        var pick = boot && boot.demoDishEditPick;
        if (pick) {
            var row = document.getElementById('dish-' + pick);
            if (row) {
                var hid = row.querySelector('input[name="dish_id"]');
                if (hid && hid.value) return hid.value;
            }
        }
        var any = document.querySelector('#product-list-body input[name="dish_id"]');
        return any ? any.value : '';
    }
    function submitDemoImageUpload(onSuccess, onFail) {
        if (productAjaxPending) return;
        var dishId = pickDemoDishId();
        if (!dishId) {
            if (typeof onFail === 'function') onFail(null);
            return;
        }
        productAjaxPending = true;
        clearExperienceUnsavedDirty();
        var fd = new FormData();
        fd.append('experience_demo_image_upload', '1');
        fd.append('dish_id', dishId);
        fd.append('experience_product_ajax', '1');
        var token = getCsrfToken();
        if (token) fd.append('csrfmiddlewaretoken', token);
        document.querySelectorAll('input[name^="exp"]').forEach(function (inp) {
            if (inp.name && inp.value) fd.append(inp.name, inp.value);
        });
        var postUrl = window.location.pathname;
        var qs = window.location.search;
        if (qs) postUrl += qs.split('#')[0];
        fetch(postUrl, {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
            headers: {
                'X-Experience-Product-Ajax': '1',
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then(function (resp) { return resp.json(); })
            .then(function (data) {
                productAjaxPending = false;
                if (data.messages) showAjaxMessages(data.messages);
                if (data.productListHtml) {
                    replaceProductListHtml(data.productListHtml, data.editDishPick || '');
                }
                if (boot && data.editDishPick) boot.demoDishEditPick = data.editDishPick;
                if (data.ok) {
                    if (typeof onSuccess === 'function') onSuccess(data);
                } else if (typeof onFail === 'function') {
                    onFail(data);
                }
            }).catch(function () {
                productAjaxPending = false;
                if (window.YcNotice) {
                    YcNotice.show({
                        level: 'error',
                        text: '演示图片上传失败，请稍后重试。',
                        mustAck: true,
                    });
                }
                if (typeof onFail === 'function') onFail(null);
            });
    }
    function bumpMicroForNextStep() {
        var major = currentMajor();
        if (!major || !major.microSteps) return;
        if (activeMicro + 1 > major.microSteps.length) return;
        activeMicro += 1;
        saveSession();
        syncMicroToPage();
    }
    function syncMicroToPage() {
        if (!boot) return;
        var flag = boot.urlFlag || 'exp';
        var trackKey = boot.urlTrack || 'exp_track';
        var majorKey = boot.urlMajor || 'exp_major';
        var microKey = boot.urlMicro || 'exp_micro';
        var microVal = String(activeMicro);
        document.querySelectorAll('input[name="' + microKey + '"]').forEach(function (inp) {
            inp.value = microVal;
        });
        document.querySelectorAll('input[name="' + trackKey + '"]').forEach(function (inp) {
            inp.value = activeTrack || '';
        });
        document.querySelectorAll('input[name="' + majorKey + '"]').forEach(function (inp) {
            inp.value = String(activeMajor);
        });
        document.querySelectorAll('input[name="' + flag + '"]').forEach(function (inp) {
            inp.value = '1';
        });
        try {
            var url = new URL(window.location.href);
            url.searchParams.set(flag, '1');
            if (activeTrack) url.searchParams.set(trackKey, activeTrack);
            url.searchParams.set(majorKey, String(activeMajor));
            url.searchParams.set(microKey, microVal);
            window.history.replaceState({}, '', url.pathname + '?' + url.searchParams.toString() + url.hash);
        } catch (e) { /* 忽略 */ }
    }
    function ensureExpHiddenFieldsInForm(form) {
        if (!boot || !activeTrack || !form) return;
        var fields = [
            [boot.urlFlag || 'exp', '1'],
            [boot.urlTrack || 'exp_track', activeTrack],
            [boot.urlMajor || 'exp_major', String(activeMajor)],
            [boot.urlMicro || 'exp_micro', String(activeMicro)],
        ];
        fields.forEach(function (pair) {
            var name = pair[0];
            var val = pair[1];
            var inp = form.querySelector('input[name="' + name + '"]');
            if (!inp) {
                inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = name;
                form.appendChild(inp);
            }
            inp.value = val;
        });
    }
    function ensureAllExpHiddenFields() {
        if (!isWritableTourPage() || !activeTrack) return;
        document.querySelectorAll('form').forEach(function (form) {
            var method = (form.getAttribute('method') || 'get').toLowerCase();
            if (method === 'post') {
                ensureExpHiddenFieldsInForm(form);
            }
        });
    }
    function showAjaxMessages(msgs) {
        if (!msgs || !msgs.length || !window.YcNotice) return;
        msgs.forEach(function (m) {
            // 引导进行中：成功提示不打断操作（失败/警告仍提示）
            if (isTourVisible() && (m.level === 'ok' || m.level === 'success')) {
                return;
            }
            YcNotice.show({
                level: m.level || 'info',
                text: m.text,
                mustAck: false,
            });
        });
    }
    function clearExperienceUnsavedDirty() {
        if (window.ycSellerUnsavedGuard && window.ycSellerUnsavedGuard.clearAllDirty) {
            window.ycSellerUnsavedGuard.clearAllDirty();
        }
    }
    function reinitMenuPanelUnsavedGuard() {
        document.querySelectorAll('#menu-panel form[data-unsaved-guard]').forEach(function (f) {
            if (window.ycSellerUnsavedGuard && window.ycSellerUnsavedGuard.registerForm) {
                window.ycSellerUnsavedGuard.registerForm(f);
            }
        });
    }
    function replaceMenuPanelHtml(html) {
        var body = document.getElementById('menu-panel-body');
        if (!body) return;
        body.innerHTML = html;
        var panel = document.getElementById('menu-panel');
        if (panel) panel.open = true;
        clearExperienceUnsavedDirty();
        reinitMenuPanelUnsavedGuard();
        ensureAllExpHiddenFields();
    }
    function formMatchesActionStep(form, step) {
        if (!step || !step.selector || !form) return false;
        var el = findTarget(step.selector);
        return !!(el && form.contains(el));
    }
    function isExperienceMenuPostForm(form) {
        if (!form || !isWritableTourPage() || !activeTrack) return false;
        if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return false;
        return !!form.closest('#menu-panel');
    }
    function isExperienceProductPostForm(form) {
        if (!form || !isWritableTourPage() || !activeTrack) return false;
        if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return false;
        if (form.id === 'product-add-form') return true;
        return form.classList.contains('product-edit-form');
    }
    function isExperienceDinePostForm(form) {
        if (!form || !isWritableTourPage() || !activeTrack) return false;
        if (pageKeyFromPath() !== 'preview_dine') return false;
        if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return false;
        return form.id === 'table-add-form' || form.id === 'table-batch-form';
    }
    function appendFormSubmitter(fd, submitter) {
        // 拦截 submit 后用 FormData(form) 会丢触发按钮；须手动补上
        if (!submitter || !submitter.name || submitter.disabled) return;
        if (submitter.type === 'submit' || submitter.type === 'image') {
            fd.set(submitter.name, submitter.value || '1');
        }
    }
    function submitMenuFormAjax(form, onSuccess, onFail, submitter) {
        if (menuAjaxPending) return;
        menuAjaxPending = true;
        clearExperienceUnsavedDirty();
        ensureExpHiddenFieldsInForm(form);
        var fd = new FormData(form);
        appendFormSubmitter(fd, submitter);
        fd.set('experience_menu_ajax', '1');
        var postUrl = window.location.pathname;
        var qs = window.location.search;
        if (qs) postUrl += qs.split('#')[0];
        fetch(postUrl, {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
            headers: {
                'X-Experience-Menu-Ajax': '1',
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then(function (resp) { return resp.json(); })
            .then(function (data) {
                menuAjaxPending = false;
                if (data.messages) showAjaxMessages(data.messages);
                if (data.menuPanelHtml) replaceMenuPanelHtml(data.menuPanelHtml);
                if (data.ok) {
                    if (typeof onSuccess === 'function') onSuccess(data);
                } else if (typeof onFail === 'function') {
                    onFail(data);
                }
            }).catch(function () {
                menuAjaxPending = false;
                if (window.YcNotice) {
                    YcNotice.show({
                        level: 'error',
                        text: '操作失败，请稍后重试。',
                        mustAck: true,
                    });
                }
                if (typeof onFail === 'function') onFail(null);
            });
    }
    function replaceProductListHtml(html, editPick) {
        var body = document.getElementById('product-list-body');
        if (!body) return;
        body.innerHTML = html;
        var panel = document.getElementById('product-list');
        if (panel) panel.open = true;
        clearExperienceUnsavedDirty();
        ensureAllExpHiddenFields();
        var row = document.querySelector('[data-yc-tour="demo-dish-row"]');
        if (!row && editPick) {
            row = document.getElementById('dish-' + editPick);
        }
        if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    function submitProductFormAjax(form, onSuccess, onFail, submitter) {
        if (productAjaxPending) return;
        productAjaxPending = true;
        clearExperienceUnsavedDirty();
        ensureExpHiddenFieldsInForm(form);
        var fd = new FormData(form);
        appendFormSubmitter(fd, submitter);
        fd.set('experience_product_ajax', '1');
        var postUrl = window.location.pathname;
        var qs = window.location.search;
        if (qs) postUrl += qs.split('#')[0];
        fetch(postUrl, {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
            headers: {
                'X-Experience-Product-Ajax': '1',
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then(function (resp) { return resp.json(); })
            .then(function (data) {
                productAjaxPending = false;
                if (data.messages) showAjaxMessages(data.messages);
                if (data.productListHtml) {
                    replaceProductListHtml(data.productListHtml, data.editDishPick || '');
                }
                if (boot && data.editDishPick) {
                    boot.demoDishEditPick = data.editDishPick;
                }
                if (data.ok) {
                    if (typeof onSuccess === 'function') onSuccess(data);
                } else if (typeof onFail === 'function') {
                    onFail(data);
                }
            }).catch(function () {
                productAjaxPending = false;
                if (window.YcNotice) {
                    YcNotice.show({
                        level: 'error',
                        text: '商品操作失败，请稍后重试。',
                        mustAck: true,
                    });
                }
                if (typeof onFail === 'function') onFail(null);
            });
    }
    function fetchMenuProfilePick(profileId, onSuccess, onFail) {
        if (menuAjaxPending || !profileId) return;
        menuAjaxPending = true;
        syncMicroToPage();
        var url = new URL(window.location.href);
        url.searchParams.set('profile', profileId);
        fetch(url.pathname + '?' + url.searchParams.toString(), {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'X-Experience-Menu-Pick': '1',
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then(function (resp) { return resp.json(); })
            .then(function (data) {
                menuAjaxPending = false;
                if (data.menuPanelHtml) replaceMenuPanelHtml(data.menuPanelHtml);
                if (data.ok) {
                    if (typeof onSuccess === 'function') onSuccess(data);
                } else if (typeof onFail === 'function') {
                    onFail(data);
                }
            }).catch(function () {
                menuAjaxPending = false;
                if (window.YcNotice) {
                    YcNotice.show({
                        level: 'error',
                        text: '切换清单失败，请稍后重试。',
                        mustAck: true,
                    });
                }
                if (typeof onFail === 'function') onFail(null);
            });
    }
    function advanceAfterSelectNamePick() {
        bumpMicroForNextStep();
        runMicroStep();
    }
    function bindExperienceMenuAjax() {
        if (document.body.dataset.ycExpMenuAjaxBound) return;
        document.body.dataset.ycExpMenuAjaxBound = '1';
        document.addEventListener('submit', function (ev) {
            var form = ev.target;
            if (!isExperienceMenuPostForm(form) || !isTourVisible()) return;
            ev.preventDefault();
            ev.stopPropagation();
            var step = currentMicroStep();
            var shouldAdvance = !!(step && isActionStep(step) && formMatchesActionStep(form, step));
            submitMenuFormAjax(form, function () {
                if (shouldAdvance) {
                    bumpMicroForNextStep();
                    runMicroStep();
                }
            }, null, ev.submitter || null);
        }, true);
    }
    function bindExperienceProductAjax() {
        if (document.body.dataset.ycExpProductAjaxBound) return;
        document.body.dataset.ycExpProductAjaxBound = '1';
        document.addEventListener('submit', function (ev) {
            var form = ev.target;
            if (!isExperienceProductPostForm(form) || !isTourVisible()) return;
            ev.preventDefault();
            ev.stopPropagation();
            var step = currentMicroStep();
            var shouldAdvance = !!(step && isActionStep(step) && formMatchesActionStep(form, step));
            submitProductFormAjax(form, function () {
                if (shouldAdvance) {
                    bumpMicroForNextStep();
                    runMicroStep();
                }
            }, null, ev.submitter || null);
        }, true);
    }
    function resolveSelectNameValue(el, step) {
        if (!el || el.tagName !== 'SELECT' || !step) return '';
        var val = step.demoText || '';
        if (step.demoTextKey && boot && boot[step.demoTextKey]) {
            val = boot[step.demoTextKey];
        }
        if (step.demoType === 'select_name' && val) {
            for (var i = 0; i < el.options.length; i++) {
                if (el.options[i].text.indexOf(val) >= 0) {
                    return el.options[i].value;
                }
            }
            return '';
        }
        return val;
    }
    function executeActionStep(step) {
        var el = findTarget(step.selector);
        if (!el) return false;
        if (el.disabled) return false;
        var tourKey = el.getAttribute('data-yc-tour') || '';
        if (tourKey === 'add-demo-image-btn') {
            var flag = document.getElementById('experience-demo-image-flag');
            if (flag) flag.value = '1';
            var status = document.querySelector('[data-yc-tour="add-demo-image-status"]');
            if (status) status.hidden = false;
            bumpMicroForNextStep();
            runMicroStep();
            return true;
        }
        if (tourKey === 'demo-dish-image-upload-btn') {
            submitDemoImageUpload(function () {
                bumpMicroForNextStep();
                runMicroStep();
            });
            return true;
        }
        if (tourKey === 'preview-shop-order-link') {
            var previewHref = (el.getAttribute('href') || '').trim();
            if (previewHref) window.open(previewHref, '_blank', 'noopener');
            bumpMicroForNextStep();
            runMicroStep();
            return true;
        }
        if (el.tagName === 'A') {
            var href = (el.getAttribute('href') || '').trim();
            if (href && href.indexOf('edit=') >= 0) {
                bumpMicroForNextStep();
                saveSession();
                var rel = new URL(href, window.location.href);
                var dest = buildTourUrl(
                    rel.pathname + (rel.search ? '?' + rel.searchParams.toString() : ''),
                    activeTrack,
                    activeMajor,
                    activeMicro
                );
                window.location.href = dest + (rel.hash || '');
                return true;
            }
            if (el.getAttribute('data-yc-tour') === 'menu-print-qr-link') {
                bumpMicroForNextStep();
                saveSession();
                window.location.href = buildTourUrl(
                    '/experience/preview/seller/print-qr/',
                    activeTrack,
                    activeMajor,
                    activeMicro
                );
                return true;
            }
        }
        var form = el.closest('form');
        if (form && isExperienceMenuPostForm(form)) {
            submitMenuFormAjax(form, function () {
                bumpMicroForNextStep();
                runMicroStep();
            }, null, el.tagName === 'BUTTON' || el.tagName === 'INPUT' ? el : null);
            return true;
        }
        if (form && isExperienceProductPostForm(form)) {
            submitProductFormAjax(form, function () {
                bumpMicroForNextStep();
                runMicroStep();
            }, null, el.tagName === 'BUTTON' || el.tagName === 'INPUT' ? el : null);
            return true;
        }
        if (form && isExperienceDinePostForm(form)) {
            bumpMicroForNextStep();
            saveSession();
            ensureExpHiddenFieldsInForm(form);
            if (window.ycSellerUnsavedGuard &&
                typeof window.ycSellerUnsavedGuard.allowNextUnload === 'function') {
                window.ycSellerUnsavedGuard.allowNextUnload();
            }
            if (el.tagName === 'BUTTON' && el.type === 'submit') {
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit(el);
                } else {
                    form.submit();
                }
            } else {
                el.click();
            }
            return true;
        }
        return false;
    }
    function executeSelectNameStep(step) {
        var el = findTarget(step.selector);
        if (!el || el.tagName !== 'SELECT') return false;
        var targetVal = resolveSelectNameValue(el, step);
        if (!targetVal) return false;
        if (el.value === targetVal) return false;
        fetchMenuProfilePick(targetVal, function () {
            advanceAfterSelectNamePick();
        });
        return true;
    }
    function bindStepInteractionListeners(step) {
        if (!step || !step.selector) return;
        var el = findTarget(step.selector);
        if (!el) return;
        if (step.demoType === 'select_name' && el.tagName === 'SELECT' && !el.dataset.ycExpSelectBound) {
            el.dataset.ycExpSelectBound = '1';
            el.addEventListener('change', function (ev) {
                if (!isTourVisible() || currentMicroStep() !== step) return;
                ev.preventDefault();
                ev.stopImmediatePropagation();
                var pid = el.value;
                if (!pid) return;
                fetchMenuProfilePick(pid, function () {
                    advanceAfterSelectNamePick();
                });
            }, true);
        }
    }
    function restoreFromUrl() {
        var params = new URLSearchParams(window.location.search);
        if (params.get(boot.urlFlag || 'exp') !== '1') return false;
        var track = params.get(boot.urlTrack || 'exp_track');
        if (!track) return false;
        activeTrack = track;
        activeMajor = parseInt(params.get(boot.urlMajor || 'exp_major') || '0', 10);
        activeMicro = parseInt(params.get(boot.urlMicro || 'exp_micro') || '0', 10);
        saveSession();
        return true;
    }
    function restoreFromSession() {
        if (!boot || !window.sessionStorage) return false;
        var track = sessionStorage.getItem(boot.sessionTrackKey);
        if (!track) return false;
        activeTrack = track;
        activeMajor = parseInt(sessionStorage.getItem(boot.sessionMajorKey) || '0', 10);
        activeMicro = parseInt(sessionStorage.getItem(boot.sessionMicroKey) || '0', 10);
        return true;
    }
    function markWelcomeSeen() {
        if (boot && window.localStorage) {
            localStorage.setItem(boot.welcomeSeenKey, '1');
        }
    }
    function welcomeSeen() {
        if (!boot || !window.localStorage) return true;
        return localStorage.getItem(boot.welcomeSeenKey) === '1';
    }
    function showModal(id) {
        var m = $(id);
        if (m) m.hidden = false;
    }
    function hideModal(id) {
        var m = $(id);
        if (m) m.hidden = true;
    }
    function hideExperienceWelcome() {
        hideModal('experience-welcome-modal');
        markWelcomeSeen();
    }
    function pageKeyFromPath(path) {
        path = path || window.location.pathname;
        if (path === '/' || path === '/directory/') return 'home';
        if (path.indexOf('/shop-register') === 0) return 'shop_register';
        if (path.indexOf('/register') === 0) return 'register';
        if (path.indexOf('/shop') === 0) return 'shop';
        if (path.indexOf('/experience/preview/seller/operating') === 0) return 'preview_operating';
        if (path.indexOf('/experience/preview/seller/products') === 0) return 'preview_products';
        if (path.indexOf('/experience/preview/seller/print-qr') === 0) return 'preview_print_qr';
        if (path.indexOf('/experience/preview/seller/workbench') === 0) return 'preview_workbench_manage';
        if (path.indexOf('/experience/preview/seller/dine') === 0) return 'preview_dine';
        if (path.indexOf('/experience/preview/seller/table-stickers') === 0) return 'preview_table_stickers';
        if (path.indexOf('/experience/preview/seller/delivery') === 0) return 'preview_delivery';
        if (path.indexOf('/onboarding/preview/seller/products') === 0) return 'preview_products';
        if (path.indexOf('/onboarding/preview/seller/print-qr') === 0) return 'preview_print_qr';
        if (path.indexOf('/onboarding/preview/seller/workbench') === 0) return 'preview_workbench_manage';
        if (path.indexOf('/onboarding/preview/work/login') === 0) return 'preview_work_login';
        if (path.indexOf('/onboarding/preview/work/') === 0) return 'preview_work_hub';
        if (path.indexOf('/onboarding/preview/seller/orders/') === 0 && path !== '/onboarding/preview/seller/orders/' && path !== '/onboarding/preview/seller/orders') return 'preview_order_detail';
        if (path.indexOf('/onboarding/preview/seller/orders') === 0) return 'preview_orders';
        if (path.indexOf('/onboarding/preview/seller/payment') === 0) return 'preview_payment';
        if (path.indexOf('/onboarding/preview/seller/homepage') === 0) return 'preview_homepage';
        if (path.indexOf('/onboarding/preview/seller/dine') === 0) return 'preview_dine';
        if (path.indexOf('/onboarding/preview/seller/delivery') === 0) return 'preview_delivery';
        if (path.indexOf('/onboarding/preview/buyer/orders') === 0) return 'preview_buyer_orders';
        return '';
    }
    function resolvePagePath(page) {
        if (page === 'shop' && boot && boot.officialSellerId) {
            return '/shop/?seller_id=' + encodeURIComponent(boot.officialSellerId);
        }
        return (boot && boot.pages && boot.pages[page]) || '/';
    }
    function stepPath(step) {
        if (step && step.path && step.path.indexOf('/') === 0) {
            return step.path;
        }
        return resolvePagePath(step ? step.page : '');
    }
    function openFoldSelector(sel) {
        if (!sel) return;
        var el = findTarget(sel);
        if (el && el.tagName === 'DETAILS') {
            el.open = true;
        }
    }
    /** 按小步 foldLayout 同步工作台折叠区：该开的开、其余全关 */
    function syncStepFoldLayout(step) {
        if (!step || step.foldLayout === undefined || step.foldLayout === null) return;
        var want = {};
        var ids = step.foldLayout;
        var i;
        for (i = 0; i < ids.length; i++) {
            want[ids[i]] = true;
        }
        var folds = document.querySelectorAll('details.seller-panel-fold');
        for (i = 0; i < folds.length; i++) {
            var d = folds[i];
            if (!d.id) continue;
            d.open = !!want[d.id];
        }
    }
    function runDemoClick(sel) {
        if (!sel) return;
        var el = findTarget(sel);
        if (!el || typeof el.click !== 'function') return;
        // 带 href 的链接会整页跳转且丢失 yc_tour 参数，导致引导卡死；改由 step.path 换页
        if (el.tagName === 'A') {
            var href = (el.getAttribute('href') || '').trim();
            if (href && href !== '#' && href.indexOf('javascript:') !== 0) {
                return;
            }
        }
        el.click();
    }
    function majorEntryPath(major) {
        if (!major) return boot && boot.homeUrl ? boot.homeUrl : '/experience/';
        if (major.entryPath) return major.entryPath;
        if (major.microSteps && major.microSteps[0]) {
            return stepPath(major.microSteps[0]);
        }
        return boot && boot.homeUrl ? boot.homeUrl : '/experience/';
    }
    function navigateToMajor(track, majorIndex) {
        if (!boot) return;
        var list = majors(track);
        if (majorIndex < 0 || majorIndex >= list.length) return;
        activeTrack = track;
        activeMajor = majorIndex;
        activeMicro = 0;
        saveSession();
        stopTourUi();
        var major = list[majorIndex];
        var path = majorEntryPath(major);
        window.location.href = buildTourUrl(path, track, majorIndex, 0);
    }
    function buildTourUrl(path, track, major, micro) {
        var base = path.split('?')[0];
        var qs = new URLSearchParams(path.indexOf('?') >= 0 ? path.split('?')[1] : '');
        qs.set(boot.urlFlag || 'exp', '1');
        qs.set(boot.urlTrack || 'exp_track', track);
        qs.set(boot.urlMajor || 'exp_major', String(major));
        qs.set(boot.urlMicro || 'exp_micro', String(micro));
        return base + '?' + qs.toString();
    }
    function ensureTourDom() {
        if (tourRoot) return;
        tourRoot = document.createElement('div');
        tourRoot.id = 'yc-exp-tour-root';
        tourRoot.hidden = true;
        tourRoot.innerHTML = ''
            + '<div class="yc-exp-tour-backdrop"></div>'
            + '<div class="yc-exp-tour-spotlight" aria-hidden="true"></div>'
            + '<div class="yc-exp-tour-card card" role="dialog" aria-modal="true">'
            + '<p class="yc-exp-tour-progress"></p>'
            + '<h3 class="yc-exp-tour-title"></h3>'
            + '<p class="yc-exp-tour-body card-meta"></p>'
            + '<ul class="yc-exp-tour-tips"></ul>'
            + '<p class="yc-exp-tour-warn"></p>'
            + '<p class="yc-exp-tour-auto-count card-meta" hidden></p>'
            + '<label class="yc-exp-tour-no-auto">'
            + '<input type="checkbox" class="yc-exp-tour-no-auto-cb"> 不自动切换到下一步'
            + '</label>'
            + '<div class="yc-exp-tour-nav-actions">'
            + '<button type="button" class="btn btn-sm btn-outline yc-exp-tour-prev">上一步</button>'
            + '<button type="button" class="btn btn-sm btn-orange yc-exp-tour-next">下一步</button>'
            + '</div>'
            + '<button type="button" class="btn btn-sm btn-outline btn-block yc-exp-tour-exit">退出体验</button>'
            + '</div></div>';
        document.body.appendChild(tourRoot);
        document.body.classList.add('yc-exp-tour-active');
        tourBackdrop = tourRoot.querySelector('.yc-exp-tour-backdrop');
        tourSpotlight = tourRoot.querySelector('.yc-exp-tour-spotlight');
        tourCard = tourRoot.querySelector('.yc-exp-tour-card');
        tourProgress = tourRoot.querySelector('.yc-exp-tour-progress');
        tourTitle = tourRoot.querySelector('.yc-exp-tour-title');
        tourBody = tourRoot.querySelector('.yc-exp-tour-body');
        tourTips = tourRoot.querySelector('.yc-exp-tour-tips');
        tourWarn = tourRoot.querySelector('.yc-exp-tour-warn');
        tourAutoCountdown = tourRoot.querySelector('.yc-exp-tour-auto-count');
        tourNoAutoCb = tourRoot.querySelector('.yc-exp-tour-no-auto-cb');
        tourPrevBtn = tourRoot.querySelector('.yc-exp-tour-prev');
        tourNextBtn = tourRoot.querySelector('.yc-exp-tour-next');
        tourExitBtn = tourRoot.querySelector('.yc-exp-tour-exit');
        loadNoAutoAdvancePref();
        if (tourNoAutoCb) {
            tourNoAutoCb.checked = noAutoAdvance;
            tourNoAutoCb.addEventListener('change', function () {
                noAutoAdvance = !!tourNoAutoCb.checked;
                saveNoAutoAdvancePref();
                if (noAutoAdvance) {
                    clearAutoTimer();
                    if (tourAutoCountdown) tourAutoCountdown.hidden = true;
                    refreshTourNavButtons(currentMicroStep());
                } else if (isTourVisible()) {
                    startAutoAdvance(currentMicroStep());
                    refreshTourNavButtons(currentMicroStep());
                }
            });
        }
        tourPrevBtn.addEventListener('click', retreatMicro);
        tourNextBtn.addEventListener('click', advanceMicro);
        tourExitBtn.addEventListener('click', function () {
            clearSession();
        });
        if (window.YcExperienceModal) {
            window.YcExperienceModal.enableDrag(tourCard, tourCard.querySelector('.yc-exp-tour-progress') || tourCard);
        }
        tourBackdrop.addEventListener('click', function () { /* 须主动点按钮 */ });
        resizeHandler = function () {
            repositionSpotlightOnly(currentMicroStep());
        };
        window.addEventListener('resize', resizeHandler);
        blockFormsDuringTour();
    }
    function blockFormsDuringTour() {
        document.querySelectorAll('form').forEach(function (form) {
            if (form.dataset.ycTourBound) return;
            form.dataset.ycTourBound = '1';
            form.addEventListener('submit', function (ev) {
                if (activeTrack && tourRoot && !tourRoot.hidden) {
                    if (isWritableTourPage()) {
                        return;
                    }
                    ev.preventDefault();
                    if (window.YcNotice) {
                        YcNotice.show({
                            level: 'warning',
                            text: '新版体验引导中不会真提交表单；请点「下一小步」继续，或「退出体验」。',
                            mustAck: true,
                        });
                    }
                }
            });
        });
    }
    function loadNoAutoAdvancePref() {
        try {
            noAutoAdvance = sessionStorage.getItem(NO_AUTO_KEY) === '1';
        } catch (e) {
            noAutoAdvance = false;
        }
    }
    function saveNoAutoAdvancePref() {
        try {
            sessionStorage.setItem(NO_AUTO_KEY, noAutoAdvance ? '1' : '0');
        } catch (e) { /* 忽略 */ }
    }
    function isAutoAdvanceEnabled() {
        return !noAutoAdvance;
    }
    function clearAutoTimer() {
        if (autoTimer) {
            clearInterval(autoTimer);
            autoTimer = null;
        }
    }
    function stepAutoSeconds(step) {
        if (step && typeof step.autoSeconds === 'number' && step.autoSeconds > 0) {
            return step.autoSeconds;
        }
        var def = 8;
        var typeDef = 12;
        if (boot) {
            if (typeof boot.autoAdvanceSeconds === 'number') def = boot.autoAdvanceSeconds;
            if (typeof boot.autoAdvanceSecondsTypeDemo === 'number') typeDef = boot.autoAdvanceSecondsTypeDemo;
        }
        if (step && step.demoType === 'type') return typeDef;
        if (step && (step.demoType === 'select' || step.demoType === 'select_name' || step.demoType === 'action' || step.demoType === 'check' || step.demoType === 'type_multi')) {
            return typeDef;
        }
        return def;
    }
    function stepCountdownLabel(step, isLastMicro) {
        if (isLastMicro) return '本步完成';
        if (isActionStep(step)) return '执行操作';
        if (isCheckStep(step)) return '勾选演示';
        if (isSelectNameStep(step)) return '选择清单';
        return '下一小步';
    }
    function updateAutoCountdownUi(secs, step, isLastMicro) {
        if (!tourAutoCountdown) return;
        if (secs <= 0) {
            tourAutoCountdown.hidden = true;
            return;
        }
        tourAutoCountdown.hidden = false;
        var action = stepCountdownLabel(step, isLastMicro);
        tourAutoCountdown.textContent = secs + ' 秒后自动' + action;
    }
    function startAutoAdvance(step) {
        clearAutoTimer();
        if (!step || !isAutoAdvanceEnabled()) {
            if (tourAutoCountdown) tourAutoCountdown.hidden = true;
            return;
        }
        var secs = stepAutoSeconds(step);
        if (!secs || secs <= 0) {
            if (tourAutoCountdown) tourAutoCountdown.hidden = true;
            return;
        }
        var major = currentMajor();
        var isLastMicro = major && activeMicro >= major.microSteps.length - 1;
        updateAutoCountdownUi(secs, step, isLastMicro);
        autoTimer = window.setInterval(function () {
            secs -= 1;
            if (secs <= 0) {
                clearAutoTimer();
                if (tourAutoCountdown) tourAutoCountdown.hidden = true;
                advanceMicro();
                return;
            }
            updateAutoCountdownUi(secs, step, isLastMicro);
        }, 1000);
    }
    function stopTourUi() {
        clearAutoTimer();
        if (typingTimer) {
            clearInterval(typingTimer);
            typingTimer = null;
        }
        if (positionTimer) {
            clearTimeout(positionTimer);
            positionTimer = null;
        }
        clearScrollSettleTimer();
        if (tourRoot) tourRoot.hidden = true;
        document.body.classList.remove('yc-exp-tour-active');
        syncSeller5Step12ScreenshotMode(null);
        if (tourSpotlight) tourSpotlight.hidden = true;
    }
    function openMobileNav(cb) {
        var toggle = $('nav-toggle');
        var nav = $('site-nav');
        if (toggle && nav && !nav.classList.contains('is-open')) {
            toggle.click();
            window.setTimeout(cb, 350);
        } else {
            cb();
        }
    }
    function findTarget(selector) {
        if (!selector) return null;
        try {
            return document.querySelector(selector);
        } catch (e) {
            return null;
        }
    }
    function runSelectDemo(el, step) {
        if (!el || !step) return;
        var selectEl = el;
        if (el.tagName !== 'SELECT' && el.querySelector) {
            selectEl = el.querySelector('select');
        }
        if (!selectEl || selectEl.tagName !== 'SELECT') return;
        var val = step.demoText || '';
        if (step.demoTextKey && boot && boot[step.demoTextKey]) {
            val = boot[step.demoTextKey];
        }
        if (step.demoType === 'select_name' && val) {
            var matched = '';
            for (var i = 0; i < selectEl.options.length; i++) {
                if (selectEl.options[i].text.indexOf(val) >= 0) {
                    matched = selectEl.options[i].value;
                    break;
                }
            }
            val = matched;
        }
        if (!val) return;
        if (selectEl.value === val) return;
        selectEl.value = val;
        if (step.demoType === 'select_name' || step.demoType === 'select') {
            selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    function resolveTextField(el) {
        if (!el) return null;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return el;
        if (el.querySelector) {
            var inner = el.querySelector('input, textarea');
            if (inner) return inner;
        }
        return null;
    }
    function runTypeDemo(el, text) {
        var field = resolveTextField(el);
        if (!field) return;
        field.value = '';
        field.focus({ preventScroll: true });
        var i = 0;
        if (typingTimer) clearInterval(typingTimer);
        typingTimer = window.setInterval(function () {
            if (i >= text.length) {
                clearInterval(typingTimer);
                typingTimer = null;
                field.dispatchEvent(new Event('input', { bubbles: true }));
                return;
            }
            field.value += text.charAt(i);
            i += 1;
        }, 70);
    }
    function applySpotlightRect(target, pad) {
        if (!tourSpotlight || !tourCard) return;
        if (!target) {
            tourSpotlight.hidden = true;
            placeCard(null);
            return;
        }
        var rect = target.getBoundingClientRect();
        tourSpotlight.hidden = false;
        tourSpotlight.style.top = (rect.top - pad) + 'px';
        tourSpotlight.style.left = (rect.left - pad) + 'px';
        tourSpotlight.style.width = (rect.width + pad * 2) + 'px';
        tourSpotlight.style.height = (rect.height + pad * 2) + 'px';
        if (tourCard.dataset.expUserDragged !== '1') {
            placeCard(rect);
        }
    }
    function repositionSpotlightOnly(step) {
        if (!isTourVisible() || !step) return;
        var target = findTarget(step.selector);
        var pad = 8;
        if (!target) {
            if (tourSpotlight) tourSpotlight.hidden = true;
            return;
        }
        var rect = target.getBoundingClientRect();
        tourSpotlight.hidden = false;
        tourSpotlight.style.top = (rect.top - pad) + 'px';
        tourSpotlight.style.left = (rect.left - pad) + 'px';
        tourSpotlight.style.width = (rect.width + pad * 2) + 'px';
        tourSpotlight.style.height = (rect.height + pad * 2) + 'px';
        if (tourCard && tourCard.dataset.expUserDragged !== '1') {
            placeCard(rect);
        }
    }
    function positionTour(step, opts) {
        opts = opts || {};
        var instant = !!opts.instant;
        if (!tourRoot || !step || !isTourVisible()) return;
        if (positionTimer) {
            clearTimeout(positionTimer);
            positionTimer = null;
        }
        clearScrollSettleTimer();
        var pad = 8;
        function finalizeSpotlight() {
            if (!isTourVisible() || currentMicroStep() !== step) return;
            var target = findTarget(step.selector);
            if (target) {
                applySpotlightRect(target, pad);
                if (isSeller5Step12Mode(step)) {
                    window.setTimeout(function () {
                        if (!isTourVisible()) return;
                        repositionSpotlightOnly(step);
                    }, 150);
                } else if (isDineSettingsFieldStep(step)) {
                    window.setTimeout(function () {
                        if (!isTourVisible()) return;
                        repositionSpotlightOnly(step);
                    }, 180);
                } else if (isSeller6ScreenshotMode()) {
                    window.setTimeout(function () {
                        if (!isTourVisible()) return;
                        repositionSpotlightOnly(step);
                    }, 150);
                }
            } else {
                applySpotlightRect(null, pad);
            }
        }
        var target = findTarget(step.selector);
        if (target) {
            scrollTourTarget(target, instant);
            afterScrollSettled(finalizeSpotlight, instant);
        } else {
            applySpotlightRect(null, pad);
        }
    }
    function resetTourCardPosition() {
        if (!tourCard) return;
        if (window.YcExperienceModal && window.YcExperienceModal.resetPanelPosition) {
            window.YcExperienceModal.resetPanelPosition(tourCard);
        } else {
            delete tourCard.dataset.expUserDragged;
            tourCard.style.transform = 'none';
        }
    }
    function isSeller6ScreenshotMode() {
        return document.body.classList.contains('yc-exp-seller-6-screenshots');
    }
    function tourRectsOverlap(cardRect, highlightRect, gap) {
        gap = gap || 12;
        return !(
            cardRect.right + gap <= highlightRect.left
            || cardRect.left >= highlightRect.right + gap
            || cardRect.bottom + gap <= highlightRect.top
            || cardRect.top >= highlightRect.bottom + gap
        );
    }
    function isDineSettingsFieldStep(step) {
        if (!step || !step.selector) return false;
        var sel = step.selector;
        return sel.indexOf('dine-channel') >= 0
            || sel.indexOf('dine-takeaway') >= 0
            || sel.indexOf('dine-delivery') >= 0
            || sel.indexOf('dine-hours') >= 0
            || sel.indexOf('dine-wait-') >= 0
            || sel.indexOf('dine-share') >= 0
            || sel.indexOf('dine-restrict') >= 0
            || sel.indexOf('fold-lan-address') >= 0
            || sel.indexOf('dine-wait-time-rules') >= 0;
    }
    function isSeller5Step12Mode(step) {
        return !!(step && step.selector && step.selector.indexOf('demo-s5-step12-shot') >= 0);
    }
    function syncSeller5Step12ScreenshotMode(step) {
        var on = isSeller5Step12Mode(step);
        document.body.classList.toggle('yc-exp-seller-5-step12-screenshots', on);
        var panel = document.getElementById('experience-s5-step12');
        if (panel) panel.hidden = !on;
    }
    function preferCardAboveHighlight(step) {
        return false;
    }
    function scrollTourTarget(target, instant) {
        if (!target) return;
        var step = currentMicroStep();
        var behavior = instant ? 'auto' : 'smooth';
        if (isSeller6ScreenshotMode()) {
            var rect = target.getBoundingClientRect();
            var absoluteTop = rect.top + window.pageYOffset;
            var offset = Math.max(0, window.innerHeight * 0.1);
            window.scrollTo({ top: Math.max(0, absoluteTop - offset), behavior: behavior });
            return;
        }
        if (isSeller5Step12Mode(step)) {
            window.scrollTo({ top: 0, behavior: behavior });
            return;
        }
        target.scrollIntoView({ block: 'center', behavior: behavior });
    }
    function clearScrollSettleTimer() {
        if (scrollSettleTimer) {
            clearTimeout(scrollSettleTimer);
            scrollSettleTimer = null;
        }
    }
    /** 滚动与折叠动画停稳后再量位置，避免上一步连点框错位 */
    function afterScrollSettled(cb, instant) {
        clearScrollSettleTimer();
        var delay = instant ? 90 : 320;
        scrollSettleTimer = window.setTimeout(function () {
            scrollSettleTimer = null;
            cb();
        }, delay);
    }
    function placeCardSeller5Step12(rect, cardW, cardH, margin) {
        var maxLeft = Math.max(margin, window.innerWidth - cardW - margin);
        tourCard.style.left = maxLeft + 'px';
        var top = Math.max(margin, Math.min(rect.top, window.innerHeight - cardH - margin));
        tourCard.style.top = top + 'px';
    }
    function placeCardClearOfHighlight(highlightRect, cardW, cardH, margin) {
        var maxLeft = Math.max(margin, window.innerWidth - cardW - margin);
        var centerLeft = highlightRect.left + (highlightRect.width - cardW) / 2;
        centerLeft = Math.max(margin, Math.min(centerLeft, maxLeft));
        var hl = {
            top: highlightRect.top,
            left: highlightRect.left,
            right: highlightRect.right,
            bottom: highlightRect.bottom,
        };
        var tries = [
            { top: highlightRect.bottom + 16, left: centerLeft },
            { top: highlightRect.top - cardH - 16, left: centerLeft },
            { top: window.innerHeight - cardH - margin, left: margin },
            { top: window.innerHeight - cardH - margin, left: maxLeft },
            { top: margin, left: centerLeft },
        ];
        var i;
        for (i = 0; i < tries.length; i++) {
            var t = tries[i];
            t.top = Math.max(margin, Math.min(t.top, window.innerHeight - cardH - margin));
            t.left = Math.max(margin, Math.min(t.left, maxLeft));
            var cr = {
                top: t.top,
                left: t.left,
                right: t.left + cardW,
                bottom: t.top + cardH,
            };
            if (!tourRectsOverlap(cr, hl, 12)) {
                tourCard.style.left = t.left + 'px';
                tourCard.style.top = t.top + 'px';
                return;
            }
        }
        tourCard.style.left = Math.max(margin, (window.innerWidth - cardW) / 2) + 'px';
        tourCard.style.top = (window.innerHeight - cardH - margin) + 'px';
    }
    function placeCard(rect) {
        if (!tourCard) return;
        if (tourCard.dataset.expUserDragged === '1') return;
        var cardW = tourCard.offsetWidth || Math.min(isSeller6ScreenshotMode() ? 360 : 420, window.innerWidth - 24);
        var cardH = tourCard.offsetHeight || 220;
        var margin = 12;
        var maxLeft = Math.max(margin, window.innerWidth - cardW - margin);
        tourCard.style.transform = 'none';
        tourCard.style.margin = '0';
        if (!rect) {
            tourCard.style.left = Math.max(margin, (window.innerWidth - cardW) / 2) + 'px';
            tourCard.style.top = Math.max(margin, window.innerHeight * 0.18) + 'px';
            return;
        }
        if (isSeller6ScreenshotMode()) {
            placeCardClearOfHighlight(rect, cardW, cardH, margin);
            return;
        }
        if (isSeller5Step12Mode(currentMicroStep())) {
            placeCardSeller5Step12(rect, cardW, cardH, margin);
            return;
        }
        var below = rect.bottom + 16;
        var top;
        if (below + cardH < window.innerHeight - margin) {
            top = below;
        } else {
            top = Math.max(margin, Math.min(rect.top - cardH - 16, window.innerHeight - cardH - margin));
        }
        var left = rect.left + (rect.width - cardW) / 2;
        left = Math.max(margin, Math.min(left, maxLeft));
        tourCard.style.left = left + 'px';
        tourCard.style.top = top + 'px';
    }
    function fillTourCard(step) {
        var major = currentMajor();
        if (!major || !step) return;
        var trackLabel = activeTrack === 'seller' ? '开店体验' : '购物体验';
        tourProgress.textContent = trackLabel + ' · 第 ' + (major.index + 1) + ' 大步'
            + ' · 小步 ' + (activeMicro + 1) + '/' + major.microSteps.length;
        tourTitle.textContent = step.title;
        tourBody.textContent = step.body || '';
        tourBody.hidden = !step.body;
        tourTips.innerHTML = '';
        (step.tips || []).forEach(function (tip) {
            var li = document.createElement('li');
            li.textContent = tip;
            tourTips.appendChild(li);
        });
        tourTips.hidden = !(step.tips && step.tips.length);
        tourWarn.textContent = step.warn ? ('⚠️ ' + step.warn) : '';
        tourWarn.hidden = !step.warn;
        refreshTourNavButtons(step);
        if (tourNoAutoCb) tourNoAutoCb.checked = noAutoAdvance;
    }
    function refreshTourNavButtons(step) {
        if (!tourNextBtn || !tourPrevBtn) return;
        var major = currentMajor();
        if (!major || !step) return;
        var isLastMicro = activeMicro >= major.microSteps.length - 1;
        tourNextBtn.textContent = isLastMicro ? '本步完成' : '下一步';
        tourPrevBtn.disabled = activeMicro <= 0;
    }
    function syncExperiencePrintLinkHref() {
        var link = document.querySelector('[data-yc-tour="menu-print-qr-link"]');
        if (!link || !boot || !isTourVisible()) return;
        var major = currentMajor();
        if (!major || major.id !== 'seller-4') return;
        var step = currentMicroStep();
        if (!step || !step.selector || step.selector.indexOf('menu-print-qr-link') < 0) return;
        // 点链接进入打印页时，应落在「打印页说明」小步（本步 micro + 1）
        link.href = buildTourUrl(
            '/experience/preview/seller/print-qr/',
            activeTrack,
            activeMajor,
            activeMicro + 1
        );
        link.setAttribute('data-unsaved-skip', '1');
    }
    function showMicroUi(step) {
        var instantScroll = tourNavInstant;
        tourNavInstant = false;
        ensureTourDom();
        resetTourCardPosition();
        fillTourCard(step);
        tourRoot.hidden = false;
        document.body.classList.add('yc-exp-tour-active');
        syncSeller5Step12ScreenshotMode(step);
        syncExperiencePrintLinkHref();
        syncStepFoldLayout(step);
        if (step.openFold) {
            openFoldSelector(step.openFold);
        }
        if (step.demoClick) {
            runDemoClick(step.demoClick);
        }
        positionTour(step, { instant: instantScroll });
        bindStepInteractionListeners(step);
        ensureAllExpHiddenFields();
        if (step.demoType === 'type' && step.demoText && step.selector) {
            window.setTimeout(function () {
                runTypeDemo(findTarget(step.selector), step.demoText);
            }, 400);
        }
        if (isTypeMultiStep(step)) {
            window.setTimeout(function () {
                runMultiTypeDemo(step);
            }, 400);
        }
        if (isCheckStep(step) && step.selector) {
            window.setTimeout(function () {
                runCheckDemo(findTarget(step.selector), step);
            }, 400);
        }
        if (step.demoType === 'select' && step.selector) {
            window.setTimeout(function () {
                runSelectDemo(findTarget(step.selector), step);
            }, 400);
        }
        if (step.demoChipLabels && step.demoChipLabels.length) {
            window.setTimeout(function () {
                if (!isTourVisible() || currentMicroStep() !== step) return;
                runSelectChipsDemo(step);
            }, 400);
        }
        if (step.selector && step.selector.indexOf('add-list-all') >= 0) {
            window.setTimeout(function () {
                if (!isTourVisible() || currentMicroStep() !== step) return;
                var listCb = findTarget(step.selector);
                if (listCb && listCb.type === 'checkbox' && !listCb.checked) {
                    listCb.checked = true;
                    listCb.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }, 400);
        }
        window.setTimeout(function () {
            if (!isTourVisible() || currentMicroStep() !== step) return;
            bindStepInteractionListeners(step);
            startAutoAdvance(step);
        }, 350);
    }
    function runMicroStep() {
        var step = currentMicroStep();
        var major = currentMajor();
        if (!major) {
            clearSession();
            return;
        }
        if (activeMicro >= major.microSteps.length) {
            activeMicro = major.microSteps.length - 1;
            showGraduate(major, function (goNext) {
                if (major.cleanupOnComplete) {
                    requestDemoCleanup();
                }
                if (!goNext) {
                    clearSession();
                    return;
                }
                navigateToMajor(activeTrack, activeMajor + 1);
            });
            return;
        }
        if (!step) {
            clearSession();
            return;
        }
        saveSession();
        var needPage = step.page;
        var onPage = pageKeyFromPath();
        var targetPath = stepPath(step);
        var targetBase = targetPath.split('?')[0];
        var pathMatches = window.location.pathname === targetBase;
        var onTarget = pathMatches || (!step.path && needPage && onPage === needPage);
        if (needPage && !onTarget) {
            window.location.href = buildTourUrl(targetPath, activeTrack, activeMajor, activeMicro);
            return;
        }
        var start = function () {
            showMicroUi(step);
        };
        if (step.openNav) {
            openMobileNav(start);
        } else {
            start();
        }
    }
    function showGraduate(major, onDone) {
        stopTourUi();
        var titleEl = $('experience-graduate-title');
        var summaryEl = $('experience-graduate-summary');
        var nextEl = $('experience-graduate-next');
        var contBtn = $('experience-graduate-continue');
        var exitBtn = $('experience-graduate-exit');
        if (!titleEl || !contBtn) {
            if (window.YcNotice) {
                YcNotice.show({
                    level: 'ok',
                    text: (major.graduateSummary || '本大步已完成。') + (major.nextTitle ? ' 下一步：' + major.nextTitle : ''),
                    mustAck: true,
                    onClose: function () {
                        if (typeof onDone === 'function') {
                            onDone(!major.isLast && major.nextTitle);
                        }
                    },
                });
            }
            return;
        }
        if (titleEl) titleEl.textContent = major.graduateTitle || '本大步完成';
        if (summaryEl) summaryEl.textContent = major.graduateSummary || '';
        var hasNext = !major.isLast && major.nextTitle;
        if (nextEl) {
            nextEl.hidden = !hasNext;
            if (hasNext) nextEl.textContent = '下一大步：' + major.nextTitle;
        }
        if (contBtn) {
            contBtn.textContent = hasNext ? '继续下一大步' : '全部完成';
            contBtn.onclick = function () {
                hideModal('experience-graduate-modal');
                if (typeof onDone === 'function') onDone(hasNext);
            };
        }
        if (exitBtn) {
            exitBtn.onclick = function () {
                hideModal('experience-graduate-modal');
                clearSession();
            };
        }
        showModal('experience-graduate-modal');
        if (window.YcExperienceModal) window.YcExperienceModal.bindAll();
    }
    function retreatMicro() {
        clearAutoTimer();
        var major = currentMajor();
        if (!major || activeMicro <= 0) return;
        tourNavInstant = true;
        activeMicro -= 1;
        saveSession();
        runMicroStep();
    }
    function advanceMicro() {
        clearAutoTimer();
        tourNavInstant = false;
        var major = currentMajor();
        if (!major) return;
        var step = currentMicroStep();
        if (isActionStep(step)) {
            if (executeActionStep(step)) {
                return;
            }
        } else if (isSelectNameStep(step)) {
            if (executeSelectNameStep(step)) {
                return;
            }
        }
        activeMicro += 1;
        if (activeMicro >= major.microSteps.length) {
            activeMicro = major.microSteps.length - 1;
            showGraduate(major, function (goNext) {
                if (major.cleanupOnComplete) {
                    requestDemoCleanup();
                }
                if (!goNext) {
                    clearSession();
                    return;
                }
                navigateToMajor(activeTrack, activeMajor + 1);
            });
            return;
        }
        runMicroStep();
    }
    function startTrack(track, majorIndex) {
        if (!boot || !boot.enabled) {
            if (window.YcNotice) {
                YcNotice.show({
                    level: 'warning',
                    text: '暂未配置官方演示店，无法开始体验引导。',
                    mustAck: true,
                });
            }
            return;
        }
        hideExperienceWelcome();
        hideStepPicker();
        var list = majors(track);
        var idx = typeof majorIndex === 'number' ? majorIndex : 0;
        if (idx < 0 || idx >= list.length) idx = 0;
        navigateToMajor(track, idx);
    }
    function hideStepPicker() {
        hideModal('experience-step-picker-modal');
        pendingPickerTrack = null;
    }
    function showStepPicker(track) {
        if (!boot || !boot.enabled) {
            if (window.YcNotice) {
                YcNotice.show({
                    level: 'warning',
                    text: '暂未配置官方演示店，无法开始体验引导。',
                    mustAck: true,
                });
            }
            return;
        }
        var list = majors(track);
        if (!list.length) return;
        pendingPickerTrack = track;
        hideExperienceWelcome();
        var titleEl = $('experience-step-picker-title');
        var descEl = $('experience-step-picker-desc');
        var listEl = $('experience-step-picker-list');
        if (titleEl) {
            titleEl.textContent = track === 'seller' ? '体验开店 · 选大步' : '体验野草购物 · 选大步';
        }
        if (descEl) {
            descEl.textContent = '请选要从哪一大步开始；也可点下方「全部从头体验」。';
        }
        if (listEl) {
            listEl.innerHTML = '';
            list.forEach(function (major, i) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'experience-step-picker-item';
                btn.innerHTML = ''
                    + '<span class="experience-step-picker-num">' + (i + 1) + '</span>'
                    + '<span class="experience-step-picker-label">' + (major.title || ('第 ' + (i + 1) + ' 步')) + '</span>';
                btn.addEventListener('click', function () {
                    startTrack(track, i);
                });
                listEl.appendChild(btn);
            });
        }
        var allBtn = $('experience-step-picker-all');
        if (allBtn) {
            allBtn.onclick = function () {
                startTrack(track, 0);
            };
        }
        showModal('experience-step-picker-modal');
        if (window.YcExperienceModal) window.YcExperienceModal.bindAll();
    }
    function bindGraduateModal() {
        document.querySelectorAll('[data-experience-close="graduate"]').forEach(function (el) {
            if (el.dataset.ycTourGradBound) return;
            el.dataset.ycTourGradBound = '1';
            el.addEventListener('click', function () {
                hideModal('experience-graduate-modal');
                clearSession();
            });
        });
    }
    function bindExperienceHome() {
        document.querySelectorAll('[data-experience-start]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                showStepPicker(btn.getAttribute('data-experience-start'));
            });
        });
        var skipBtn = document.querySelector('[data-experience-skip-welcome]');
        if (skipBtn) skipBtn.addEventListener('click', hideExperienceWelcome);
        document.querySelectorAll('[data-experience-close="welcome"]').forEach(function (el) {
            el.addEventListener('click', hideExperienceWelcome);
        });
        document.querySelectorAll('[data-experience-close="picker"]').forEach(function (el) {
            el.addEventListener('click', hideStepPicker);
        });
    }
    function init() {
        boot = readBoot();
        if (!boot || !boot.enabled) return;
        bindGraduateModal();
        var isExperienceHome = document.body.classList.contains('experience-home-page');
        var isShowcaseHome = document.body.classList.contains('showcase-home-page');
        var isHome = isExperienceHome || isShowcaseHome;
        var params = new URLSearchParams(window.location.search);
        var tourActive = params.get(boot.urlFlag || 'exp') === '1';
        if (tourActive) {
            restoreFromUrl();
        } else if (!isHome) {
            restoreFromSession();
        }
        if (isHome) {
            bindExperienceHome();
            if ((isShowcaseHome || isExperienceHome) && !welcomeSeen()) {
                window.setTimeout(function () { showModal('experience-welcome-modal'); }, 400);
            }
        }
        if (activeTrack) {
            if (!isHome) {
                syncMicroToPage();
                bindExperienceMenuAjax();
                bindExperienceProductAjax();
            }
            if (tourActive) {
                window.setTimeout(runMicroStep, 300);
            } else if (!isHome) {
                window.setTimeout(runMicroStep, 300);
            }
        }
        window.YcExperience = { startTrack: startTrack, showStepPicker: showStepPicker, clearSession: clearSession };
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
