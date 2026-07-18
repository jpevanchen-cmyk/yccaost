/* 堂食凭证超时提示（批次 A）
 * 规则：不改动堂食凭证 5 分钟寿命；只在「本浏览器刚才在某桌堂食、现在却掉回普通进店选通道」时，
 * 给一句醒目白话提示，让客人知道要重新扫桌上的二维码。
 * 做法：进入堂食态时在本机 localStorage 记一个带时间的标记；
 * 之后若落到「请选择下单方式」而标记仍在有效期内，就显示提示条。
 */
(function () {
  var cfg = window.YC_DINE_HINT;
  if (!cfg || !cfg.sellerId) return;

  // 标记有效期：约 3 小时（够一顿饭；过久则视为新的一次到店，不再提示）
  var VALID_MS = 3 * 60 * 60 * 1000;
  var KEY = 'yc_dine_hint_' + cfg.sellerId;

  function readTs() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return 0;
      var n = parseInt(raw, 10);
      return isNaN(n) ? 0 : n;
    } catch (e) {
      return 0;
    }
  }
  function writeTs() {
    try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {}
  }
  function clearTs() {
    try { localStorage.removeItem(KEY); } catch (e) {}
  }

  // 正处于堂食态：刷新标记时间，并确保不显示提示
  if (cfg.inTableSession) {
    writeTs();
    return;
  }

  // 只有在「需要重新选下单方式」时才提示，避免已主动选了外卖/打包还被打扰
  if (!cfg.needChannelPick) return;

  var ts = readTs();
  if (!ts) return;
  if (Date.now() - ts > VALID_MS) {
    clearTs();
    return;
  }

  function showHint() {
    if (document.getElementById('yc-dine-timeout-hint')) return;
    var box = document.createElement('div');
    box.id = 'yc-dine-timeout-hint';
    box.className = 'msg-warn dine-timeout-hint';

    var text = document.createElement('span');
    text.textContent = '堂食点餐状态已超时，请重新扫描桌上的二维码进入本桌点餐。';
    box.appendChild(text);

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'dine-timeout-hint-close';
    close.setAttribute('aria-label', '关闭提示');
    close.textContent = '×';
    close.addEventListener('click', function () {
      clearTs();
      if (box.parentNode) box.parentNode.removeChild(box);
    });
    box.appendChild(close);

    var anchor = document.querySelector('.channel-pick-card');
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(box, anchor);
    } else {
      var content = document.querySelector('.content') || document.body;
      content.insertBefore(box, content.firstChild);
    }
  }

  if (document.readyState !== 'loading') {
    showHint();
  } else {
    document.addEventListener('DOMContentLoaded', showHint);
  }
})();
