/**
 * 全站折叠卡片（§5.13）：卖家后台、工作台、订单详情等
 * 1）根据网址锚点自动展开对应区块
 * 2）手风琴：同层只开一块；嵌套组（data-yc-fold-group）内互不影响外层
 */
(function () {
    function allFolds() {
        return document.querySelectorAll('details.seller-panel-fold');
    }

    function foldGroup(fold) {
        if (!fold) return null;
        return fold.closest('[data-yc-fold-group]');
    }

    function closeOtherFolds(keep) {
        var keepGroup = foldGroup(keep);
        allFolds().forEach(function (other) {
            if (other === keep || !other.open) return;
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
                closeOtherFolds(fold);
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
                closeOtherFolds(fold);
            });
        });
    }

    function bindAccordion() {
        bindAccordionInScope(document);
    }

    window.ycOpenSellerFoldForHash = openSellerFoldForHash;
    window.ycRebindSellerPanelFold = bindAccordionInScope;
    bindAccordion();
    openSellerFoldForHash();
})();
