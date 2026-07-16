/* 主页积木：选择图片后显示文件名；正文框随内容增高（也可手动拖高） */
(function () {
  function bindFileRows(root) {
    root.querySelectorAll('.home-block-path-row').forEach(function (row) {
      var fileInput = row.querySelector('.home-block-file-input');
      var pathDisplay = row.querySelector('.home-block-path-display');
      if (!fileInput || !pathDisplay) return;
      fileInput.addEventListener('change', function () {
        var f = fileInput.files && fileInput.files[0];
        if (f && f.name) {
          // 选图后先显示文件名；保存成功后会变成本站 /media/… 地址
          pathDisplay.value = f.name;
          pathDisplay.title = '已选择：' + f.name + '（保存后显示本站地址）';
        }
      });
    });
  }

  function autoGrowBody(el) {
    if (!el) return;
    el.style.height = 'auto';
    var next = Math.max(160, el.scrollHeight);
    var maxPx = Math.floor(window.innerHeight * 0.7);
    el.style.height = Math.min(next, maxPx) + 'px';
  }

  function bindBodyGrow(root) {
    root.querySelectorAll('.home-block-body-input').forEach(function (ta) {
      autoGrowBody(ta);
      ta.addEventListener('input', function () {
        autoGrowBody(ta);
      });
    });
  }

  function init(root) {
    bindFileRows(root);
    bindBodyGrow(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      init(document);
    });
  } else {
    init(document);
  }
})();
