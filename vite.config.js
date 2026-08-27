import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
    root: 'web',
    base: '/static/',
    plugins: [
        // Service worker — 只快取 app shell（金融平台絕不快取 API/WebSocket 即時資料）。
        // - generateSW：用 Workbox 自動生成 SW（業界標準，處理 precache/版本更新）
        // - manifest:false：manifest 已由後端 /manifest.webmanifest 動態產生，不重複
        // - injectRegister:false：自訂註冊腳本（web/public/sw-register.js），處理
        //   scope:'/'（base 是 /static/，預設 scope 只到 /static/，要控制全站 / 需
        //   後端 /sw.js 路由送 Service-Worker-Allowed: / + 註冊時 scope:'/'）
        VitePWA({
            strategies: 'generateSW',
            registerType: 'autoUpdate',
            injectRegister: false,
            manifest: false,
            // sw.js 產到 publicDir（web/public/），build 後在 dist/static/sw.js。
            // 後端 /sw.js 路由會服務這份檔並送正確 header。
            filename: 'sw.js',
            workbox: {
                // 只 precache app shell（HTML/CSS/JS chunk + manifest）。
                // 不快取圖片/字體（讓它們走 HTTP cache，SW 不介入）。
                globPatterns: ['**/*.{js,css,html,webmanifest}'],
                // 嚴格上限：app shell 不該超過 5MB
                maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
                // SPA navigation fallback 到 index.html（app shell），
                // 但排除 /api/ 與 /ws（金融即時資料絕不 fallback 到快取）
                navigateFallback: 'index.html',
                navigateFallbackDenylist: [/^\/api\//, /^\/ws/, /^\/sw\.js/, /^\/manifest\.webmanifest/, /^\/tonconnect-manifest/],
                // 不設 runtimeCaching：precache 已涵蓋 app shell。
                // 所有未 precache 的請求（API/WebSocket/圖片）預設走網路，
                // 即金融即時資料絕不快取。
                // SW 更新：新版本接管
                skipWaiting: true,
                clientsClaim: true,
            },
            devOptions: {
                enabled: false, // dev 不啟用 SW（避免干擾 HMR）
            },
        }),
    ],
    build: {
        outDir: '../dist/static',
        emptyOutDir: false,
        sourcemap: true,
        chunkSizeWarningLimit: 800,
        // 關閉 modulepreload：Vite 的 __vitePreload wrapper 會在 dynamic import 前
        // 建立 <link rel=modulepreload> 並等待 onload，但在 Zeabur 線上環境對「已預載
        // 的依賴（rolldown-runtime/forum/premium）」這個 onload 永遠不觸發，導致
        // _ensureTabModules 的 import() Promise 永久 pending → tab 模板載不到 →
        // settings/各股市/admin 等「動態注入」tab 全白屏（chat 首屏靜態不受影響）。
        // 關閉後 dynamic import 走原生 import()（實測 105ms 成功），不再 hang。
        // 代價：首次切 tab 時依賴 chunk 不預載（稍慢幾十 ms），換來不再卡死。
        modulePreload: false,
        rollupOptions: {
            // 多頁 build（2026-08-14）：
            // forum/*.html 與 premium.html 是獨立頁面，以 type="module" 載入 raw
            // /static/js/*.js。Dockerfile 會刪除 raw web/js/*.js（只留豁免清單），
            // 因此這些頁必須各自成為 Vite 多頁 entry，讓它們的 module script 被打包
            // 進 assets/ 並把 HTML 改寫成 hashed asset URL，否則 prod 會 404。
            input: {
                main: 'web/index.html',
                'forum/index': 'web/forum/index.html',
                'forum/post': 'web/forum/post.html',
                'forum/create': 'web/forum/create.html',
                'forum/dashboard': 'web/forum/dashboard.html',
                'forum/messages': 'web/forum/messages.html',
                'forum/profile': 'web/forum/profile.html',
                'forum/premium': 'web/forum/premium.html',
            },
            output: {
                // rolldown 正規分 chunk API（manualChunks 為相容層、行為不保證——
                // 2026-08-24 事故：共用模組被併進 SPA main 入口 chunk，論壇頁
                // import main → 整個 SPA 在論壇頁執行、排版崩壞。見 forum/*.html
                // 的單一薄 entry 重構與 web/js/pages/ 說明）。
                codeSplitting: {
                    groups: [
                        { name: 'forum-app-core', priority: 10, test: /web[\\/]js[\\/]forum-app\.js$/ },
                        {
                            // 論壇多頁與 SPA 共用的模組一律收進 shared-core，
                            // entry（main 與各 forum boot）之間永遠不可能互相 import
                            name: 'shared-core',
                            priority: 10,
                            minSize: 0,
                            test: /web[\\/]js[\\/](store|utils|api-client|ton-auth|ui-shell|security-utils|app|apiKeyManager|auth|nav-config|global-nav|i18n|messages|friends|premium|forum-config|forum-api)\.js$/,
                        },
                        { name: 'shared-lang', priority: 10, minSize: 0, test: /web[\\/]js[\\/]components[\\/]LanguageSwitcher\.js$/ },
                    ],
                },
            },
        },
    },
    server: {
        proxy: {
            '/api': 'http://localhost:8080',
            '/ws': {
                target: 'ws://localhost:8080',
                ws: true,
            },
            '/static': 'http://localhost:8080',
        },
    },
});
