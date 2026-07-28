/**
 * H4 新手体验引导：幻灯片式小步演示（高亮 + 说明卡片 + 假输入）
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
    var tourExitBtn = null;
    var resizeHandler = null;
    var typingTimer = null;
    var positionTimer = null;
    var autoTimer = null;

    function isTourVisible() {
        return !!(tourRoot && !tourRoot.hidden && activeTrack);
    }

    function cleanTourUrl() {
        if (!window.history || !window.history.replaceState) return;
        try {
            var url = new URL(window.location.href);
            if (!url.searchParams.has('yc_tour')) return;
            url.searchParams.delete('yc_tour');
            url.searchParams.delete('yc_track');
            url.searchParams.delete('yc_major');
            url.searchParams.delete('yc_micro');
            var q = url.searchParams.toString();
            window.history.replaceState({}, '', url.pathname + (q ? '?' + q : '') + url.hash);
        } catch (e) { /* 忽略 */ }
    }
    function readBoot() {
        var el = document.getElementById('yc-onboarding-boot');
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
        activeTrack = null;
        activeMajor = 0;
        activeMicro = 0;
        if (boot && window.sessionStorage) {
            sessionStorage.removeItem(boot.sessionTrackKey);
            sessionStorage.removeItem(boot.sessionMajorKey);
            sessionStorage.removeItem(boot.sessionMicroKey);
        }
        hideModal('onboarding-graduate-modal');
        stopTourUi();
        cleanTourUrl();
    }
    function restoreFromUrl() {
        var params = new URLSearchParams(window.location.search);
        if (params.get('yc_tour') !== '1') return false;
        var track = params.get('yc_track');
        if (!track) return false;
        activeTrack = track;
        activeMajor = parseInt(params.get('yc_major') || '0', 10);
        activeMicro = parseInt(params.get('yc_micro') || '0', 10);
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
    function hideWelcome() {
        hideModal('onboarding-welcome-modal');
        markWelcomeSeen();
    }
    function pageKeyFromPath(path) {
        path = path || window.location.pathname;
        if (path === '/' || path === '/directory/') return 'home';
        if (path.indexOf('/shop-register') === 0) return 'shop_register';
        if (path.indexOf('/register') === 0) return 'register';
        if (path.indexOf('/shop') === 0) return 'shop';
        if (path.indexOf('/onboarding/preview/seller/operating') === 0) return 'preview_operating';
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
    function buildTourUrl(path, track, major, micro) {
        var base = path.split('?')[0];
        var qs = new URLSearchParams(path.indexOf('?') >= 0 ? path.split('?')[1] : '');
        qs.set('yc_tour', '1');
        qs.set('yc_track', track);
        qs.set('yc_major', String(major));
        qs.set('yc_micro', String(micro));
        return base + '?' + qs.toString();
    }
    function ensureTourDom() {
        if (tourRoot) return;
        tourRoot = document.createElement('div');
        tourRoot.id = 'yc-tour-root';
        tourRoot.hidden = true;
        tourRoot.innerHTML = ''
            + '<div class="yc-tour-backdrop"></div>'
            + '<div class="yc-tour-spotlight" aria-hidden="true"></div>'
            + '<div class="yc-tour-card card" role="dialog" aria-modal="true">'
            + '<p class="yc-tour-progress"></p>'
            + '<h3 class="yc-tour-title"></h3>'
            + '<p class="yc-tour-body card-meta"></p>'
            + '<ul class="yc-tour-tips"></ul>'
            + '<p class="yc-tour-warn"></p>'
            + '<p class="yc-tour-auto-count card-meta" hidden></p>'
            + '<div class="yc-tour-actions">'
            + '<button type="button" class="btn btn-orange btn-block yc-tour-next">下一小步</button>'
            + '<button type="button" class="btn btn-sm btn-outline btn-block yc-tour-exit">退出体验</button>'
            + '</div></div>';
        document.body.appendChild(tourRoot);
        document.body.classList.add('yc-tour-active');
        tourBackdrop = tourRoot.querySelector('.yc-tour-backdrop');
        tourSpotlight = tourRoot.querySelector('.yc-tour-spotlight');
        tourCard = tourRoot.querySelector('.yc-tour-card');
        tourProgress = tourRoot.querySelector('.yc-tour-progress');
        tourTitle = tourRoot.querySelector('.yc-tour-title');
        tourBody = tourRoot.querySelector('.yc-tour-body');
        tourTips = tourRoot.querySelector('.yc-tour-tips');
        tourWarn = tourRoot.querySelector('.yc-tour-warn');
        tourAutoCountdown = tourRoot.querySelector('.yc-tour-auto-count');
        tourNextBtn = tourRoot.querySelector('.yc-tour-next');
        tourExitBtn = tourRoot.querySelector('.yc-tour-exit');
        tourNextBtn.addEventListener('click', advanceMicro);
        tourExitBtn.addEventListener('click', function () {
            clearSession();
        });
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
                    ev.preventDefault();
                    if (window.YcNotice) {
                        YcNotice.show({
                            level: 'warning',
                            text: '体验引导中不会真提交表单；请点「下一小步」继续，或「退出体验」。',
                            mustAck: true,
                        });
                    }
                }
            });
        });
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
        return def;
    }
    function updateAutoCountdownUi(secs, isLastMicro) {
        if (!tourAutoCountdown) return;
        if (secs <= 0) {
            tourAutoCountdown.hidden = true;
            return;
        }
        tourAutoCountdown.hidden = false;
        var action = isLastMicro ? '本步完成' : '下一小步';
        tourAutoCountdown.textContent = secs + ' 秒后自动' + action;
    }
    function startAutoAdvance(step) {
        clearAutoTimer();
        if (!step) return;
        var secs = stepAutoSeconds(step);
        if (!secs || secs <= 0) {
            if (tourAutoCountdown) tourAutoCountdown.hidden = true;
            return;
        }
        var major = currentMajor();
        var isLastMicro = major && activeMicro >= major.microSteps.length - 1;
        updateAutoCountdownUi(secs, isLastMicro);
        autoTimer = window.setInterval(function () {
            secs -= 1;
            if (secs <= 0) {
                clearAutoTimer();
                if (tourAutoCountdown) tourAutoCountdown.hidden = true;
                advanceMicro();
                return;
            }
            updateAutoCountdownUi(secs, isLastMicro);
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
        if (tourRoot) tourRoot.hidden = true;
        document.body.classList.remove('yc-tour-active');
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
    function runTypeDemo(el, text) {
        if (!el || el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') return;
        el.value = '';
        el.focus({ preventScroll: true });
        var i = 0;
        if (typingTimer) clearInterval(typingTimer);
        typingTimer = window.setInterval(function () {
            if (i >= text.length) {
                clearInterval(typingTimer);
                typingTimer = null;
                return;
            }
            el.value += text.charAt(i);
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
        placeCard(rect);
    }
    function repositionSpotlightOnly(step) {
        if (!isTourVisible() || !step) return;
        applySpotlightRect(findTarget(step.selector), 8);
    }
    function positionTour(step) {
        if (!tourRoot || !step || !isTourVisible()) return;
        if (positionTimer) {
            clearTimeout(positionTimer);
            positionTimer = null;
        }
        var target = findTarget(step.selector);
        var pad = 8;
        if (target) {
            target.scrollIntoView({ block: 'center', behavior: 'smooth' });
            positionTimer = window.setTimeout(function () {
                positionTimer = null;
                if (!isTourVisible()) return;
                applySpotlightRect(target, pad);
            }, 280);
        } else {
            applySpotlightRect(null, pad);
        }
    }
    function placeCard(rect) {
        if (!tourCard) return;
        tourCard.style.top = '';
        tourCard.style.bottom = '';
        tourCard.style.left = '50%';
        tourCard.style.transform = 'translateX(-50%)';
        if (!rect) {
            tourCard.style.top = '18vh';
            return;
        }
        var cardH = tourCard.offsetHeight || 220;
        var margin = 12;
        var below = rect.bottom + 16;
        if (below + cardH < window.innerHeight - margin) {
            tourCard.style.top = below + 'px';
        } else {
            var above = rect.top - cardH - 16;
            tourCard.style.top = Math.max(margin, Math.min(above, window.innerHeight - cardH - margin)) + 'px';
        }
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
        var isLastMicro = activeMicro >= major.microSteps.length - 1;
        tourNextBtn.textContent = isLastMicro ? '本步完成' : '下一小步';
    }
    function showMicroUi(step) {
        ensureTourDom();
        fillTourCard(step);
        tourRoot.hidden = false;
        document.body.classList.add('yc-tour-active');
        if (step.openFold) {
            openFoldSelector(step.openFold);
        }
        if (step.demoClick) {
            runDemoClick(step.demoClick);
        }
        positionTour(step);
        if (step.demoType === 'type' && step.demoText && step.selector) {
            window.setTimeout(function () {
                runTypeDemo(findTarget(step.selector), step.demoText);
            }, 400);
        }
        window.setTimeout(function () {
            if (!isTourVisible() || currentMicroStep() !== step) return;
            startAutoAdvance(step);
        }, 350);
    }
    function runMicroStep() {
        var step = currentMicroStep();
        var major = currentMajor();
        if (!step || !major) {
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
        var titleEl = $('onboarding-graduate-title');
        var summaryEl = $('onboarding-graduate-summary');
        var nextEl = $('onboarding-graduate-next');
        var contBtn = $('onboarding-graduate-continue');
        var exitBtn = $('onboarding-graduate-exit');
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
                hideModal('onboarding-graduate-modal');
                if (typeof onDone === 'function') onDone(hasNext);
            };
        }
        if (exitBtn) {
            exitBtn.onclick = function () {
                hideModal('onboarding-graduate-modal');
                clearSession();
            };
        }
        showModal('onboarding-graduate-modal');
    }
    function advanceMicro() {
        clearAutoTimer();
        var major = currentMajor();
        if (!major) return;
        activeMicro += 1;
        if (activeMicro >= major.microSteps.length) {
            activeMicro = major.microSteps.length - 1;
            showGraduate(major, function (goNext) {
                if (!goNext) {
                    clearSession();
                    return;
                }
                activeMajor += 1;
                activeMicro = 0;
                var list = majors(activeTrack);
                if (activeMajor >= list.length) {
                    clearSession();
                    return;
                }
                runMicroStep();
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
        hideWelcome();
        hideStepPicker();
        activeTrack = track;
        var list = majors(track);
        var idx = typeof majorIndex === 'number' ? majorIndex : 0;
        if (idx < 0 || idx >= list.length) idx = 0;
        activeMajor = idx;
        activeMicro = 0;
        saveSession();
        runMicroStep();
    }
    function hideStepPicker() {
        hideModal('onboarding-step-picker-modal');
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
        hideWelcome();
        var titleEl = $('onboarding-step-picker-title');
        var descEl = $('onboarding-step-picker-desc');
        var listEl = $('onboarding-step-picker-list');
        if (titleEl) {
            titleEl.textContent = track === 'seller' ? '体验野草开店 · 选大步' : '体验野草购物 · 选大步';
        }
        if (descEl) {
            descEl.textContent = '请选要从哪一大步开始；也可点下方「全部从头体验」。';
        }
        if (listEl) {
            listEl.innerHTML = '';
            list.forEach(function (major, i) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'onboarding-step-picker-item';
                btn.innerHTML = ''
                    + '<span class="onboarding-step-picker-num">' + (i + 1) + '</span>'
                    + '<span class="onboarding-step-picker-label">' + (major.title || ('第 ' + (i + 1) + ' 步')) + '</span>';
                btn.addEventListener('click', function () {
                    startTrack(track, i);
                });
                listEl.appendChild(btn);
            });
        }
        var allBtn = $('onboarding-step-picker-all');
        if (allBtn) {
            allBtn.onclick = function () {
                startTrack(track, 0);
            };
        }
        showModal('onboarding-step-picker-modal');
    }
    function bindGraduateModal() {
        document.querySelectorAll('[data-onboarding-close="graduate"]').forEach(function (el) {
            if (el.dataset.ycTourGradBound) return;
            el.dataset.ycTourGradBound = '1';
            el.addEventListener('click', function () {
                hideModal('onboarding-graduate-modal');
                clearSession();
            });
        });
    }
    function bindHomePage() {
        document.querySelectorAll('[data-onboarding-start]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                showStepPicker(btn.getAttribute('data-onboarding-start'));
            });
        });
        var skipBtn = document.querySelector('[data-onboarding-skip-welcome]');
        if (skipBtn) skipBtn.addEventListener('click', hideWelcome);
        document.querySelectorAll('[data-onboarding-close="welcome"]').forEach(function (el) {
            el.addEventListener('click', hideWelcome);
        });
        document.querySelectorAll('[data-onboarding-close="picker"]').forEach(function (el) {
            el.addEventListener('click', hideStepPicker);
        });
    }
    function init() {
        boot = readBoot();
        if (!boot || !boot.enabled) return;
        bindGraduateModal();
        var isHome = document.body.classList.contains('showcase-home-page');
        var params = new URLSearchParams(window.location.search);
        var tourActive = params.get('yc_tour') === '1';
        if (tourActive) {
            restoreFromUrl();
        } else if (!isHome) {
            restoreFromSession();
        }
        if (isHome) {
            bindHomePage();
            if (!welcomeSeen()) {
                window.setTimeout(function () { showModal('onboarding-welcome-modal'); }, 400);
            }
        }
        if (activeTrack) {
            if (tourActive) {
                window.setTimeout(runMicroStep, 300);
            } else if (!isHome) {
                window.setTimeout(runMicroStep, 300);
            }
        }
        window.YcOnboarding = { startTrack: startTrack, showStepPicker: showStepPicker, clearSession: clearSession };
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
