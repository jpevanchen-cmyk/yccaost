/**
 * 卖家商品图：逐张 Ajax 上传 + 进度提示（试跑补丁 H）
 */
(function () {
    function csrfToken() {
        var el = document.querySelector('input[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function uploadOne(uploadUrl, dishId, file) {
        var fd = new FormData();
        var token = csrfToken();
        fd.append('upload_dish_image', '1');
        fd.append('dish_id', dishId);
        fd.append('dish_image', file, file.name || 'image.jpg');
        var idemKey = '';
        if (window.YcIdempotency && typeof window.YcIdempotency.newKey === 'function') {
            idemKey = window.YcIdempotency.newKey();
            fd.append(window.YcIdempotency.FIELD, idemKey);
        }
        if (token) {
            fd.append('csrfmiddlewaretoken', token);
        }
        var headers = { 'X-Requested-With': 'XMLHttpRequest' };
        if (token) {
            headers['X-CSRFToken'] = token;
        }
        if (idemKey && window.YcIdempotency && typeof window.YcIdempotency.applyToHeaders === 'function') {
            headers = window.YcIdempotency.applyToHeaders(headers, idemKey);
        }
        return fetch(uploadUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: headers,
            body: fd,
        }).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok) {
                    return { ok: false, error: (data && data.error) || ('服务器拒绝（' + r.status + '）') };
                }
                return data;
            }).catch(function () {
                return { ok: false, error: r.ok ? '服务器返回异常' : ('请求失败（' + r.status + '）') };
            });
        });
    }

    function initBlock(block) {
        var dishId = block.getAttribute('data-dish-id');
        var uploadUrl = block.getAttribute('data-upload-url');
        var fileInput = block.querySelector('.product-image-file-input');
        var uploadBtn = block.querySelector('.product-image-upload-btn');
        var statusEl = block.querySelector('.product-image-upload-status');
        if (!dishId || !uploadUrl || !fileInput || !uploadBtn) return;

        function setStatus(text, show) {
            if (!statusEl) return;
            statusEl.textContent = text || '';
            statusEl.hidden = !show;
        }

        uploadBtn.addEventListener('click', function () {
            var files = Array.prototype.slice.call(fileInput.files || []);
            if (!files.length) {
                if (window.YcNotice) {
                    window.YcNotice.show({ level: 'warning', text: '请先选择要上传的图片', mustAck: true });
                }
                return;
            }
            if (!csrfToken()) {
                if (window.YcNotice) {
                    window.YcNotice.show({ level: 'error', text: '页面安全校验失效，请刷新本页后重试', mustAck: true });
                }
                return;
            }
            uploadBtn.disabled = true;
            fileInput.disabled = true;
            var ok = 0;
            var fails = [];
            var total = files.length;
            var idx = 0;

            function next() {
                if (idx >= total) {
                    uploadBtn.disabled = false;
                    fileInput.disabled = false;
                    fileInput.value = '';
                    setStatus('', false);
                    var summary = '上传完成：成功 ' + ok + ' 张';
                    if (fails.length) summary += '，失败 ' + fails.length + ' 张';
                    if (window.YcNotice) {
                        window.YcNotice.show({
                            level: fails.length && !ok ? 'error' : (fails.length ? 'warning' : 'ok'),
                            text: summary + (fails.length ? '\n' + fails.join('\n') : ''),
                            mustAck: true,
                            onClose: function () {
                                if (ok > 0) window.location.reload();
                            },
                        });
                    } else if (ok > 0) {
                        window.location.reload();
                    }
                    return;
                }
                var file = files[idx++];
                setStatus('正在上传第 ' + idx + ' / ' + total + ' 张…', true);
                uploadOne(uploadUrl, dishId, file).then(function (data) {
                    if (data && data.ok) {
                        ok += 1;
                    } else {
                        fails.push((file.name || '图片') + '：' + ((data && data.error) || '上传失败'));
                    }
                    next();
                }).catch(function () {
                    fails.push((file.name || '图片') + '：请求中断，请重试');
                    next();
                });
            }
            next();
        });
    }

    document.querySelectorAll('.product-image-upload-block[data-dish-id]').forEach(initBlock);
})();
