/* 卖家订单页顶：新订单快捷链接的本标签页消隐
 * 规则：点链接 / 打开详情 / 关掉浏览器标签 → 不再显示该单；
 * 在卖家后台各分区之间切换仍保留（sessionStorage）。
 */
(function () {
  var STORE_KEY = 'yc_seller_dismissed_new_orders';
  var strip = document.getElementById('seller-new-order-strip');
  var linksBox = document.getElementById('seller-new-order-links');
  if (!linksBox) return;

  function loadDismissed() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list.map(String) : [];
    } catch (e) {
      return [];
    }
  }

  function saveDismissed(list) {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(list));
    } catch (e) {}
  }

  function dismiss(orderId) {
    var id = String(orderId || '');
    if (!id) return;
    var list = loadDismissed();
    if (list.indexOf(id) < 0) {
      list.push(id);
      saveDismissed(list);
    }
  }

  function applyDismissFilter() {
    var dismissed = loadDismissed();
    var visible = 0;
    var nodes = linksBox.querySelectorAll('.seller-new-order-link');
    for (var i = 0; i < nodes.length; i++) {
      var a = nodes[i];
      var oid = String(a.getAttribute('data-order-id') || '');
      var hide = oid && dismissed.indexOf(oid) >= 0;
      a.hidden = hide;
      if (!hide) visible += 1;
    }
    if (strip) strip.hidden = visible === 0;
  }

  function bindClicks() {
    var nodes = linksBox.querySelectorAll('.seller-new-order-link');
    for (var i = 0; i < nodes.length; i++) {
      (function (a) {
        if (a.getAttribute('data-bound') === '1') return;
        a.setAttribute('data-bound', '1');
        a.addEventListener('click', function () {
          dismiss(a.getAttribute('data-order-id'));
        });
      })(nodes[i]);
    }
  }

  // 轮询刷新：用服务端最新新单列表重绘，再套消隐
  function refreshNewOrders(items) {
    if (!Array.isArray(items)) return;
    linksBox.textContent = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i] || {};
      var oid = String(it.order_id || '');
      var a = document.createElement('a');
      a.className = 'seller-shortcut-link seller-new-order-link';
      a.setAttribute('data-order-id', oid);
      a.href = it.url || '#';
      a.textContent = (it.display_no || oid) + (it.fulfillment ? (' · ' + it.fulfillment) : '');
      linksBox.appendChild(a);
    }
    bindClicks();
    applyDismissFilter();
  }

  bindClicks();
  applyDismissFilter();

  window.YC_SellerOrderShortcuts = {
    refreshNewOrders: refreshNewOrders,
    dismiss: dismiss
  };
})();
