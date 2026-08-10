/**
 * 服务员桌台看板：固定格子总览 ↔ 单桌详情；复制加点链接；定时刷新桌态
 */
(function () {
    var POLL_MS = 30000;
    var pollTimer = null;

    function fullAddonUrl(path) {
        path = (path || '').trim();
        if (!path) return '';
        return path.indexOf('http') === 0 ? path : (window.location.origin + path);
    }

    function showGridView(shell) {
        if (!shell) return;
        var grid = shell.querySelector('#waiter-table-grid-view');
        if (grid) grid.hidden = false;
        shell.querySelectorAll('.waiter-table-detail-view').forEach(function (el) {
            el.hidden = true;
        });
        try {
            sessionStorage.removeItem('yc_waiter_table_detail');
        } catch (e) { /* 忽略 */ }
    }

    function showDetailView(shell, detailId) {
        if (!shell || !detailId) return;
        var grid = shell.querySelector('#waiter-table-grid-view');
        if (grid) grid.hidden = true;
        shell.querySelectorAll('.waiter-table-detail-view').forEach(function (el) {
            el.hidden = el.id !== detailId;
        });
        try {
            sessionStorage.setItem('yc_waiter_table_detail', detailId);
        } catch (e) { /* 忽略 */ }
    }

    function restoreDetailIfAny(shell) {
        if (!shell) return;
        var saved = '';
        try {
            saved = sessionStorage.getItem('yc_waiter_table_detail') || '';
        } catch (e) { /* 忽略 */ }
        if (saved && shell.querySelector('#' + saved)) {
            showDetailView(shell, saved);
        } else {
            showGridView(shell);
        }
    }

    function bindCopyAddon(scope) {
        (scope || document).querySelectorAll('.yc-waiter-copy-addon').forEach(function (btn) {
            if (btn.dataset.ycCopyBound === '1') return;
            btn.dataset.ycCopyBound = '1';
            btn.addEventListener('click', function () {
                var url = fullAddonUrl(btn.getAttribute('data-addon-path'));
                if (!url) return;
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(url).then(function () {
                        btn.textContent = '已复制';
                        setTimeout(function () {
                            btn.textContent = '复制链接（备用）';
                        }, 2000);
                    });
                } else {
                    window.prompt('请复制加点链接', url);
                }
            });
        });
    }

    function bindTableBoard(scope) {
        var root = scope || document;
        root.querySelectorAll('.waiter-table-board-shell').forEach(function (shell) {
            if (shell.dataset.ycTableBoardBound === '1') return;
            shell.dataset.ycTableBoardBound = '1';

            shell.querySelectorAll('.waiter-table-tile').forEach(function (tile) {
                tile.addEventListener('click', function () {
                    showDetailView(shell, tile.getAttribute('data-table-detail-id'));
                });
            });

            shell.querySelectorAll('.yc-waiter-table-back').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    showGridView(shell);
                });
            });

            restoreDetailIfAny(shell);
        });
        bindCopyAddon(root);
    }

    function pollUrl() {
        var cfg = window.YC_WAITER_TABLE_BOARD;
        if (cfg && cfg.pollUrl) return cfg.pollUrl;
        return '';
    }

    function pollTableBoard() {
        var url = pollUrl();
        var body = document.getElementById('waiter-table-board-body');
        if (!url || !body) return;
        var shell = body.querySelector('.waiter-table-board-shell');
        if (shell) {
            var grid = shell.querySelector('#waiter-table-grid-view');
            if (grid && grid.hidden) return;
        }
        if (document.visibilityState && document.visibilityState !== 'visible') return;
        var header = (window.YcaoPanel && window.YcaoPanel.refreshHeader) || 'YecaoPanel';
        fetch(url, {
            method: 'GET',
            headers: { 'X-Requested-With': header },
            credentials: 'same-origin',
        })
            .then(function (r) { return r.json(); })
            .then(applyPollHtml)
            .catch(function () { /* 静默失败，不打扰服务员 */ });
    }

    function applyPollHtml(data) {
        var body = document.getElementById('waiter-table-board-body');
        if (!body || !data || !data.html) return;
        body.innerHTML = data.html;
        bindTableBoard(body);
    }

    function startPoll() {
        if (pollTimer || !pollUrl()) return;
        pollTimer = window.setInterval(pollTableBoard, POLL_MS);
    }

    function stopPoll() {
        if (pollTimer) {
            window.clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    window.ycRebindWaiterTableBoard = function (scope) {
        bindTableBoard(scope || document);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            bindTableBoard(document);
            startPoll();
        });
    } else {
        bindTableBoard(document);
        startPoll();
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            pollTableBoard();
        }
    });

    window.addEventListener('pagehide', stopPoll);
})();
