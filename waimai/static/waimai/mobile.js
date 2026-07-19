/**
 * 野草系统 · 手机端交互（菜单、购物车、滚动位置保持）
 */
(function () {
    var SCROLL_Y_KEY = 'ycScrollY';
    var SCROLL_ANCHOR_KEY = 'ycScrollTo';
    var cartScrollY = 0;

    function getEffectiveScrollY() {
        /* 购物车打开时整页被锁住，要用打开前记住的位置 */
        if (document.body.classList.contains('cart-open') && document.body.style.top) {
            var top = parseInt(document.body.style.top, 10);
            if (!isNaN(top)) {
                return Math.abs(top);
            }
        }
        return window.scrollY || document.documentElement.scrollTop || 0;
    }

    function scrollToAnchor(anchorId) {
        if (!anchorId || anchorId === 'cart') return false;
        var el = document.getElementById(anchorId);
        if (!el) return false;
        el.scrollIntoView({ block: 'center', behavior: 'auto' });
        el.classList.add('scroll-flash');
        setTimeout(function () {
            el.classList.remove('scroll-flash');
        }, 1200);
        return true;
    }

    function saveScrollBeforeSubmit(form) {
        try {
            sessionStorage.setItem(SCROLL_Y_KEY, String(getEffectiveScrollY()));
        } catch (e) { /* 忽略 */ }

        var anchor = form.getAttribute('data-scroll-anchor');
        if (!anchor) {
            var row = form.closest('[id]');
            if (row) anchor = row.id;
        }
        if (anchor) {
            try {
                sessionStorage.setItem(SCROLL_ANCHOR_KEY, anchor);
            } catch (e) { /* 忽略 */ }
        }
    }

    function restoreScrollPosition(onDone) {
        /* 卖家折叠模块：先展开锚点所在区块，再滚动定位 */
        if (typeof window.ycOpenSellerFoldForHash === 'function') {
            window.ycOpenSellerFoldForHash();
        }
        var hash = window.location.hash ? window.location.hash.slice(1) : '';
        var savedY = null;
        var savedAnchor = null;
        try {
            savedY = sessionStorage.getItem(SCROLL_Y_KEY);
            savedAnchor = sessionStorage.getItem(SCROLL_ANCHOR_KEY);
            if (savedY !== null) sessionStorage.removeItem(SCROLL_Y_KEY);
            if (savedAnchor) sessionStorage.removeItem(SCROLL_ANCHOR_KEY);
        } catch (e) { /* 忽略 */ }

        var done = function () {
            if (onDone) onDone();
        };

        /* 购物车操作：先恢复背后页面的滚动，再打开抽屉 */
        if (hash === 'cart') {
            if (savedY !== null && savedY !== '') {
                var cartY = parseInt(savedY, 10);
                if (!isNaN(cartY) && cartY >= 0) {
                    setTimeout(function () {
                        window.scrollTo(0, cartY);
                        done();
                    }, 50);
                    return;
                }
            }
            done();
            return;
        }

        var anchor = hash || savedAnchor || '';
        if (anchor) {
            setTimeout(function () {
                var found = scrollToAnchor(anchor);
                // 锚点对不上时（如旧链接缺档位后缀），退回提交前记下的纵向位置，避免滚回顶部
                if (!found && savedY !== null && savedY !== '') {
                    var fallbackY = parseInt(savedY, 10);
                    if (!isNaN(fallbackY) && fallbackY > 0) {
                        window.scrollTo(0, fallbackY);
                    }
                }
                done();
            }, 50);
            return;
        }

        if (savedY !== null && savedY !== '') {
            var y = parseInt(savedY, 10);
            if (!isNaN(y) && y > 0) {
                setTimeout(function () {
                    window.scrollTo(0, y);
                    done();
                }, 50);
                return;
            }
        }
        done();
    }

    /** 防止菜单/购物车锁滚动后 class 残留导致整页无法滑动 */
    function ensureBodyScrollable() {
        var cartDrawer = document.getElementById('cart-drawer');
        var nav = document.getElementById('site-nav');
        var cartOpen = cartDrawer && cartDrawer.classList.contains('is-open');
        var navOpen = nav && nav.classList.contains('is-open');

        if (!cartOpen && document.body.classList.contains('cart-open')) {
            document.body.classList.remove('cart-open');
            document.body.style.top = '';
        }
        if (!navOpen && document.body.classList.contains('nav-open')) {
            document.body.classList.remove('nav-open');
        }
    }

    // 所有普通 POST：提交前记住滚动位置；无刷新购物车不需要记位置
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || !form.method || form.method.toLowerCase() !== 'post') return;
        if (isAsyncCartForm(form)) return;
        saveScrollBeforeSubmit(form);
    });

    ensureBodyScrollable();

    // 顶栏汉堡菜单
    var toggle = document.getElementById('nav-toggle');
    var nav = document.getElementById('site-nav');
    var overlay = document.getElementById('nav-overlay');

    function closeNav() {
        if (nav) nav.classList.remove('is-open');
        if (overlay) overlay.classList.remove('is-open');
        document.body.classList.remove('nav-open');
    }

    function openNav() {
        if (nav) nav.classList.add('is-open');
        if (overlay) overlay.classList.add('is-open');
        document.body.classList.add('nav-open');
    }

    if (toggle && nav) {
        toggle.addEventListener('click', function () {
            if (nav.classList.contains('is-open')) {
                closeNav();
            } else {
                openNav();
            }
        });
    }

    if (overlay) {
        overlay.addEventListener('click', closeNav);
    }

    if (nav) {
        nav.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', closeNav);
        });
    }

    // 店铺页购物车抽屉
    var cartDrawer = document.getElementById('cart-drawer');

    function lockPageBehindCart() {
        cartScrollY = getEffectiveScrollY();
        document.body.classList.add('cart-open');
        document.body.style.top = '-' + cartScrollY + 'px';
    }

    function unlockPageBehindCart() {
        document.body.classList.remove('cart-open');
        document.body.style.top = '';
        window.scrollTo(0, cartScrollY);
    }

    function openCart() {
        lockPageBehindCart();
        if (cartDrawer) cartDrawer.classList.add('is-open');
    }

    function closeCart() {
        if (cartDrawer) cartDrawer.classList.remove('is-open');
        unlockPageBehindCart();
    }

    // 用统一点击监听，购物车外壳被无刷新替换后仍然有效
    document.addEventListener('click', function (e) {
        var openBtn = e.target.closest ? e.target.closest('[data-cart-open]') : null;
        if (openBtn) {
            e.preventDefault();
            cartDrawer = document.getElementById('cart-drawer');
            openCart();
            return;
        }
        var closeBtn = e.target.closest ? e.target.closest('[data-cart-close]') : null;
        if (closeBtn) {
            e.preventDefault();
            e.stopPropagation();
            closeCart();
        }
    });

    document.addEventListener('touchmove', function (e) {
        if (e.target.closest && e.target.closest('.cart-drawer-backdrop')) {
            e.preventDefault();
        }
    }, { passive: false });

    function cartAction(form) {
        var input = form && form.querySelector('input[name="action"]');
        return input ? input.value : '';
    }

    function isAsyncCartForm(form) {
        var action = cartAction(form);
        return !!document.getElementById('shop-cart-shell')
            && ['add_to_cart', 'decrease_from_cart', 'remove_from_cart'].indexOf(action) !== -1;
    }

    function preserveCheckoutFields() {
        var values = {};
        document.querySelectorAll('#shop-cart-shell [name="delivery_address"], #shop-cart-shell [name="distance_km"]:checked').forEach(function (field) {
            if (!(field.name in values) || field.closest('.cart-drawer')) {
                values[field.name] = field.value;
            }
        });
        return values;
    }

    function restoreCheckoutFields(values) {
        Object.keys(values || {}).forEach(function (name) {
            document.querySelectorAll('#shop-cart-shell [name="' + name + '"]').forEach(function (field) {
                if (field.type === 'radio') {
                    field.checked = field.value === values[name];
                } else {
                    field.value = values[name];
                }
            });
        });
    }

    // 加购、减数量、删除：只替换购物车，不刷新整页
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!isAsyncCartForm(form)) return;
        e.preventDefault();

        var submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        var drawerWasOpen = !!(document.getElementById('cart-drawer')
            && document.getElementById('cart-drawer').classList.contains('is-open'));
        var checkoutValues = preserveCheckoutFields();

        // 注意：表单里有 name="action" 隐藏域，会把 form.action 覆盖成输入框对象，
        // 必须用 getAttribute 或当前网址，不能直接读 form.action。
        var postUrl = form.getAttribute('action') || window.location.href;

        fetch(postUrl, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'YecaoCart' }
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok || !data.ok) {
                        throw new Error(data.message || '购物车操作失败，请稍后再试');
                    }
                    return data;
                });
            })
            .then(function (data) {
                var shell = document.getElementById('shop-cart-shell');
                if (!shell) return;
                shell.innerHTML = data.cart_shell_html;
                restoreCheckoutFields(checkoutValues);
                cartDrawer = document.getElementById('cart-drawer');
                if (drawerWasOpen && cartDrawer) {
                    openCart();
                } else if (drawerWasOpen) {
                    unlockPageBehindCart();
                }
            })
            .catch(function (err) {
                window.alert(err.message || '购物车操作失败，请稍后再试');
                if (submitBtn) submitBtn.disabled = false;
            });
    });

    restoreScrollPosition(function () {
        if (window.location.hash === '#cart' && cartDrawer) {
            setTimeout(openCart, 80);
        }
    });

    window.addEventListener('pageshow', function () {
        ensureBodyScrollable();
    });

    document.querySelectorAll('.page-back-btn--history').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = '/directory/';
            }
        });
    });
})();
