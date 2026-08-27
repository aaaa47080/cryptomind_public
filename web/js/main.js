// ========================================
// main.js - Application Entry Point
// ========================================
// Loaded via <script type="module"> in index.html.
// Import order matters: dependencies first, then consumers.
//
// Side-effect-only modules (no exports needed):
//   logger.js, ton-auth.js, i18n.js
//
// Simple modules (already converted to ES module format):
//   store.js, utils.js, api-client.js, security-utils.js, ui-shell.js,
//   legal.js, filter.js, testMode.js, wallet.js, alerts.js
//
// Complex modules (NOT yet converted internally — imported for side-effects only):
//   app.js, apiKeyManager.js, auth.js, friends.js, messages.js,
//   forum-app.js, admin.js, spa.js, components/*, chat-*.js, etc.
// ========================================

// ─── Phase 0: Telegram Mini App integration (MUST be first) ──────────────
// Sets window.TWA_RETURN_URL + WebApp.ready()/expand() before TON Connect
// initialises. Imported here (not a standalone <script>) so the Vite build
// actually bundles + ships it — a plain /js/ script tag 404s in production.
import './telegram-webapp.js';

// ─── Phase 1: Core utilities (MUST load first) ───────────────────────────
import './store.js';           // AppStore (pub/sub state)

AppStore.restore();

window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    // Suppress non-actionable errors that don't need user notification
    if (reason instanceof DOMException && reason.name === 'AbortError') return; // cancelled fetch
    if (reason?.name === 'AbortError') return;
    // TON Connect SDK 拋的 "Operation aborted"（tab 切換 / 使用者取消連線 / bridge 超時）
    // 不是 bug——是 SDK 內部 AbortController 的正常行為，但 SDK 没 catch 這個 rejection。
    // 過濾掉避免 console 刷屏 + 使用者看到不必要的 error toast。
    const msg = typeof reason?.message === 'string' ? reason.message : '';
    if (msg.includes('Operation aborted') || msg.includes('TON_CONNECT_SDK_ERROR')) return;
    console.error('[Unhandled Rejection]', reason);
    window.__lastUnhandledReasonMessage =
        (typeof reason?.message === 'string' && reason.message.trim()) ||
        (typeof reason === 'string' && reason.trim()) ||
        (window.I18n ? window.I18n.t('app.unexpectedError') : 'An unexpected error occurred');
    if (typeof showToast === 'function') {
        showToast(window.__lastUnhandledReasonMessage || (window.I18n ? window.I18n.t('app.unexpectedError') : 'An unexpected error occurred'), 'error');
        return;
    }
});

window.addEventListener('error', (event) => {
    console.error('[Global Error]', event.error);
});

import './utils.js';           // AppUtils (shared helpers)
import './api-client.js';      // AppAPI (HTTP client)

// ─── Phase 2: Side-effect-only modules ────────────────────────────────────
// ton-auth.js sets up window.safeTonLogin (TON Connect) + the shared
// window.tonConnectUI instance used by premium payments. Must load before
// auth.js so the login button wiring is ready.
import './ton-auth.js';

// ─── Phase 3: UI shell & layout ───────────────────────────────────────────
import './ui-shell.js';        // UIShell, showToast
import './layout-debug.js';    // 底部版面數字面板（只在 #layout-debug 時顯示）

// ─── Phase 4: Security & utilities ────────────────────────────────────────
import './security-utils.js';  // SecurityUtils (XSS, CSP)

// ─── Phase 5: App core ────────────────────────────────────────────────────
import './app.js';             // Main app logic
import './apiKeyManager.js';   // API key management
import './auth.js';            // AuthManager

// ─── Phase 6: Components system (load order matters) ──────────────────────
import './components/css-constants.js';
import './telegram-link.js';
import './components/core.js';
// 所有 tab-*.js 模板已改 dynamic import（spa.js 切 tab 時按需載入）：
//   hidden:true：tab-friends, tab-forum
//   defaultEnabled:false：tab-commodity, tab-forex, tab-hkstock, tab-astock,
//     tab-jpstock, tab-instock, tab-krstock
//   預設啟用但非首屏：tab-twstock, tab-usstock, tab-admin, tab-crypto, tab-settings

// ─── Phase 7: Notifications ───────────────────────────────────────────────
import './notification-service.js';
import './components/NotificationBell.js';
import './components/NotificationPanel.js';

// ─── Phase 8: Settings & tools ────────────────────────────────────────────
import './llmSettings.js';
import './testMode.js';
import './toolSettings.js';
import './filter.js';

// ─── Phase 9: Chat system ─────────────────────────────────────────────────
import './chat-state.js';
import './chat-sessions.js';
import './chat-stream-ui.js';
import './chat-hitl.js';
import './analysisSettings.js';
import './chat-analysis.js';
import './chat-history.js';
import './chat-init.js';

// ─── Phase 10: Social features ────────────────────────────────────────────
// friends.js / messages.js 已改 dynamic import（friends tab 為 hidden:true，
// messages 由獨立頁面載入）— spa.js 切 friends tab 時載入

// ─── Phase 11: Navigation ─────────────────────────────────────────────────
import './nav-config.js?v=62';
import './global-nav.js';

// ─── Phase 12: Market data ────────────────────────────────────────────────
import './market-status.js';   // 被所有 stock tab 依賴，留首屏（共享依賴）
// crypto 相關（market-screener/chart/ws/pulse）已改 dynamic import —
//   spa.js 切 crypto tab 時載入
// twstock / usstock / board 已改 dynamic import（預設啟用但非首屏）
// commodity / forex / hkstock / astock / jpstock / instock / krstock
// 已改 dynamic import（皆 defaultEnabled:false）— spa.js 切對應 tab 時載入

// ─── Phase 13: Forum ──────────────────────────────────────────────────────
// forum-config / forum-api / forum-app 已改 dynamic import（forum tab hidden）
// premium.js 已改 dynamic import（settings tab 用，與 forum-config 綁定）— 
//   spa.js 切 settings tab 時載入

// ─── Phase 14: Wallet & alerts ────────────────────────────────────────────
// wallet.js / alerts.js 已改 dynamic import（wallet 預設關閉；alerts 由
// twstock/usstock tab 用，跟著 stock 模組一起載入）

// ─── Phase 15: Safety & admin ─────────────────────────────────────────────
// admin.js / admin-stats.js 已改 dynamic import（admin tab locked）

// ─── Phase 16: SPA & modals ───────────────────────────────────────────────
import './spa.js?v=64';
import './chat-preset.js';
import './modals.js';
import './legal.js';
import './feedback.js';

// ─── Phase 17: Internationalization (last — translates everything) ────────
import './i18n.js';
import './components/LanguageSwitcher.js';
import './components/ThemeSwitcher.js';
