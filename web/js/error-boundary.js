// ========================================
// error-boundary.js — 全域 JS 錯誤捕捉 → 後端 → admin 可見
// 2026-08-23 Phase 2：現在 JS 錯誤只在 console 消失，使用者遇到問題
// 我們無從得知。加上後能從 admin 面板看到前端錯誤率。
// ========================================

(function () {
    'use strict';

    var MAX_QUEUE = 20;
    var FLUSH_INTERVAL = 30000; // 30 秒批量上報
    var queue = [];
    var timer = null;
    var sessionId = null;

    function getErrId() {
        return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    }

    function captureError(error, context) {
        try {
            var entry = {
                id: getErrId(),
                message: String(error && error.message ? error.message : error).slice(0, 500),
                stack: error && error.stack ? String(error.stack).slice(0, 2000) : '',
                context: context || 'unknown',
                url: window.location.hash || window.location.pathname,
                userAgent: navigator.userAgent.slice(0, 200),
                timestamp: new Date().toISOString(),
                session_id: window.currentSessionId || sessionId,
            };
            queue.push(entry);
            if (queue.length > MAX_QUEUE) queue.shift();
            scheduleFlush();
        } catch (_e) {
            // 錯誤捕捉本身不能炸
        }
    }

    function scheduleFlush() {
        if (timer) return;
        timer = setTimeout(flush, FLUSH_INTERVAL);
    }

    async function flush() {
        timer = null;
        if (!queue.length) return;
        var batch = queue.splice(0);
        try {
            await fetch('/api/frontend-errors', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ errors: batch }),
            });
        } catch (_e) {
            // 上報失敗靜默（不要因為上報失敗再觸發錯誤）
        }
    }

    // 頁面卸載前強制 flush
    window.addEventListener('beforeunload', function () {
        if (queue.length) {
            navigator.sendBeacon &&
                navigator.sendBeacon(
                    '/api/frontend-errors',
                    JSON.stringify({ errors: queue })
                );
        }
    });

    // 1. 未捕捉的 JS 錯誤
    window.addEventListener('error', function (e) {
        captureError(e.error || e.message, 'window.onerror');
    });

    // 2. Promise rejection
    window.addEventListener('unhandledrejection', function (e) {
        captureError(e.reason, 'unhandledrejection');
    });

    // 3. console.error 攔截（只攔有 Error 物件的）
    var origError = console.error;
    console.error = function () {
        for (var i = 0; i < arguments.length; i++) {
            if (arguments[i] instanceof Error) {
                captureError(arguments[i], 'console.error');
                break;
            }
        }
        origError.apply(console, arguments);
    };

    // 暴露手動上報介面
    window.reportFrontendError = captureError;
    window.__flushFrontendErrors = flush;
})();
