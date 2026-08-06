/**
 * 写操作幂等 · 前端共用（进度 80 · 幂等第 1 步）
 * - 每次「意图明确的写操作」调用 newKey() 生成唯一编号
 * - 随 POST 带上 Idempotency-Key 请求头或 idempotency_key 表单字段
 * - 后端 idempotency_helpers.run_idempotent 负责去重
 */
(function () {
    var HEADER = 'Idempotency-Key';
    var FIELD = 'idempotency_key';

    function newKey() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }
        return 'yc-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
    }

    function applyToHeaders(headers, key) {
        headers = headers || {};
        if (key) {
            headers[HEADER] = key;
        }
        return headers;
    }

    function applyToFormData(formData, key) {
        if (key && formData && typeof formData.set === 'function') {
            formData.set(FIELD, key);
        }
        return formData;
    }

    window.YcIdempotency = {
        HEADER: HEADER,
        FIELD: FIELD,
        newKey: newKey,
        applyToHeaders: applyToHeaders,
        applyToFormData: applyToFormData,
    };
})();
