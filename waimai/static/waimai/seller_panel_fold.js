/**
 * 全站折叠卡片（§5.13）：卖家后台、工作台、订单详情等
 * 1）根据网址锚点自动展开对应区块
 * 2）手风琴：同层只开一块；嵌套组（data-yc-fold-group）内互不影响外层
 * 3）多开区（data-yc-fold-multi）：区内卡片可同时展开，互不自动收起
 * 4）全关区（data-yc-fold-close-all）：ESC、点卡片外空白 → 区内全部收起
 */
(function () {
    function allFolds() {
        return document.querySelectorAll('details.seller-panel-fold');
    }

    function foldGroup(fold) {
        if (!fold) return null;
        return fold.closest('[data-yc-fold-group]');
    }

    function isMultiFold(fold) {
        return !!(fold && fold.closest('[data-yc-fold-multi]'));
    }

    function closeOtherFolds(keep) {
        if (isMultiFold(keep)) return;
        var keepGroup = foldGroup(keep);
        allFolds().forEach(function (other) {
            if (other === keep || !other.open) return;
            if (isMultiFold(other)) return;
            // 嵌套：不要关掉祖先或后代（避免点子卡片收起大标题）
            if (other.contains(keep) || keep.contains(other)) return;
            var otherGroup = foldGroup(other);
            if (keepGroup) {
                if (otherGroup === keepGroup) {
                    other.open = false;
                }
                return;
            }
            if (!otherGroup) {
                other.open = false;
            }
        });
    }

    function openAncestorFolds(fold) {
        var node = fold.parentElement;
        while (node) {
            if (node.tagName === 'DETAILS' && node.classList.contains('seller-panel-fold')) {
                node.open = true;
            }
            node = node.parentElement;
        }
    }

    function openSellerFoldForHash() {
        var hash = window.location.hash ? window.location.hash.slice(1) : '';
        if (!hash) return;
        var target = document.getElementById(hash);
        if (target) {
            var fold = target.classList.contains('seller-panel-fold')
                ? target
                : target.closest('.seller-panel-fold');
            if (fold && fold.tagName === 'DETAILS') {
                openAncestorFolds(fold);
                if (!isMultiFold(fold)) {
                    closeOtherFolds(fold);
                }
                fold.open = true;
            }
            return;
        }
        if (hash.indexOf('dish-') === 0 || hash.indexOf('edit-') === 0) {
            var list = document.getElementById('product-list');
            if (list && list.tagName === 'DETAILS') {
                closeOtherFolds(list);
                list.open = true;
            }
        }
    }

    function bindAccordionInScope(root) {
        var scope = root || document;
        scope.querySelectorAll('details.seller-panel-fold').forEach(function (fold) {
            if (fold.dataset.ycFoldAccordionBound === '1') return;
            fold.dataset.ycFoldAccordionBound = '1';
            fold.addEventListener('toggle', function () {
                if (!fold.open) return;
                if (isMultiFold(fold)) return;
                closeOtherFolds(fold);
            });
        });
    }

    function bindAccordion() {
        bindAccordionInScope(document);
    }

    function closeFoldsIn(root) {
        if (!root) return;
        root.querySelectorAll('details.seller-panel-fold').forEach(function (fold) {
            fold.open = false;
        });
    }

    function closeAllMarkedRegions() {
        document.querySelectorAll('[data-yc-fold-close-all]').forEach(closeFoldsIn);
    }

    function bindCloseAll() {
        if (document.documentElement.dataset.ycFoldCloseAllBound === '1') return;
        document.documentElement.dataset.ycFoldCloseAllBound = '1';
        document.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Escape' && ev.key !== 'Esc') return;
            closeAllMarkedRegions();
        });
        document.addEventListener('click', function (ev) {
            var target = ev.target;
            if (!target || !target.closest) return;
            if (target.closest('details.seller-panel-fold')) return;
            var region = target.closest('[data-yc-fold-close-all]');
            if (region) {
                closeFoldsIn(region);
                return;
            }
            if (target === document.body || target.tagName === 'MAIN' || (target.classList && target.classList.contains('site-main'))) {
                closeAllMarkedRegions();
            }
        });
    }

    window.ycOpenSellerFoldForHash = openSellerFoldForHash;
    window.ycRebindSellerPanelFold = bindAccordionInScope;
    bindAccordion();
    bindCloseAll();
    openSellerFoldForHash();
})();
