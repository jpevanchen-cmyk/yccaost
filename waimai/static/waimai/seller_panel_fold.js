/**
 * 卖家后台折叠模块：根据网址锚点自动展开对应区块（须在 mobile.js 恢复滚动前执行）
 */
(function () {
    function openSellerFoldForHash() {
        var hash = window.location.hash ? window.location.hash.slice(1) : '';
        if (!hash) return;
        var target = document.getElementById(hash);
        if (target) {
            var fold = target.classList.contains('seller-panel-fold')
                ? target
                : target.closest('.seller-panel-fold');
            if (fold && fold.tagName === 'DETAILS') {
                fold.open = true;
            }
            return;
        }
        /* 商品行 / 编辑区锚点：展开商品管理模块 */
        if (hash.indexOf('dish-') === 0 || hash.indexOf('edit-') === 0) {
            var list = document.getElementById('product-list');
            if (list && list.tagName === 'DETAILS') {
                list.open = true;
            }
        }
    }

    window.ycOpenSellerFoldForHash = openSellerFoldForHash;
    openSellerFoldForHash();
})();
