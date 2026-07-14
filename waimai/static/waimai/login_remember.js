/**
 * 登录页「记住用户名和密码」：
 * - 默认不勾选
 * - 勾选后由本系统写入本机存储
 * - 未勾选时尽量降低浏览器自动填充（无法 100% 禁止浏览器自己记密码）
 */
(function () {
    var cfg = window.YC_LOGIN_REMEMBER;
    if (!cfg || !cfg.storageKey) return;

    var form = document.querySelector(cfg.formSelector || 'form.auth-form');
    if (!form) return;

    var userInput = form.querySelector(cfg.usernameSelector || 'input[name="username"]');
    var passInput = form.querySelector(cfg.passwordSelector || 'input[name="password"]');
    var box = form.querySelector(cfg.checkboxSelector || 'input[name="remember_credentials"]');
    if (!userInput || !passInput || !box) return;

    var storageKey = cfg.storageKey;

    function readSaved() {
        try {
            var raw = localStorage.getItem(storageKey);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (e) {
            return null;
        }
    }

    function clearSaved() {
        try { localStorage.removeItem(storageKey); } catch (e) { /* 忽略 */ }
    }

    function saveNow() {
        try {
            localStorage.setItem(storageKey, JSON.stringify({
                username: userInput.value || '',
                password: passInput.value || '',
            }));
        } catch (e) { /* 忽略 */ }
    }

    function applyAutocomplete(remember) {
        // 未勾选：尽量不配合浏览器记密码；无法保证所有浏览器都听劝
        var mode = remember ? 'on' : 'off';
        form.setAttribute('autocomplete', mode);
        userInput.setAttribute('autocomplete', remember ? 'username' : 'off');
        passInput.setAttribute('autocomplete', remember ? 'current-password' : 'new-password');
        if (!remember) {
            userInput.setAttribute('autocapitalize', 'off');
            userInput.setAttribute('autocorrect', 'off');
            userInput.setAttribute('spellcheck', 'false');
        }
    }

    // 默认不勾选；若本机曾勾选并保存过，则勾上并回填
    var saved = readSaved();
    box.checked = false;
    applyAutocomplete(false);
    if (saved && (saved.username || saved.password)) {
        box.checked = true;
        userInput.value = saved.username || '';
        passInput.value = saved.password || '';
        applyAutocomplete(true);
    }

    box.addEventListener('change', function () {
        applyAutocomplete(box.checked);
        if (!box.checked) clearSaved();
    });

    form.addEventListener('submit', function () {
        if (box.checked) {
            saveNow();
        } else {
            clearSaved();
            applyAutocomplete(false);
        }
    });
})();
