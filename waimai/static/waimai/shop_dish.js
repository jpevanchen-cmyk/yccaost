/**
 * 客人点菜页：商品简化行 + 手风琴展开（同时只开一个）
 */
(function () {
    var listEl = null;
    var backdrop = null;
    var expandedGroup = null;

    function groups() {
        if (!listEl) return [];
        return listEl.querySelectorAll('[data-dish-group]');
    }

    function setExpanded(group, on) {
        if (!group) return;
        var panel = group.querySelector('.dish-expanded-panel');
        var toggle = group.querySelector('[data-dish-compact-toggle]');
        if (on) {
            group.classList.add('is-expanded');
            if (panel) panel.hidden = false;
            if (toggle) toggle.setAttribute('aria-expanded', 'true');
        } else {
            group.classList.remove('is-expanded');
            if (panel) panel.hidden = true;
            if (toggle) toggle.setAttribute('aria-expanded', 'false');
        }
    }

    function syncBackdrop() {
        if (!listEl) return;
        if (expandedGroup) {
            listEl.classList.add('dish-list--has-expanded');
        } else {
            listEl.classList.remove('dish-list--has-expanded');
        }
        if (!backdrop) return;
        backdrop.hidden = !expandedGroup;
    }

    function collapseAll() {
        groups().forEach(function (g) {
            setExpanded(g, false);
        });
        expandedGroup = null;
        syncBackdrop();
    }

    function expandGroup(group, scrollIntoView) {
        if (!group) return;
        if (expandedGroup && expandedGroup !== group) {
            setExpanded(expandedGroup, false);
        }
        expandedGroup = group;
        setExpanded(group, true);
        syncBackdrop();
        if (scrollIntoView !== false) {
            window.setTimeout(function () {
                group.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }, 30);
        }
    }

    function toggleGroup(group) {
        if (expandedGroup === group) {
            collapseAll();
        } else {
            expandGroup(group, true);
        }
    }

    /** 加购后滚回锚点前：先展开对应商品 */
    function expandForAnchor(anchorId) {
        if (!anchorId) return;
        var target = document.getElementById(anchorId);
        if (!target) return;
        var group = target.closest('[data-dish-group]');
        if (group) {
            expandGroup(group, false);
        }
    }

    function onCompactClick(e) {
        var btn = e.target.closest('[data-dish-compact-toggle]');
        if (!btn) return;
        e.preventDefault();
        toggleGroup(btn.closest('[data-dish-group]'));
    }

    function onCollapseClick(e) {
        var btn = e.target.closest('[data-dish-collapse]');
        if (!btn) return;
        e.preventDefault();
        collapseAll();
    }

    function onBackdropClick() {
        collapseAll();
    }

    /** 点空白：列表区非当前展开商品处也收起 */
    function onListClick(e) {
        if (!expandedGroup) return;
        if (e.target.closest('[data-dish-group].is-expanded')) return;
        if (e.target.closest('.dish-lightbox')) return;
        collapseAll();
    }

    function bindGalleryStopPropagation(group) {
        group.querySelectorAll('[data-dish-gallery-thumb]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
            });
        });
    }

    function init() {
        listEl = document.querySelector('.dish-list[data-yc-tour="shop-dish-area"], .dish-list');
        if (!listEl) return;

        backdrop = document.getElementById('dish-expand-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'dish-expand-backdrop';
            backdrop.className = 'dish-expand-backdrop';
            backdrop.hidden = true;
            listEl.insertBefore(backdrop, listEl.firstChild);
        }
        backdrop.addEventListener('click', onBackdropClick);

        listEl.addEventListener('click', onCompactClick);
        listEl.addEventListener('click', onCollapseClick);
        listEl.addEventListener('click', onListClick);

        groups().forEach(bindGalleryStopPropagation);

        window.ycExpandDishGroupForAnchor = expandForAnchor;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
