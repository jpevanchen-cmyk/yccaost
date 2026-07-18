/* 展示主页：吸顶导航、回顶部、半屏阈值裁切与大阅读区 */
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

  var overlay = document.getElementById('showcase-reader');
  var readerTitle = document.getElementById('showcase-reader-title');
  var readerBody = document.getElementById('showcase-reader-body');
  var readerClose = document.getElementById('showcase-reader-close');
  if (!overlay || !readerTitle || !readerBody) return;

  /* 超过半屏才裁切；预览高度略低于半屏，方便看出「还有下文」 */
  function thresholdPx() {
    return Math.round(window.innerHeight * 0.5);
  }
  function previewPx() {
    return Math.round(window.innerHeight * 0.45);
  }

  function openReaderText(title, bodyText) {
    readerTitle.textContent = title || '';
    readerBody.classList.remove('is-html');
    readerBody.textContent = bodyText || '';
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('showcase-reader-open');
    if (readerClose) readerClose.focus();
  }

  function openReaderHtml(title, html) {
    readerTitle.textContent = title || '';
    readerBody.classList.add('is-html');
    readerBody.innerHTML = html || '';
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('showcase-reader-open');
    if (readerClose) readerClose.focus();
  }

  function closeReader() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('showcase-reader-open');
    readerBody.classList.remove('is-html');
    readerBody.textContent = '';
  }

  function blockTitle(block) {
    var titleEl = block.querySelector('.showcase-block-title');
    return titleEl ? titleEl.textContent.trim() : '';
  }

  function openBlock(block) {
    var title = blockTitle(block);
    var bodyEl = block.querySelector('.showcase-body');
    if (bodyEl) {
      openReaderText(title, bodyEl.textContent || '');
      return;
    }
    var main = block.querySelector('.showcase-block-main');
    if (main) {
      openReaderHtml(title, main.innerHTML);
      return;
    }
    openReaderText(title, block.textContent || '');
  }

  function clearCompact(block) {
    block.classList.remove('is-over-threshold');
    block.style.maxHeight = '';
    var bar = block.querySelector('.showcase-expand-bar');
    if (bar) bar.remove();
  }

  function applyHeightRules() {
    var limit = thresholdPx();
    var preview = previewPx();
    document.querySelectorAll('.showcase-home-page .showcase-block').forEach(function (block) {
      clearCompact(block);
      /* 先按自然高度量，再决定要不要裁切 */
      var natural = block.scrollHeight;
      if (natural <= limit + 2) return;

      block.classList.add('is-over-threshold');
      block.style.maxHeight = preview + 'px';

      var expand = document.createElement('button');
      expand.type = 'button';
      expand.className = 'showcase-expand-bar';
      expand.textContent = bodyHasArticle(block) ? '点击阅读全文' : '点击展开';
      expand.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        openBlock(block);
      });
      block.appendChild(expand);
    });
  }

  function bodyHasArticle(block) {
    return !!block.querySelector('.showcase-body');
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

  if (readerClose) {
    readerClose.addEventListener('click', function (e) {
      e.stopPropagation();
      closeReader();
    });
  }
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeReader();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeReader();
  });
})();
