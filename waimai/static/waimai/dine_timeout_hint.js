/* 兼容旧路径：已迁至 waimai/plugins/dining/dine_timeout_hint.js
 * 新页面请引用 {% static 'waimai/plugins/dining/dine_timeout_hint.js' %}
 */
(function () {
  var s = document.createElement('script');
  var cur = document.currentScript;
  var base = (cur && cur.src) ? cur.src.replace(/[^/]+$/, '') : '/static/waimai/';
  s.src = base + 'plugins/dining/dine_timeout_hint.js?v=2';
  s.async = false;
  (cur && cur.parentNode ? cur.parentNode : document.head).insertBefore(s, cur ? cur.nextSibling : null);
})();
