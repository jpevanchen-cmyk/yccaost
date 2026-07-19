/* 兼容旧路径：已迁至 waimai/plugins/dining/seller_dine_grid.js
 * 新页面请引用 {% static 'waimai/plugins/dining/seller_dine_grid.js' %}
 */
(function () {
  var s = document.createElement('script');
  var cur = document.currentScript;
  var base = (cur && cur.src) ? cur.src.replace(/[^/]+$/, '') : '/static/waimai/';
  s.src = base + 'plugins/dining/seller_dine_grid.js?v=4';
  s.async = false;
  (cur && cur.parentNode ? cur.parentNode : document.head).insertBefore(s, cur ? cur.nextSibling : null);
})();
