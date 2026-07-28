/**
 * 新版新手体验：可拖动弹窗（仅 experience-modal / yc-exp-tour-card，与 YcNotice 无关）
 */
(function () {
    function clamp(val, min, max) {
        return Math.max(min, Math.min(max, val));
    }

    function clampPanelInViewport(panel, margin) {
        if (!panel) return;
        margin = margin || 8;
        var rect = panel.getBoundingClientRect();
        var w = rect.width || panel.offsetWidth || 0;
        var h = rect.height || panel.offsetHeight || 0;
        if (!w || !h) return;
        var left = clamp(rect.left, margin, window.innerWidth - w - margin);
        var top = clamp(rect.top, margin, window.innerHeight - h - margin);
        panel.style.position = 'fixed';
        panel.style.margin = '0';
        panel.style.transform = 'none';
        panel.style.left = left + 'px';
        panel.style.top = top + 'px';
    }

    function enableDrag(panel, handle) {
        if (!panel || !handle || panel.dataset.expDragBound) return;
        panel.dataset.expDragBound = '1';
        var dragging = false;
        var startX = 0;
        var startY = 0;
        var startLeft = 0;
        var startTop = 0;

        function onPointerDown(ev) {
            if (ev.button !== undefined && ev.button !== 0) return;
            if (ev.target.closest('button, input, textarea, select, a, label')) return;
            var rect = panel.getBoundingClientRect();
            panel.style.position = 'fixed';
            panel.style.margin = '0';
            panel.style.transform = 'none';
            panel.style.zIndex = '10155';
            panel.style.left = rect.left + 'px';
            panel.style.top = rect.top + 'px';
            panel.dataset.expUserDragged = '1';
            dragging = true;
            startX = ev.clientX;
            startY = ev.clientY;
            startLeft = rect.left;
            startTop = rect.top;
            handle.setPointerCapture(ev.pointerId);
            ev.preventDefault();
        }

        function onPointerMove(ev) {
            if (!dragging) return;
            var dx = ev.clientX - startX;
            var dy = ev.clientY - startY;
            panel.style.left = (startLeft + dx) + 'px';
            panel.style.top = (startTop + dy) + 'px';
            clampPanelInViewport(panel, 8);
        }

        function onPointerUp(ev) {
            if (!dragging) return;
            dragging = false;
            clampPanelInViewport(panel, 8);
            try { handle.releasePointerCapture(ev.pointerId); } catch (e) { /* 忽略 */ }
        }

        handle.addEventListener('pointerdown', onPointerDown);
        handle.addEventListener('pointermove', onPointerMove);
        handle.addEventListener('pointerup', onPointerUp);
        handle.addEventListener('pointercancel', onPointerUp);
    }

    function resetPanelPosition(panel) {
        if (!panel) return;
        delete panel.dataset.expUserDragged;
        panel.style.transform = 'none';
        panel.style.margin = '0';
    }

    function bindAll() {
        document.querySelectorAll('.experience-box').forEach(function (box) {
            var handle = box.querySelector('[data-experience-drag-handle]') || box.querySelector('.experience-box-title') || box;
            enableDrag(box, handle);
        });
        document.querySelectorAll('.yc-exp-tour-card').forEach(function (card) {
            var handle = card.querySelector('.yc-exp-tour-title') || card.querySelector('.yc-exp-tour-progress') || card;
            enableDrag(card, handle);
        });
    }

    window.YcExperienceModal = {
        enableDrag: enableDrag,
        bindAll: bindAll,
        resetPanelPosition: resetPanelPosition,
        clampPanelInViewport: clampPanelInViewport,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindAll);
    } else {
        bindAll();
    }
})();
