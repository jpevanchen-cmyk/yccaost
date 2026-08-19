/* 条款页：尽量关掉这一页；关不掉时给出人话提示 */
(function () {
  var failHint = document.getElementById('privacy-close-fail');
  var buttons = document.querySelectorAll('.js-privacy-close');
  if (!buttons.length) return;

  function tryClose() {
    window.close();
    window.setTimeout(function () {
      if (failHint) failHint.hidden = false;
    }, 200);
  }

  for (var i = 0; i < buttons.length; i += 1) {
    buttons[i].addEventListener('click', tryClose);
  }
})();
