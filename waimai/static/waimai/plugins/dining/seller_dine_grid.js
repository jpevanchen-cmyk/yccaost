/**
 * 饮食插件静态资源：堂食营业桌号 / 虚拟码网格点选、批量操作、删除二次确认
 * （原 waimai/seller_dine_grid.js）
 */
(function () {
    function initCodeGrid(cfg) {
        var grid = document.getElementById(cfg.gridId);
        var form = document.getElementById(cfg.formId);
        var actionInput = document.getElementById(cfg.actionInputId);
        var hint = document.getElementById(cfg.hintId);
        var pathsBox = document.getElementById(cfg.pathsBoxId);
        if (!grid || !form) return;

        function selectedChips() {
            return grid.querySelectorAll('.code-chip.is-selected');
        }

        function updateHint() {
            var n = selectedChips().length;
            if (!hint) return;
            if (!n) {
                hint.textContent = cfg.emptyHint;
                return;
            }
            var labels = [];
            selectedChips().forEach(function (chip) {
                labels.push(chip.getAttribute('data-label'));
            });
            hint.textContent = '已选 ' + n + ' 个：' + labels.join('、');
        }

        function syncHiddenIds() {
            form.querySelectorAll('input[name="selected_ids"]').forEach(function (el) {
                el.remove();
            });
            selectedChips().forEach(function (chip) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'selected_ids';
                input.value = chip.getAttribute('data-id');
                form.appendChild(input);
            });
        }

        function renderScanPaths() {
            if (!pathsBox) return;
            pathsBox.innerHTML = '';
            var chips = grid.querySelectorAll('.code-chip');
            chips.forEach(function (chip) {
                var row = document.createElement('div');
                row.className = 'scan-path-row';
                row.innerHTML = '<strong>' + chip.getAttribute('data-label') + '</strong> ' +
                    '<code>' + chip.getAttribute('data-scan') + '</code>';
                pathsBox.appendChild(row);
            });
        }

        grid.addEventListener('click', function (e) {
            var chip = e.target.closest('.code-chip');
            if (!chip) return;
            chip.classList.toggle('is-selected');
            updateHint();
            syncHiddenIds();
        });

        var pathFold = document.getElementById(cfg.pathFoldId);
        if (pathFold) {
            pathFold.addEventListener('toggle', function () {
                if (pathFold.open) renderScanPaths();
            });
        }

        form.querySelectorAll('[data-batch]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var action = btn.getAttribute('data-batch');
                if (!selectedChips().length) {
                    window.alert(cfg.pickFirstMsg);
                    return;
                }
                syncHiddenIds();
                if (action === 'delete') {
                    var labels = [];
                    selectedChips().forEach(function (chip) {
                        labels.push(chip.getAttribute('data-label'));
                    });
                    var first = window.confirm(
                        '确定要删除以下' + cfg.itemName + '吗？\n' + labels.join('、')
                    );
                    if (!first) return;
                    var second = window.confirm(
                        '删除后不可恢复，请再次确认删除这 ' + labels.length + ' 个' + cfg.itemName + '。'
                    );
                    if (!second) return;
                }
                actionInput.value = action;
                // 这是明确的批量提交，不是用户误离开网页。
                if (window.ycSellerUnsavedGuard &&
                    typeof window.ycSellerUnsavedGuard.allowNextUnload === 'function') {
                    window.ycSellerUnsavedGuard.allowNextUnload();
                }
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            });
        });

        updateHint();
    }

    initCodeGrid({
        gridId: 'table-chip-grid',
        formId: 'table-batch-form',
        actionInputId: 'table-batch-action',
        hintId: 'table-batch-hint',
        pathsBoxId: 'table-scan-paths',
        pathFoldId: 'table-scan-fold',
        emptyHint: '请先点选桌号，再点下方「启用 / 停用 / 导出 PDF / 删除」',
        pickFirstMsg: '请先点选至少一个桌号',
        itemName: '桌号',
    });

    initCodeGrid({
        gridId: 'virtual-chip-grid',
        formId: 'virtual-batch-form',
        actionInputId: 'virtual-batch-action',
        hintId: 'virtual-batch-hint',
        pathsBoxId: 'virtual-scan-paths',
        pathFoldId: 'virtual-scan-fold',
        emptyHint: '请先点选虚拟码，再点下方「启用 / 停用 / 导出 PDF / 删除」',
        pickFirstMsg: '请先点选至少一个虚拟码',
        itemName: '虚拟码',
    });
})();
