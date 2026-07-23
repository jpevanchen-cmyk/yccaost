/* 展示主页：吸顶导航、回顶部、半屏裁切与原位置展开/收起 */
(function () {
  var btn = document.getElementById('showcase-back-top');
  if (btn) {
    function onScroll() {
      btn.hidden = window.scrollY < 240;
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    btn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  var expandedBlock = null;

  /* 超过半屏才裁切；预览高度略低于半屏，方便看出「还有下文」 */
  function thresholdPx() {
    return Math.round(window.innerHeight * 0.5);
  }
  function previewPx() {
    return Math.round(window.innerHeight * 0.45);
  }

  /* 只处理 showcase-stack 下最外层积木，跳过留言板等嵌套内层 */
  function isTopLevelBlock(block) {
    var parent = block.parentElement;
    while (parent && !parent.classList.contains('showcase-stack')) {
      if (parent.classList.contains('showcase-block')) return false;
      parent = parent.parentElement;
    }
    return true;
  }

  function bodyHasArticle(block) {
    return !!block.querySelector('.showcase-body');
  }

  function expandLabel(block) {
    return bodyHasArticle(block) ? '点击阅读全文' : '点击展开';
  }

  function clearCompact(block) {
    block.classList.remove('is-over-threshold');
    block.style.maxHeight = '';
    var bar = block.querySelector('.showcase-expand-bar');
    if (bar) bar.remove();
  }

  function setExpandBarLabel(bar, block, expanded) {
    bar.textContent = expanded ? '收起' : expandLabel(block);
    bar.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  function collapseBlock(block, reapplyRules) {
    if (!block) return;
    block.classList.remove('is-expanded');
    if (expandedBlock === block) expandedBlock = null;
    if (reapplyRules !== false) applyHeightRules();
  }

  function collapseExpanded() {
    if (expandedBlock) collapseBlock(expandedBlock, true);
  }

  function expandBlock(block) {
    if (expandedBlock && expandedBlock !== block) {
      collapseBlock(expandedBlock, false);
    }
    block.classList.remove('is-over-threshold');
    block.classList.add('is-expanded');
    block.style.maxHeight = 'none';
    block.style.height = 'auto';
    var bar = block.querySelector('.showcase-expand-bar');
    if (bar) setExpandBarLabel(bar, block, true);
    expandedBlock = block;
    block.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function toggleBlock(block) {
    if (block.classList.contains('is-expanded')) {
      collapseBlock(block, true);
    } else {
      expandBlock(block);
    }
  }

  /* 点输入框、按钮、链接等时不触发展开 */
  function isInteractiveClick(target) {
    if (!target || !target.closest) return false;
    if (target.closest('.showcase-expand-bar')) return true;
    return !!target.closest('a, button, input, textarea, select, label');
  }

  function applyHeightRules() {
    var limit = thresholdPx();
    var preview = previewPx();
    document.querySelectorAll('.showcase-home-page .showcase-block').forEach(function (block) {
      if (!isTopLevelBlock(block)) return;
      if (block.classList.contains('is-expanded')) return;

      clearCompact(block);
      var natural = block.scrollHeight;
      if (natural <= limit + 2) return;

      block.classList.add('is-over-threshold');
      block.style.maxHeight = preview + 'px';

      var expand = document.createElement('button');
      expand.type = 'button';
      expand.className = 'showcase-expand-bar';
      expand.setAttribute('aria-expanded', 'false');
      expand.textContent = expandLabel(block);
      expand.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggleBlock(block);
      });
      block.appendChild(expand);
    });
  }

  /* 等图片加载完再量一次，避免量矮了 */
  function whenReady(fn) {
    if (document.readyState === 'complete') {
      fn();
      return;
    }
    window.addEventListener('load', fn, { once: true });
    fn();
  }

  whenReady(applyHeightRules);

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(applyHeightRules, 120);
  });

  /* Esc 收起当前展开的积木 */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') collapseExpanded();
  });

  /* 点积木外收起；点裁切中的积木区域直接展开 */
  document.addEventListener('click', function (e) {
    if (expandedBlock && !expandedBlock.contains(e.target)) {
      collapseExpanded();
    }

    var block = e.target.closest('.showcase-home-page .showcase-block');
    if (!block || !isTopLevelBlock(block)) return;
    if (!block.classList.contains('is-over-threshold')) return;
    if (isInteractiveClick(e.target)) return;
    expandBlock(block);
  });
})();
