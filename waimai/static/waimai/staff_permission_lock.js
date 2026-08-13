/**
 * 员工权限勾选：勾了业务权限时，当场勾上连带的订单台项并锁住，不能单独取消。
 * 锁住的勾选仍保持勾上并提交（不用浏览器 disabled，否则保存时会丢）。
 */
(function () {
    function loadData() {
        var el = document.getElementById('yc-staff-perm-lock-data');
        if (!el) {
            return null;
        }
        try {
            return JSON.parse(el.textContent);
        } catch (err) {
            return null;
        }
    }

    var DATA = loadData();
    if (!DATA || !DATA.bundles || !DATA.bundles.length) {
        return;
    }

    function permInputs(form) {
        return form.querySelectorAll('input[type="checkbox"][name="permissions"]');
    }

    function findInput(form, code) {
        return form.querySelector('input[type="checkbox"][name="permissions"][value="' + code + '"]');
    }

    function uniqueLabels(labels) {
        var seen = {};
        var out = [];
        labels.forEach(function (label) {
            if (!seen[label]) {
                seen[label] = true;
                out.push(label);
            }
        });
        return out;
    }

    function hintHost(input) {
        return input.closest('li') || input.parentElement;
    }

    function setHint(input, text) {
        var host = hintHost(input);
        if (!host) {
            return;
        }
        var el = host.querySelector('.yc-staff-perm-lock-hint');
        if (!text) {
            if (el) {
                el.remove();
            }
            return;
        }
        if (!el) {
            el = document.createElement('span');
            el.className = 'yc-staff-perm-lock-hint';
            host.appendChild(el);
        }
        el.textContent = text;
    }

    function lockReasons(form) {
        var reasons = {};
        DATA.bundles.forEach(function (bundle) {
            var trigger = findInput(form, bundle.code);
            if (!trigger || !trigger.checked) {
                return;
            }
            (bundle.implies || []).forEach(function (code) {
                if (!reasons[code]) {
                    reasons[code] = [];
                }
                reasons[code].push(bundle.label);
            });
        });
        return reasons;
    }

    function syncLocks(form) {
        var reasons = lockReasons(form);
        permInputs(form).forEach(function (input) {
            var why = reasons[input.value];
            if (why && why.length) {
                input.checked = true;
                input.setAttribute('data-yc-perm-locked', '1');
                input.setAttribute('aria-disabled', 'true');
                setHint(input, '由「' + uniqueLabels(why).join('、') + '」带上，不能单独取消');
            } else {
                input.removeAttribute('data-yc-perm-locked');
                input.removeAttribute('aria-disabled');
                setHint(input, '');
            }
        });
    }

    function applyPreset(form, presetCode) {
        var codes = (DATA.presets || {})[presetCode];
        if (!codes || !codes.length) {
            return;
        }
        codes.forEach(function (code) {
            var input = findInput(form, code);
            if (input) {
                input.checked = true;
            }
        });
        syncLocks(form);
    }

    function bindForm(form) {
        if (!form || form.getAttribute('data-yc-staff-perm-bound') === '1') {
            return;
        }
        if (!form.querySelector('input[type="checkbox"][name="permissions"]')) {
            return;
        }
        form.setAttribute('data-yc-staff-perm-bound', '1');
        syncLocks(form);
    }

    function bindAll() {
        document.querySelectorAll('form').forEach(bindForm);
    }

    document.addEventListener('change', function (e) {
        var target = e.target;
        if (!target) {
            return;
        }
        var form = target.closest('form');
        if (!form || !form.querySelector('input[type="checkbox"][name="permissions"]')) {
            return;
        }
        bindForm(form);
        if (target.name === 'preset') {
            applyPreset(form, target.value);
            return;
        }
        if (target.name === 'permissions') {
            syncLocks(form);
        }
    });

    document.addEventListener('click', function (e) {
        var target = e.target;
        if (!target || !target.closest) {
            return;
        }
        var input = target;
        if (target.name !== 'permissions') {
            var label = target.closest('label');
            input = label ? label.querySelector('input[name="permissions"]') : null;
        }
        if (!input || input.name !== 'permissions') {
            return;
        }
        if (input.getAttribute('data-yc-perm-locked') !== '1') {
            return;
        }
        e.preventDefault();
        input.checked = true;
    }, true);

    document.addEventListener('keydown', function (e) {
        var target = e.target;
        if (!target || target.name !== 'permissions') {
            return;
        }
        if (target.getAttribute('data-yc-perm-locked') !== '1') {
            return;
        }
        if (e.key === ' ' || e.key === 'Spacebar' || e.key === 'Enter') {
            e.preventDefault();
            target.checked = true;
        }
    }, true);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindAll);
    } else {
        bindAll();
    }
})();
