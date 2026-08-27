// sw-register.js — service worker 註冊（只快取 app shell）
// 放在 publicDir（web/public/），build 後原樣到 dist/static/sw-register.js，
// 不被 Vite 處理，Dockerfile 刪檔規則（只刪 web/js/*.js）不影響本檔。
//
// 策略：app shell（HTML/CSS/JS chunk）由 Workbox precache/StaleWhileRevalidate；
// 所有 /api/* 與 WebSocket 一律 network-only（金融平台絕不快取即時資料）。
// SW 檔在 /sw.js（後端路由，送 Service-Worker-Allowed: /），註冊時 scope:'/'。
(function () {
    // SW 需要 secure context：只在 https 或 localhost 註冊（vite dev 的非 secure
    // IP 測試、或 file:// 不註冊，避免錯誤刷屏）
    if (!('serviceWorker' in navigator)) return;
    if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
        return;
    }

    window.addEventListener('load', function () {
        navigator.serviceWorker
            .register('/sw.js', { scope: '/' })
            .then(function (reg) {
                console.debug('[sw] registered, scope:', reg.scope);
            })
            .catch(function (err) {
                // 註冊失敗不阻塞 app（SW 只是加速重複造訪，非核心功能）
                console.debug('[sw] registration skipped:', err.message);
            });

        // autoUpdate：偵測到新版 SW 接管時，提示使用者重新整理。
        // Workbox skipWaiting+clientsClaim 會讓新 SW 立即接管，
        // 這裡只在「使用者剛回來且已有新版」時提示一次，不打斷使用中 session。
        let refreshing = false;
        navigator.serviceWorker.addEventListener('controllerchange', function () {
            if (refreshing) return;
            refreshing = true;
            // 不強制重整（金融對話 session 不該被打斷）；只在新版接管時靜默記錄。
            console.debug('[sw] controller changed — new version active');
        });
    });
})();
