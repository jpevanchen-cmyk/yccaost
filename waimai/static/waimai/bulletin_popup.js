/* 大厅整机公告：有更新才弹一次，关掉后记住版本号 */
(function () {
  var dlg = document.getElementById('yc-hall-bulletin');
  if (!dlg) return;
  var rev = dlg.getAttribute('data-revision') || '';
  if (!rev) return;
  var key = 'yc-server-bulletin-seen-rev';
  var seen = '';
  try {
    seen = (window.localStorage && localStorage.getItem(key)) || '';
  } catch (err) {
    seen = '';
  }
  if (seen === rev) return;

  function remember() {
    try {
      if (window.localStorage) localStorage.setItem(key, rev);
    } catch (err2) { /* 忽略 */ }
  }

  function openDlg() {
    try {
      if (typeof dlg.showModal === 'function') {
        dlg.showModal();
      } else {
        dlg.setAttribute('open', '');
      }
    } catch (err3) {
      dlg.setAttribute('open', '');
    }
  }

  dlg.addEventListener('close', remember);
  openDlg();
})();
