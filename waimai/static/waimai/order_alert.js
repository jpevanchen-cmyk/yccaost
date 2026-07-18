/* 新订单网页内强提醒（第一、二步）
 * 第一步：页面开着时定时查新单；有新单弹醒目横幅 + 持续响铃，直到处理完或用户收起。
 * 第二步：用户授权后，页面在后台也能弹出浏览器系统通知。
 * 音量、重复间隔、提示音可由店铺在「工作台管理」里自定义（随轮询下发）。
 * 因浏览器规则，声音必须由用户先点一次页面才能播放；开启状态本身用 sessionStorage 记住，
 * 整页刷新（如点一份备好/上桌）后仍保持开启，无需重新点击。
 * 用法：页面里设置 window.YC_ORDER_ALERT = { pollUrl: '...', storagePrefix: '...' }，再引入本脚本。
 */
(function () {
  var cfg = window.YC_ORDER_ALERT;
  if (!cfg || !cfg.pollUrl) return;

  var POLL_MS = 15000; // 每 15 秒查一次新单

  var audioCtx = null; // 合成提示音用
  var customAudio = null; // 店铺自定义音频（如有）
  var soundTimer = null; // 循环响铃定时器
  var pollTimer = null; // 轮询定时器
  var enabled = false; // 提醒开关（本标签页内，刷新保持）
  var audioUnlocked = false; // 是否已借用户手势解锁过声音
  var muted = false; // 用户点「暂停响铃」后为 true（仍继续查单，只是不响）
  var currentCount = 0;
  var currentLatestTs = 0;
  var ackCount = 0; // 用户点「确认」时记下的单数：小于等于它就不再弹横幅；来更多新单会自动恢复
  var ackLatestTs = 0; // 同数量的新单替换旧单时，也要能识别为真正的新单

  // 店铺下发的提醒配置（有默认值，轮询后更新）
  var serverCfg = { volume: 0.6, interval: 8, sound_url: '' };

  // ---- 本标签页记忆：刷新后保持开启/确认/静音状态 ----
  var STORE_PREFIX = (cfg.storagePrefix || 'yc_order_alert') + '_';
  function storeGet(key) {
    try { return sessionStorage.getItem(STORE_PREFIX + key); } catch (e) { return null; }
  }
  function storeSet(key, value) {
    try { sessionStorage.setItem(STORE_PREFIX + key, String(value)); } catch (e) {}
  }
  function storeDel(key) {
    try { sessionStorage.removeItem(STORE_PREFIX + key); } catch (e) {}
  }
  function persistState() {
    storeSet('enabled', enabled ? '1' : '0');
    storeSet('muted', muted ? '1' : '0');
    storeSet('ackCount', ackCount);
    storeSet('ackTs', ackLatestTs);
  }

  // ---- 合成提示音（无自定义音频时用）----
  function playSynthBeep() {
    if (!audioCtx) return;
    try {
      var vol = serverCfg.volume;
      var t = audioCtx.currentTime;
      var osc = audioCtx.createOscillator();
      var gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, t);
      osc.frequency.setValueAtTime(1175, t + 0.18);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, vol), t + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + 0.6);
    } catch (e) {}
  }

  // 准备自定义音频元素（拿到网址后创建/更新）
  function ensureCustomAudio() {
    if (!serverCfg.sound_url) {
      customAudio = null;
      return;
    }
    if (!customAudio || customAudio.getAttribute('data-src') !== serverCfg.sound_url) {
      customAudio = new Audio(serverCfg.sound_url);
      customAudio.setAttribute('data-src', serverCfg.sound_url);
      customAudio.preload = 'auto';
    }
    customAudio.volume = Math.min(1, Math.max(0, serverCfg.volume));
  }

  // 借一次用户手势解锁声音（用于刷新后自动恢复的场景）
  function unlockAudio() {
    if (audioUnlocked) return;
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx && audioCtx.state === 'suspended' && audioCtx.resume) audioCtx.resume();
    } catch (e) {}
    ensureCustomAudio();
    if (customAudio) {
      try {
        var p = customAudio.play();
        if (p && p.then) {
          p.then(function () { customAudio.pause(); customAudio.currentTime = 0; }).catch(function () {});
        }
      } catch (e) {}
    }
    audioUnlocked = true;
  }

  // 响一声：优先店铺自定义音频，失败则退回合成音
  function playAlertSound() {
    ensureCustomAudio();
    if (customAudio) {
      try {
        customAudio.currentTime = 0;
        var p = customAudio.play();
        if (p && p.catch) p.catch(function () { playSynthBeep(); });
        return;
      } catch (e) {}
    }
    playSynthBeep();
  }

  // ---- 界面元素 ----
  var banner, bannerText, enableBtn, statusText;

  function setButtonState() {
    if (!enableBtn) return;
    if (enabled) {
      enableBtn.textContent = '🔕 新单提醒：开（点此关闭）';
      enableBtn.classList.add('is-on');
    } else {
      enableBtn.textContent = '🔔 新单提醒：关（点此开启）';
      enableBtn.classList.remove('is-on');
    }
  }

  function buildUI() {
    var bar = document.createElement('div');
    bar.className = 'order-alert-bar';
    enableBtn = document.createElement('button');
    enableBtn.type = 'button';
    enableBtn.className = 'btn btn-orange order-alert-enable';
    statusText = document.createElement('span');
    statusText.className = 'order-alert-status';
    bar.appendChild(enableBtn);
    bar.appendChild(statusText);
    // 若页面提供了挂载点（cfg.mountSelector），就把按钮条放到指定位置；否则退回页面底部
    var mount = cfg.mountSelector ? document.querySelector(cfg.mountSelector) : null;
    if (mount) {
      mount.appendChild(bar);
    } else {
      document.body.appendChild(bar);
    }

    banner = document.createElement('div');
    banner.className = 'order-alert-banner';
    banner.hidden = true;
    bannerText = document.createElement('span');
    bannerText.className = 'order-alert-banner-text';
    var muteBtn = document.createElement('button');
    muteBtn.type = 'button';
    muteBtn.className = 'order-alert-btn';
    muteBtn.textContent = '🔕 暂停响铃';
    var ackBtn = document.createElement('button');
    ackBtn.type = 'button';
    ackBtn.className = 'order-alert-btn order-alert-btn-primary';
    ackBtn.textContent = '✅ 确认（我知道了）';
    banner.appendChild(bannerText);
    banner.appendChild(muteBtn);
    banner.appendChild(ackBtn);
    document.body.appendChild(banner);

    // 开/关切换
    enableBtn.addEventListener('click', function () {
      if (enabled) turnOff(); else turnOn();
    });
    // 暂停响铃：只静音，红横幅还在（提醒还有几单待处理）
    muteBtn.addEventListener('click', function () {
      muted = true;
      stopSound();
      persistState();
      statusText.textContent = '（响铃已暂停；单子处理完后，再来新单会自动恢复）';
    });
    // 确认（我知道了）：最快收起红条；之后再来更多新单会自动重新提醒
    ackBtn.addEventListener('click', function () {
      ackCount = currentCount;
      ackLatestTs = currentLatestTs;
      muted = false; // 重置静音标记，方便下批新单正常响
      stopSound();
      hideBanner();
      persistState();
      statusText.textContent = '（已确认当前新单；再来新单会自动重新提醒）';
    });

    // 刷新后自动恢复：上次开着就继续开着，无需重新点击
    if (storeGet('enabled') === '1') {
      muted = storeGet('muted') === '1';
      ackCount = Number(storeGet('ackCount')) || 0;
      ackLatestTs = Number(storeGet('ackTs')) || 0;
      resumeEnabled();
    } else {
      setButtonState();
      statusText.textContent = '（提醒未开启：开启后本页开着时会持续检查新单并响铃）';
    }
  }

  // 首次开启：由用户点击，可创建声音并申请系统通知
  function turnOn() {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      var t = audioCtx.currentTime;
      var g = audioCtx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.connect(audioCtx.destination);
    } catch (e) {}
    audioUnlocked = true;
    ensureCustomAudio();
    if (customAudio) {
      try {
        customAudio.play().then(function () {
          customAudio.pause();
          customAudio.currentTime = 0;
        }).catch(function () {});
      } catch (e) {}
    }
    // 第二步：申请浏览器系统通知权限（用户可拒绝，不影响网页内提醒）
    if ('Notification' in window && Notification.permission === 'default') {
      try { Notification.requestPermission(); } catch (e) {}
    }
    enabled = true;
    muted = false;
    ackCount = 0;
    ackLatestTs = 0;
    persistState();
    setButtonState();
    statusText.textContent = '（提醒运行中：本页开着时每约 15 秒检查一次新单）';
    playSynthBeep(); // 让用户确认能听到
    startPolling();
  }

  // 关闭：手动点「关」才停；停轮询、停声、收起红条
  function turnOff() {
    enabled = false;
    stopSound();
    stopPolling();
    hideBanner();
    persistState();
    setButtonState();
    statusText.textContent = '（提醒已关闭；点上面按钮可重新开启）';
  }

  // 刷新后自动恢复开启：不重新申请手势，声音等下一次页面点击再解锁
  function resumeEnabled() {
    enabled = true;
    setButtonState();
    statusText.textContent = '（提醒运行中：刷新后已自动保持开启）';
    // 任意一次页面点击（如点「开始备货」）就顺便解锁声音
    var onceUnlock = function () {
      unlockAudio();
      document.removeEventListener('click', onceUnlock, true);
    };
    document.addEventListener('click', onceUnlock, true);
    startPolling();
  }

  function startSound() {
    if (muted || soundTimer) return;
    playAlertSound();
    soundTimer = setInterval(function () {
      if (!muted && currentCount > 0) playAlertSound();
    }, Math.max(3, serverCfg.interval) * 1000);
  }

  function stopSound() {
    if (soundTimer) {
      clearInterval(soundTimer);
      soundTimer = null;
    }
  }

  // 提醒文案：不同角色可自定义（骑手是「外卖单」，其它是「新订单待备货」）
  var ITEM_LABEL = (cfg.itemLabel || '个新订单待备货，请及时处理！');

  function showBanner(count) {
    bannerText.textContent = '有 ' + count + ' ' + ITEM_LABEL;
    banner.hidden = false;
  }
  function hideBanner() {
    banner.hidden = true;
  }

  // 第二步：弹浏览器系统通知（仅在已授权时）
  function showSystemNotification(count) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      var n = new Notification('野草 · 有新订单', {
        body: '有 ' + count + ' ' + ITEM_LABEL,
        tag: 'yc-new-order',
        renotify: true,
      });
      n.onclick = function () {
        window.focus();
        n.close();
      };
    } catch (e) {}
  }

  function applyResult(count, latestTs) {
    var was = currentCount;
    var previousLatestTs = currentLatestTs;
    currentCount = count;
    currentLatestTs = latestTs;
    if (count <= 0) {
      // 单子都处理完了：收起红条、停声，但保持开启，下次来单重新提醒
      hideBanner();
      stopSound();
      muted = false;
      ackCount = 0;
      ackLatestTs = 0;
      persistState();
      return;
    }
    // 数量增加，或最新订单时间变新：都算真正来了新单，撤销「确认/暂停」，绝不漏单
    if (count > was || latestTs > previousLatestTs) {
      ackCount = 0;
      ackLatestTs = 0;
      muted = false;
      persistState();
      showSystemNotification(count);
    }
    // 已确认且没有更多新单：保持收起、保持安静（刷新后靠 sessionStorage 记住）
    if (ackCount > 0 && count <= ackCount && latestTs <= ackLatestTs) {
      return;
    }
    // 只要还有未处理新单且未确认，红条就一直显示（剩几单显示几单）
    showBanner(count);
    if (!muted) startSound();
  }

  function pollOnce() {
    fetch(cfg.pollUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.ok) return;
        if (data.config) {
          if (typeof data.config.volume === 'number') serverCfg.volume = data.config.volume;
          if (typeof data.config.interval === 'number') serverCfg.interval = data.config.interval;
          if (typeof data.config.sound_url === 'string') serverCfg.sound_url = data.config.sound_url;
        }
        applyResult(Number(data.count) || 0, Number(data.latest_ts) || 0);
        if (typeof cfg.onPoll === 'function') {
          try { cfg.onPoll(data); } catch (e) {}
        }
      })
      .catch(function () {});
  }

  function startPolling() {
    pollOnce();
    if (!pollTimer) {
      pollTimer = setInterval(pollOnce, POLL_MS);
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && pollTimer) pollOnce();
  });

  if (document.readyState !== 'loading') {
    buildUI();
  } else {
    document.addEventListener('DOMContentLoaded', buildUI);
  }
})();
