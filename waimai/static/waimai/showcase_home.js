/* 展示主页：吸顶导航、回顶部、半屏裁切与原位置展开/收起 */
(function () {
  /* 标题与挡住内容的顶栏之间留一小缝，避免贴死或重叠 */
  var TITLE_GAP_PX = 8;

  function siteTopEl() {
    return document.querySelector('.site-top');
  }

  function showcaseNavEl() {
    return document.querySelector('.showcase-home-page .showcase-sticky-nav');
  }

  /* 量全站顶栏 + 主页导航条实际高度（换行变高也能跟上） */
  function overlayClearPx() {
    var topBar = siteTopEl();
    var nav = showcaseNavEl();
    var topH = topBar ? Math.round(topBar.getBoundingClientRect().height) : 0;
    var navH = nav ? Math.round(nav.getBoundingClientRect().height) : 0;
    document.documentElement.style.setProperty('--yc-site-top-h', topH + 'px');
    var clear = topH + navH + TITLE_GAP_PX;
    document.documentElement.style.setProperty('--yc-showcase-title-clear', clear + 'px');
    return clear;
  }

  function blockTitleEl(block) {
    if (!block) return null;
    var kids = block.children;
    var i;
    for (i = 0; i < kids.length; i += 1) {
      if (kids[i].classList && kids[i].classList.contains('showcase-block-title')) {
        return kids[i];
      }
    }
    return block.querySelector('.showcase-block-title');
  }

  /* 把积木标题停在挡住内容的条下面，中间留 TITLE_GAP_PX */
  function scrollBlockTitleIntoPlace(block, behavior) {
    if (!block) return;
    var title = blockTitleEl(block) || block;
    var clear = overlayClearPx();
    var rect = title.getBoundingClientRect();
    var targetY = window.scrollY + rect.top - clear;
    if (targetY < 0) targetY = 0;
    window.scrollTo({ top: targetY, behavior: behavior || 'smooth' });
  }

  function blockFromHash() {
    var hash = (window.location.hash || '').replace(/^#/, '');
    if (!hash || hash === 'top') return null;
    var el = document.getElementById(hash);
    if (!el) return null;
    if (el.classList.contains('showcase-block')) return el;
    return el.closest('.showcase-block');
  }

  function tryHashScroll(behavior) {
    var block = blockFromHash();
    if (!block) return;
    var welcome = document.getElementById('yc-topic-welcome');
    if (welcome && welcome.open) {
      welcome.addEventListener(
        'close',
        function () {
          scrollBlockTitleIntoPlace(block, behavior || 'smooth');
        },
        { once: true }
      );
      return;
    }
    scrollBlockTitleIntoPlace(block, behavior);
  }

  overlayClearPx();

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
    scrollBlockTitleIntoPlace(block, 'smooth');
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

  whenReady(function () {
    overlayClearPx();
    applyHeightRules();
    tryHashScroll('auto');
  });

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      overlayClearPx();
      applyHeightRules();
    }, 120);
  });

  /* 点吸顶导航里的积木锚点：拦住浏览器默认「贴屏幕最顶」，改对准标题 */
  document.addEventListener('click', function (e) {
    if (!document.body.classList.contains('showcase-home-page')) return;
    if (document.body.classList.contains('yc-tour-active')) return;
    var a = e.target && e.target.closest ? e.target.closest('.showcase-nav-links a') : null;
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (href.charAt(0) !== '#') return;
    var id = href.slice(1);
    if (!id || id === 'top') return;
    var target = document.getElementById(id);
    if (!target) return;
    var block = target.classList.contains('showcase-block')
      ? target
      : target.closest('.showcase-block');
    if (!block) return;
    e.preventDefault();
    var next = '#' + id;
    if (window.location.hash !== next && window.history && window.history.pushState) {
      window.history.pushState(null, '', next);
    } else if (window.location.hash !== next) {
      window.location.hash = next;
    }
    scrollBlockTitleIntoPlace(block, 'smooth');
  });

  window.addEventListener('hashchange', function () {
    if (document.body.classList.contains('yc-tour-active')) return;
    tryHashScroll('smooth');
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

  /* 二级专题页欢迎弹窗：可关；勾选后本页记住不再提示 */
  var welcome = document.getElementById('yc-topic-welcome');
  if (welcome && typeof welcome.showModal === 'function') {
    var key = welcome.getAttribute('data-storage-key') || '';
    var remembered = false;
    try {
      remembered = !!(key && window.localStorage && localStorage.getItem(key) === '1');
    } catch (err) {
      remembered = false;
    }
    if (!remembered) {
      try {
        welcome.showModal();
      } catch (err2) {
        welcome.setAttribute('open', '');
      }
    }
    welcome.addEventListener('close', function () {
      var box = document.getElementById('yc-topic-welcome-remember');
      if (box && box.checked && key) {
        try {
          localStorage.setItem(key, '1');
        } catch (err3) { /* 忽略 */ }
      }
    });
  }
})();
