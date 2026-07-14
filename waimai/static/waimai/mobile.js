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
        if (!anchorId || anchorId === 'cart') return;
        var el = document.getElementById(anchorId);
        if (!el) return;
        el.scrollIntoView({ block: 'center', behavior: 'auto' });
        el.classList.add('scroll-flash');
        setTimeout(function () {
            el.classList.remove('scroll-flash');
        }, 1200);
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
                scrollToAnchor(anchor);
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

    // 所有 POST 表单：提交前记住滚动位置（全站通用）
    document.querySelectorAll('form').forEach(function (form) {
        if (!form.method || form.method.toLowerCase() !== 'post') return;
        form.addEventListener('submit', function () {
            saveScrollBeforeSubmit(form);
        });
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
    var cartOpenBtns = document.querySelectorAll('[data-cart-open]');
    var cartCloseBtns = document.querySelectorAll('[data-cart-close]');

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

    cartOpenBtns.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            openCart();
        });
    });

    cartCloseBtns.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            closeCart();
        });
    });

    var cartBackdrop = document.querySelector('.cart-drawer-backdrop');
    if (cartBackdrop) {
        cartBackdrop.addEventListener('click', function (e) {
            e.preventDefault();
            closeCart();
        });
        cartBackdrop.addEventListener('touchmove', function (e) {
            e.preventDefault();
        }, { passive: false });
    }

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
