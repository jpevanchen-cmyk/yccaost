/**
 * 全站折叠卡片（§5.13）：卖家后台、工作台、订单详情等
 * 1）根据网址锚点自动展开对应区块
 * 2）同一页同一时间只开一块：点开一个就关掉其它已开的
 */
(function () {
    function allFolds() {
        return document.querySelectorAll('details.seller-panel-fold');
    }

    function closeOtherFolds(keep) {
        allFolds().forEach(function (other) {
            if (other !== keep && other.open) {
                other.open = false;
            }
        });
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
                closeOtherFolds(fold);
                fold.open = true;
            }
            return;
        }
        /* 商品行 / 编辑区锚点：展开商品管理模块 */
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
