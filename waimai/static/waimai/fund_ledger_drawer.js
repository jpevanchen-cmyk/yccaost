/**
 * 资金流水 · 侧滑浮层（流水详情 / 订单摘要）
 */
(function () {
    var cfg = window.YC_FUND_LEDGER_DRAWER;
    if (!cfg) {
        return;
    }

    var drawer = document.getElementById('fund-ledger-drawer');
    var bodyEl = document.getElementById('fund-ledger-drawer-body');
    var titleEl = document.getElementById('fund-ledger-drawer-title');
    if (!drawer || !bodyEl || !titleEl) {
        return;
    }

    var PLACEHOLDER = '00000000-0000-0000-0000-000000000000';

    function buildUrl(template, id) {
        return (template || '').replace(PLACEHOLDER, id);
    }

    function setOpen(open) {
        drawer.hidden = !open;
        drawer.classList.toggle('is-open', open);
        drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
        document.body.classList.toggle('yc-detail-drawer-open', open);
    }

    function showLoading(title) {
        titleEl.textContent = title || '详情';
        bodyEl.innerHTML = '<p class="card-meta">加载中…</p>';
        setOpen(true);
    }

    function bindDrawerLinks(root) {
        var scope = root || document;
        scope.querySelectorAll('.yc-fl-drawer-link').forEach(function (btn) {
            if (btn.dataset.ycFlBound === '1') {
                return;
            }
            btn.dataset.ycFlBound = '1';
            btn.addEventListener('click', function (ev) {
                ev.preventDefault();
                var entryId = btn.getAttribute('data-yc-fl-entry');
                var orderId = btn.getAttribute('data-yc-fl-order');
                if (entryId) {
                    openEntry(entryId, btn.getAttribute('data-yc-fl-entry-label'));
                } else if (orderId) {
                    openOrder(orderId, btn.getAttribute('data-yc-fl-order-label'));
                }
            });
        });
    }

    function openEntry(ledgerId, label) {
        showLoading('流水 ' + (label || ''));
        fetch(buildUrl(cfg.entryUrlTemplate, ledgerId), {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        }).then(function (resp) {
            return resp.json();
        }).then(function (data) {
            if (!data || !data.ok) {
                bodyEl.innerHTML = '<p class="msg-err">' + ((data && data.message) || '加载失败') + '</p>';
                return;
            }
            bodyEl.innerHTML = data.html;
            bindDrawerLinks(bodyEl);
        }).catch(function () {
            bodyEl.innerHTML = '<p class="msg-err">加载失败，请检查网络后重试。</p>';
        });
    }

    function openOrder(orderId, label) {
        showLoading('订单 ' + (label || ''));
        fetch(buildUrl(cfg.orderUrlTemplate, orderId), {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        }).then(function (resp) {
            return resp.json();
        }).then(function (data) {
            if (!data || !data.ok) {
                bodyEl.innerHTML = '<p class="msg-err">' + ((data && data.message) || '加载失败') + '</p>';
                return;
            }
            bodyEl.innerHTML = data.html;
            bindDrawerLinks(bodyEl);
        }).catch(function () {
            bodyEl.innerHTML = '<p class="msg-err">加载失败，请检查网络后重试。</p>';
        });
    }

    drawer.querySelectorAll('[data-yc-fl-drawer-close]').forEach(function (el) {
        el.addEventListener('click', function () {
            setOpen(false);
        });
    });

    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && drawer.classList.contains('is-open')) {
            setOpen(false);
        }
    });

    bindDrawerLinks(document);
})();
