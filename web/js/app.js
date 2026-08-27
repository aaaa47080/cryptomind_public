// ========================================
// app.js - 核心應用邏輯與全局變量
// ========================================

window.Utils = window.Utils || {};

window.Utils.debounce = function(fn, delay) {
    let timer;
    return function() {
        const args = arguments;
        const ctx = this;
        clearTimeout(timer);
        timer = setTimeout(function() { fn.apply(ctx, args); }, delay);
    };
};

window.Utils.throttle = function(fn, limit) {
    let inThrottle = false;
    return function() {
        const args = arguments;
        const ctx = this;
        if (!inThrottle) {
            fn.apply(ctx, args);
            inThrottle = true;
            setTimeout(function() { inThrottle = false; }, limit);
        }
    };
};

// Initialize Lucide icons
if (typeof lucide !== 'undefined') {
    lucide.createIcons();
}

// markdown-it 可能不存在於所有頁面（forum/post.html 有自己的載入；主頁從 index.html 載入）
// 安全修復: 關閉 HTML 功能以防止 XSS 攻擊
const md = window.markdownit
    ? window.markdownit({ html: false, linkify: true, breaks: true })
    : null;
window.md = md;

if (!md) {
    // 大聲警告：chat history 跟訊息渲染會壞掉，提示開發者去檢查 index.html 是否漏 CDN
    console.warn(
        '[app.js] window.markdownit not loaded — chat messages will fall back to <pre>. ' +
        'Please ensure index.html loads https://cdn.jsdelivr.net/npm/markdown-it@14.1.0/dist/markdown-it.min.js'
    );
}
AppStore.set('isAnalyzing', false);
let marketRefreshInterval = null;

// ========================================
// 安全工具函數
// ========================================

/**
 * 轉義 HTML 特殊字符，防止 XSS 攻擊
 * 注意：security-utils.js 另有 SecurityUtils.escapeHTML（使用 DOM textContent）。
 * 此版本額外轉義單引號（&#039;），適合用在 HTML attribute 值中，兩者不衝突。
 * 全域程式碼（chat.js、forum.js 等）均使用此簡短名稱 escapeHtml。
 * @param {string} str - 要轉義的字符串
 * @returns {string} 轉義後的字符串
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
window.escapeHtml = escapeHtml;

/**
 * 移除 LLM 輸出中殘留的行內 HTML(渲染前的防禦性清理)。
 *
 * 背景:LLM 偶爾會自作主張用 HTML 標籤做行內引用編號(如 <sup>[3]</sup>),
 * 但 citation_rules 從未要求行內編號,且渲染層(markdown-it html:false /
 * escapeHtml)會把這些標籤當字面文字顯示,造成 UI 出現難看的 <sup>[3]</sup>。
 *
 * 處理策略:
 * 1. <sup>...</sup> / <sub>...</sub>:連同內容一起移除(引用編號在無對應參考
 *    清單時無意義,留著反而誤導)。
 * 2. 其他行內標籤(如 <b>、<span>):移除標籤本身,保留文字內容(避免吃掉正文)。
 *
 * 注意:此函式只處理「行內 HTML 殘留」,正規 markdown(**、##、- 等)不受影響。
 * @param {string} text - 原始文字
 * @returns {string} 清除行內 HTML 後的文字
 */
function stripInlineHtml(text) {
    if (!text) return '';
    return String(text)
        // 1. <sup>...</sup> / <sub>...</sub>:連同內容一起刪除成空字串。
        //    引用標記插在文字中間,刪掉後前後文字應直接相連(不加空白,
        //    否則中文間會出現難看的空格,如「下跌 ，因為」)。
        //    支援:成對標籤、單獨開/閉標籤、帶屬性、自閉合。
        .replace(/<\/?(sup|sub)\b[^>]*>[\s\S]*?<\/?(sup|sub)\b[^>]*>/gi, '')
        .replace(/<\/?(sup|sub)\b[^>]*>/gi, '')
        // 2. 其餘行內 HTML 標籤:去標籤留內容(避免吃掉正文)
        .replace(/<\/?[a-zA-Z][^>]*>/g, '');
}
window.stripInlineHtml = stripInlineHtml;

// ========================================
// AI 分析結果格式化工具
// ========================================

/**
 * 將 AI 分析的結構化文字轉為美觀的 HTML 卡片格式
 * 支援：## 標題、**粗體**、- 項目符號、段落分隔
 * @param {string} text - AI 分析原始文字
 * @returns {string} 格式化後的 HTML
 */
function formatAIAnalysisText(text) {
    if (!text) return '';
    // 先移除 LLM 殘留的行內 HTML(如 <sup>[3]</sup>),再 escape
    const cleaned = stripInlineHtml(text);
    const safe = escapeHtml(cleaned);
    const blocks = safe.split(/\n{2,}/);
    return blocks.map(function (block) {
        block = block.trim();
        if (!block) return '';
        // Section header (## or lines ending with：/:)
        if (/^##\s+/.test(block)) {
            var title = block.replace(/^##\s+/, '').replace(/\*\*/g, '');
            return '<h4 class="text-sm font-bold text-primary/90 mt-4 mb-2 flex items-center gap-2">'
                + '<span class="w-1 h-4 bg-primary/60 rounded-full inline-block"></span>'
                + title + '</h4>';
        }
        // Bullet list block
        if (block.split('\n').every(function (l) { return /^\s*[-•]\s/.test(l); })) {
            var items = block.split('\n').map(function (l) {
                var content = l.replace(/^\s*[-•]\s+/, '');
                return '<li class="text-sm text-textSecondary leading-relaxed ml-1">' + content + '</li>';
            }).join('');
            return '<ul class="space-y-1 list-none mb-2">' + items + '</ul>';
        }
        // Regular paragraph — bold markers as spans
        var formatted = block
            .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-textPrimary font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');
        return '<p class="text-sm text-textSecondary leading-relaxed mb-2">' + formatted + '</p>';
    }).filter(Boolean).join('');
}
window.formatAIAnalysisText = formatAIAnalysisText;

/**
 * 產生 AI 分析摘要區塊的 HTML (含狀態感知按鈕)
 * @param {Object} opts
 * @param {Object} opts.data - API 回應資料 (含 source_mode, ai_error, report)
 * @param {string} opts.tabName - Tab 名稱 (如 'ForexTab')
 * @param {boolean} [opts.hasKey] - 是否已綁定 API Key (用於 US/TW stock pattern)
 * @param {string} [opts.symbolArg] - runDeepAnalysis 的 symbol 參數
 * @param {Function} [opts._t] - i18n 函數
 * @returns {string} HTML string
 */
function renderAIAnalysisSection(opts) {
    var data = opts.data || {};
    var report = data.report || {};
    var summary = report.summary || '';
    var keyPoints = report.key_points || [];
    var tab = opts.tabName || '';
    // Strip trailing "Tab" so "HKStockTab" → "hkstock" matches the i18n namespace
    var i18nNs = tab.toLowerCase().replace(/tab$/, '');
    var _tFn = opts._t || _t;
    var symbolArg = opts.symbolArg || '';

    // Declarative CSP-safe action metadata. The delegated handler only allows
    // known tab objects and never evaluates JavaScript strings.
    var analysisAction = tab + '.runDeepAnalysis';
    var firstAttemptArgs = encodeURIComponent(JSON.stringify(symbolArg ? [symbolArg, false] : [false]));
    var forceRefreshArgs = encodeURIComponent(JSON.stringify(symbolArg ? [symbolArg, true] : [true]));

        // ── State 0: No API key (for US/TW stock pattern)
    if (opts.hasKey === false) {
        return '<div class="rounded-2xl bg-surfaceHighlight border border-borderLight p-5">'
            + '<div class="text-xs font-bold text-textMuted uppercase tracking-widest mb-3">' + (_tFn(i18nNs + '.aiAnalysisSummary') || 'AI Analysis Summary') + '</div>'
            + '<div class="flex flex-col items-center text-center gap-3 py-4">'
            +   '<div class="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">'
            +     '<i data-lucide="key" class="w-5 h-5 text-primary"></i>'
            +   '</div>'
            +   '<div>'
            +     '<p class="text-sm font-bold text-secondary mb-1">' + (_tFn(i18nNs + '.connectAIKey') || 'Configure API Key to Enable AI Analysis') + '</p>'
            +     '<p class="text-xs text-textMuted">' + (_tFn(i18nNs + '.connectAIKeyDesc') || 'Go to Settings to bind your LLM API Key') + '</p>'
            +   '</div>'
            +   '<button data-click="switchTab" data-click-arg="settings" class="px-4 py-2 bg-primary/10 hover:bg-primary/20 text-primary text-xs rounded-xl border border-primary/30 transition flex items-center gap-1.5">'
            +     '<i data-lucide="settings" class="w-3.5 h-3.5"></i>' + (_tFn(i18nNs + '.goToSettings') || 'Go to Settings')
            +   '</button>'
            + '</div></div>';
    }

    // ── State 1: Has deep analysis result — show formatted content + re-analyze
    if (data.source_mode === 'deep_analysis' && summary) {
        var formattedSummary = formatAIAnalysisText(summary);
        var kpHtml = keyPoints.length
            ? '<ul class="space-y-1.5 list-disc list-inside mt-3">'
                + keyPoints.map(function (p) { return '<li class="text-sm text-textSecondary leading-relaxed">' + p + '</li>'; }).join('')
              + '</ul>'
            : '';

        // Cache metadata line
        var cacheMeta = '';
        if (data.cached_at) {
            var cachedTime = new Date(data.cached_at);
            var cachedStr = cachedTime.toLocaleTimeString((window.I18n?.getLanguage?.() || 'zh-TW') === 'en' ? 'en-US' : 'zh-TW', { hour: '2-digit', minute: '2-digit' });
            cacheMeta += '<span class="text-textMuted">' + (_tFn(i18nNs + '.cachedAt') || 'Cached at') + ' ' + cachedStr + '</span>';
        }
        if (data.cache_expires_at) {
            var expiresTime = new Date(data.cache_expires_at);
            var expiresStr = expiresTime.toLocaleTimeString((window.I18n?.getLanguage?.() || 'zh-TW') === 'en' ? 'en-US' : 'zh-TW', { hour: '2-digit', minute: '2-digit' });
            cacheMeta += (cacheMeta ? ' · ' : '') + '<span class="text-textMuted">' + (_tFn(i18nNs + '.nextUpdate') || 'Next update') + ' ' + expiresStr + '</span>';
        }
        var cacheMetaHtml = cacheMeta
            ? '<div class="text-[10px] mt-2 flex items-center gap-1"><i data-lucide="clock" class="w-3 h-3 text-textMuted inline"></i> ' + cacheMeta + '</div>'
            : '';

        // Cooldown badge on re-analyze button
        var cooldownBadge = '';
        if (data.cooldown_remaining && data.cooldown_remaining > 0) {
            var cdMin = Math.ceil(data.cooldown_remaining / 60);
            cooldownBadge = ' <span class="text-[10px] opacity-70">(' + cdMin + ' ' + (_tFn(i18nNs + '.minutesToRefresh') || 'min to refresh') + ')</span>';
        }

        return '<div class="rounded-2xl bg-surfaceHighlight border border-borderLight p-5">'
            + '<div class="flex items-center justify-between mb-3">'
            +   '<div class="text-xs font-bold text-textMuted uppercase tracking-widest">' + (_tFn(i18nNs + '.aiAnalysisSummary') || 'AI Analysis Summary') + '</div>'
            +   '<button data-click="' + analysisAction + '" data-click-args="' + forceRefreshArgs + '" class="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors">'
            +     '<i data-lucide="refresh-cw" class="w-3 h-3"></i> ' + (_tFn(i18nNs + '.reAnalyze') || 'Re-analyze') + cooldownBadge
            +   '</button>'
            + '</div>'
            + formattedSummary
            + kpHtml
            + cacheMetaHtml
            + '</div>';
    }

    // ── State 2: Error — show error message + retry button (amber)
    if (data.ai_error) {
        return '<div class="rounded-2xl bg-surfaceHighlight border border-borderLight p-5">'
            + '<div class="text-xs font-bold text-textMuted uppercase tracking-widest mb-3">' + (_tFn(i18nNs + '.aiAnalysisSummary') || 'AI Analysis Summary') + '</div>'
            + '<div class="flex flex-col items-center text-center gap-3 py-4">'
            +   '<div class="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center">'
            +     '<i data-lucide="alert-triangle" class="w-5 h-5 text-amber-400"></i>'
            +   '</div>'
            +   '<div>'
            +     '<p class="text-sm font-bold text-secondary mb-1">' + escapeHtml(data.ai_error) + '</p>'
            +     '<p class="text-xs text-textMuted">' + (_tFn(i18nNs + '.retryAnalysisDesc') || 'Please try again later or click re-analyze') + '</p>'
            +   '</div>'
            +   '<button data-click="' + analysisAction + '" data-click-args="' + forceRefreshArgs + '" class="px-4 py-2 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 text-xs rounded-xl border border-amber-600/20 transition flex items-center gap-1.5">'
            +     '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>' + (_tFn(i18nNs + '.retryAnalysis') || 'Retry Analysis')
            +   '</button>'
            + '</div></div>';
    }

    // ── State 3: First time (no analysis yet, no error) — show start button (primary)
    return '<div class="rounded-2xl bg-surfaceHighlight border border-borderLight p-5">'
        + '<div class="text-xs font-bold text-textMuted uppercase tracking-widest mb-3">' + (_tFn(i18nNs + '.aiAnalysisSummary') || 'AI Analysis Summary') + '</div>'
        + '<div class="flex flex-col items-center text-center gap-3 py-4">'
        +   '<div class="w-12 h-12 rounded-full bg-gradient-to-br from-primary/20 to-accent/10 flex items-center justify-center">'
        +     '<i data-lucide="brain-circuit" class="w-6 h-6 text-primary"></i>'
        +   '</div>'
        +   '<div>'
        +     '<p class="text-sm font-bold text-secondary mb-1">' + (_tFn(i18nNs + '.aiReadyTitle') || 'AI Deep Analysis Ready') + '</p>'
        +     '<p class="text-xs text-textMuted">' + (_tFn(i18nNs + '.aiReadyDesc') || 'Click the button below to start AI deep analysis') + '</p>'
        +   '</div>'
        +   '<button data-click="' + analysisAction + '" data-click-args="' + firstAttemptArgs + '" class="px-5 py-2.5 bg-primary/15 hover:bg-primary/25 text-primary text-xs rounded-xl border border-primary/30 transition flex items-center gap-2 font-semibold">'
        +     '<i data-lucide="zap" class="w-3.5 h-3.5"></i>' + (_tFn(i18nNs + '.startAIAnalysis') || 'Start AI Analysis')
        +   '</button>'
        + '</div></div>';
}
window.renderAIAnalysisSection = renderAIAnalysisSection;

// ========================================
// 自定義對話框系統 (替代原生 alert/confirm)
// ========================================

/**
 * 處理返回主程式的過渡效果
 * @param {Event} e - 事件對象
 * @param {string} targetTab - 可選的目標 tab（如 'friends', 'chat' 等）
 */
function handleBackToApp(e, targetTab = '') {
    if (e) e.preventDefault();

    // 添加淡出效果（統一使用 0.2s）
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.2s ease-out';

    // 構建目標 URL
    let targetUrl = '/static/index.html';
    if (targetTab) {
        targetUrl += '#' + targetTab;
    }

    setTimeout(() => {
        window.location.href = targetUrl;
    }, 200);
}

// 暴露到全局
window.handleBackToApp = handleBackToApp;

/**
 * 通用的平滑導航函數
 * @param {string} url - 目標 URL
 * @param {number} delay - 過渡延遲（毫秒）
 */
function smoothNavigate(url, delay = 200) {
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.2s ease-out';
    setTimeout(() => {
        window.location.href = url;
    }, delay);
}
window.smoothNavigate = smoothNavigate;

/**
 * 初始化頁面淡入效果
 */
function initPageTransition() {

    // 為所有返回主應用的連結添加平滑過渡
    document
        .querySelectorAll('a[href="/static/index.html"], a[href^="/static/index.html#"]')
        .forEach((link) => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                smoothNavigate(link.href);
            });
        });

    // 為所有論壇內部連結添加平滑過渡
    document.querySelectorAll('a[href^="/static/forum/"]').forEach((link) => {
        // 排除當前頁面的連結
        if (link.href === window.location.href) return;

        link.addEventListener('click', (e) => {
            e.preventDefault();
            smoothNavigate(link.href);
        });
    });
}

// 在 DOM 載入後初始化頁面過渡
document.addEventListener('DOMContentLoaded', () => {
    // 只在論壇頁面執行（非主應用）
    const page = document.body.dataset.page;
    if (page && page !== 'main') {
        initPageTransition();
    }
});

window.initPageTransition = initPageTransition;

/**
 * 顯示確認對話框 (替代 confirm)
 */
function showConfirm(options = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const iconEl = document.getElementById('confirm-modal-icon');
        const titleEl = document.getElementById('confirm-modal-title');
        const messageEl = document.getElementById('confirm-modal-message');
        const confirmBtn = document.getElementById('confirm-modal-confirm');
        const cancelBtn = document.getElementById('confirm-modal-cancel');
        const content = modal ? modal.querySelector('div') : null;

        if (!modal) {
            resolve(window.confirm(options.message || window.I18n.t('common.confirmQuestion')));
            return;
        }

        const {
            title = window.I18n.t('common.confirmAction'),
            message = window.I18n.t('common.confirmActionMessage'),
            type = 'warning',
            confirmText = window.I18n.t('common.confirm'),
            cancelText = window.I18n.t('common.cancel'),
        } = options;

        // 設置圖標和顏色
        const iconConfig = {
            danger: { icon: 'alert-triangle', bg: 'bg-danger/20', color: 'text-danger' },
            warning: { icon: 'alert-circle', bg: 'bg-primary/20', color: 'text-primary' },
            info: { icon: 'info', bg: 'bg-accent/20', color: 'text-accent' },
            success: { icon: 'check-circle', bg: 'bg-success/20', color: 'text-success' },
        };

        const config = iconConfig[type] || iconConfig.warning;

        const ALLOWED_ICON_NAMES = new Set([
            'alert-triangle',
            'alert-circle',
            'info',
            'check-circle',
            'x-circle',
        ]);
        const safeIcon = ALLOWED_ICON_NAMES.has(config.icon) ? config.icon : 'info';

        if (iconEl) {
            iconEl.className = `w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6 ${config.bg}`;
            iconEl.innerHTML = `<i data-lucide="${safeIcon}" class="w-8 h-8 ${config.color}"></i>`;
        }

        if (titleEl) titleEl.textContent = title;
        if (messageEl) messageEl.textContent = message;
        if (confirmBtn) confirmBtn.textContent = confirmText;
        if (cancelBtn) cancelBtn.textContent = cancelText;

        // 根據類型設置確認按鈕樣式
        if (confirmBtn) {
            if (type === 'danger') {
                confirmBtn.className =
                    'flex-1 py-3 bg-danger hover:brightness-110 text-background font-bold rounded-2xl transition shadow-lg';
            } else {
                confirmBtn.className =
                    'flex-1 py-3 bg-primary hover:brightness-110 text-background font-bold rounded-2xl transition shadow-lg';
            }
        }

        if (window.lucide) lucide.createIcons();

        // 觸發動畫
        if (content) {
            content.classList.remove('modal-content-active');
            void content.offsetWidth; // force reflow
            content.classList.add('modal-content-active');
        }

        modal.classList.remove('hidden');

        // 清除舊的事件監聽器並添加新的
        const newConfirmBtn = confirmBtn.cloneNode(true);
        const newCancelBtn = cancelBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

        newConfirmBtn.onclick = () => {
            modal.classList.add('hidden');
            resolve(true);
        };

        newCancelBtn.onclick = () => {
            modal.classList.add('hidden');
            resolve(false);
        };
    });
}

/**
 * 顯示 Alert 對話框 (替代 alert，只有確認按鈕)
 * @param {Object} options - 配置選項
 * @returns {Promise<void>}
 */
function showAlert(options = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const iconEl = document.getElementById('confirm-modal-icon');
        const titleEl = document.getElementById('confirm-modal-title');
        const messageEl = document.getElementById('confirm-modal-message');
        const buttonsEl = document.getElementById('confirm-modal-buttons');

        if (!modal) {
            window.alert(options.message || window.I18n.t('common.notice'));
            resolve();
            return;
        }

        const { title = window.I18n.t('common.notice'), message = '', type = 'info', confirmText = window.I18n.t('common.ok') } = options;

        // 設置圖標和顏色
        const iconConfig = {
            danger: { icon: 'x-circle', bg: 'bg-danger/20', color: 'text-danger' },
            warning: { icon: 'alert-triangle', bg: 'bg-primary/20', color: 'text-primary' },
            info: { icon: 'info', bg: 'bg-accent/20', color: 'text-accent' },
            success: { icon: 'check-circle', bg: 'bg-success/20', color: 'text-success' },
        };

        const config = iconConfig[type] || iconConfig.info;

        const ALLOWED_ICON_NAMES = new Set([
            'alert-triangle',
            'alert-circle',
            'info',
            'check-circle',
            'x-circle',
        ]);
        const safeIcon = ALLOWED_ICON_NAMES.has(config.icon) ? config.icon : 'info';

        iconEl.className = `w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6 ${config.bg}`;
        iconEl.innerHTML = `<i data-lucide="${safeIcon}" class="w-8 h-8 ${config.color}"></i>`;

        titleEl.textContent = title;
        messageEl.textContent = message;

        // 只顯示一個按鈕
        const safeConfirmText = String(confirmText || window.I18n.t('common.ok') || 'OK');
        buttonsEl.innerHTML = `
            <button id="confirm-modal-ok" class="flex-1 py-3 bg-primary hover:brightness-110 text-background font-bold rounded-2xl transition shadow-lg">
                ${escapeHtml(safeConfirmText)}
            </button>
        `;

        lucide.createIcons();
        modal.classList.remove('hidden');

        document.getElementById('confirm-modal-ok').onclick = () => {
            // 恢復兩個按鈕的結構
            buttonsEl.innerHTML = `
                <button id="confirm-modal-cancel" class="flex-1 py-3 bg-surfaceHighlight hover:bg-surfaceHighlight text-textMuted font-bold rounded-2xl transition border border-borderSubtle">
                    ${window.I18n?.t('common.cancel') || 'Cancel'}
                </button>
                <button id="confirm-modal-confirm" class="flex-1 py-3 bg-danger hover:brightness-110 text-background font-bold rounded-2xl transition shadow-lg">
                    ${window.I18n?.t('common.confirm') || 'Confirm'}
                </button>
            `;
            modal.classList.add('hidden');
            resolve();
        };
    });
}

// 全局導出
window.showConfirm = showConfirm;
window.showAlert = showAlert;

// ========================================
// API Key Status Check
// ========================================
async function checkApiKeyStatus() {
    if (window.DEBUG_MODE) console.log('[App] checkApiKeyStatus called');

    const indicator = document.getElementById('api-status-indicator');
    const statusText = document.getElementById('api-status-text');
    const statusDot = indicator ? indicator.querySelector('span') : null;

    // Check LLM Key (async) - 添加錯誤處理
    let currentProvider = null;
    let hasLlmKey = false;
    try {
        if (window.APIKeyManager && typeof window.APIKeyManager.getCurrentProvider === 'function') {
            currentProvider = await window.APIKeyManager.getCurrentProvider();
            hasLlmKey = !!currentProvider;
        }
        if (!hasLlmKey && typeof hydrateSettingsFromBackend === 'function') {
            const hydrated = await hydrateSettingsFromBackend();
            const settings = hydrated?.settings || {};
            // 全域值可能是 BYOK 哨兵 "user_provided"（非真 provider），寫入會毒化選擇
            const isRealProvider =
                settings.primary_model_provider &&
                (window.APIKeyManager?.PROVIDERS || []).includes(
                    settings.primary_model_provider
                );
            if (isRealProvider && window.APIKeyManager) {
                window.APIKeyManager.setSelectedProvider(settings.primary_model_provider);
                if (
                    settings.primary_model_name &&
                    typeof window.APIKeyManager.cacheModelForProvider === 'function'
                ) {
                    // keyless 使用者沒有後端資料列可更新，只同步本地快取即可
                    window.APIKeyManager.cacheModelForProvider(
                        settings.primary_model_provider,
                        settings.primary_model_name
                    );
                }
                const verified = await window.APIKeyManager.getCurrentProvider();
                if (verified) {
                    currentProvider = verified;
                    hasLlmKey = true;
                }
            }
        }
    } catch (e) {
        console.warn('[App] Error checking API key:', e);
        hasLlmKey = false;
    }
    if (window.DEBUG_MODE) console.log('[App] hasLlmKey:', hasLlmKey);

    // 1. Update Top Bar Indicator (LLM Status)
    if (indicator && statusText && statusDot) {
        if (hasLlmKey) {
            const providerName =
                window.__modelConfigCache?.[currentProvider]?.display ||
                (currentProvider === 'openai'
                    ? 'OpenAI'
                    : currentProvider === 'google_gemini'
                      ? 'Gemini'
                      : currentProvider === 'openrouter'
                        ? 'OpenRouter'
                        : currentProvider);

            statusDot.className =
                'w-2 h-2 bg-emerald-500 rounded-full shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse';
            statusText.textContent = `AI Online: ${providerName}`;
            statusText.className = 'text-emerald-400 font-mono tracking-tight';
            statusText.onclick = null;
        } else {
            statusDot.className = 'w-2 h-2 bg-rose-500 rounded-full animate-pulse';
            statusText.textContent = window.I18n ? window.I18n.t('status.systemOffline') : 'SYSTEM OFFLINE (NO KEY)';
            statusText.className =
                'text-rose-400 font-mono tracking-tight cursor-pointer hover:underline';
            statusText.onclick = () => {
                if (typeof openSettings === 'function') openSettings();
            };
        }
    }

    // 2. Control Chat Tab Overlay (LLM Key)
    const llmOverlay = document.getElementById('no-llm-key-warning');
    if (window.DEBUG_MODE)
        console.log('[App] llmOverlay element:', !!llmOverlay, 'hasLlmKey:', hasLlmKey);
    if (llmOverlay) {
        if (hasLlmKey) {
            llmOverlay.classList.add('hidden');
            if (window.DEBUG_MODE) console.log('[App] Hiding LLM overlay (has key)');
        } else {
            llmOverlay.classList.remove('hidden');
            if (window.DEBUG_MODE) console.log('[App] Showing LLM overlay (no key)');
        }
    }

    // 3. Update Chat Input State
    updateChatUIState(hasLlmKey);
}
window.checkApiKeyStatus = checkApiKeyStatus;

// ========================================
// 更新聊天 UI 狀態（根據 API key 是否存在）
// ========================================
async function updateChatUIState(hasApiKey) {
    if (hasApiKey === undefined) {
        hasApiKey = !!(await window.APIKeyManager?.getCurrentProvider());
    }

    // 訪客模式（2026-08-19）：未登入者不需 BYOK——輸入框解鎖、走 guest 端點，
    // 建議按鈕與警告覆蓋層全部不顯示（那些是登入用戶的 BYOK 引導）。
    const isGuest = window.AuthManager && !window.AuthManager.isLoggedIn();
    if (isGuest) {
        const suggestionsAreaG = document.getElementById('suggestions-area');
        if (suggestionsAreaG) suggestionsAreaG.classList.add('hidden');
        const noLlmKeyWarningG = document.getElementById('no-llm-key-warning');
        if (noLlmKeyWarningG) noLlmKeyWarningG.classList.add('hidden');
        const apiKeyWarningG = document.getElementById('api-key-warning');
        if (apiKeyWarningG) apiKeyWarningG.classList.add('hidden');
        const userInputG = document.getElementById('user-input');
        const sendBtnG = document.getElementById('send-btn');
        if (userInputG) {
            userInputG.disabled = false;
            userInputG.placeholder =
                window.I18n?.t('chat.guestPlaceholder') ||
                'Ask anything — free guest mode';
            userInputG.classList.remove('opacity-50', 'cursor-not-allowed');
        }
        if (sendBtnG) {
            sendBtnG.disabled = false;
            sendBtnG.classList.remove('opacity-40', 'cursor-not-allowed');
        }
        return;
    }

    // 1. 建議按鈕區域
    const suggestionsArea = document.getElementById('suggestions-area');
    if (suggestionsArea) {
        suggestionsArea.classList.toggle('hidden', !hasApiKey);
    }

    // 2. API Key 未設置警告覆蓋層
    const noLlmKeyWarning = document.getElementById('no-llm-key-warning');
    if (noLlmKeyWarning) {
        // 沒有 API key 時顯示覆蓋層
        noLlmKeyWarning.classList.toggle('hidden', hasApiKey);
    }

    // 3. 舊的 API Key 警告 (保留相容性)
    const apiKeyWarning = document.getElementById('api-key-warning');
    if (apiKeyWarning) {
        apiKeyWarning.classList.toggle('hidden', hasApiKey);
    }

    // 4. 輸入框和發送按鈕
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    if (userInput) {
        userInput.disabled = !hasApiKey;
        userInput.placeholder = hasApiKey
            ? window.I18n?.t('chat.placeholderReady') || 'Send a command to AI Agent...'
            : window.I18n?.t('chat.systemLocked') || 'System Locked - Please Configure API Key';
        userInput.classList.toggle('opacity-50', !hasApiKey);
        userInput.classList.toggle('cursor-not-allowed', !hasApiKey);
    }

    if (sendBtn) {
        sendBtn.disabled = !hasApiKey;
        sendBtn.classList.toggle('opacity-50', !hasApiKey);
        sendBtn.classList.toggle('cursor-not-allowed', !hasApiKey);
    }
}
window.updateChatUIState = updateChatUIState;

// 暴露到全局供 index.html 控制初始化順序
function initializeUIStatus() {
    if (window.DEBUG_MODE) console.log('[App] initializeUIStatus called');
    if (window.DEBUG_MODE) console.log('[App] APIKeyManager exists:', !!window.APIKeyManager);
    // Note: key/provider status is async, so we can't check it synchronously in debug log

    // 只在初始化時檢查一次
    checkApiKeyStatus();
    // 移除定期輪詢 - API Key 設定後狀態就確定了
    // 狀態變更時應該主動調用 checkApiKeyStatus() 而非輪詢
}
window.initializeUIStatus = initializeUIStatus;

// --- Global Filter Logic Variables ---
AppStore.set('allMarketSymbols', []);
AppStore.set('globalSelectedSymbols', []);
AppStore.set('selectedNewsSources', ['google', 'cryptocompare', 'cryptopanic', 'newsapi']);
AppStore.set('currentFilterExchange', 'okx');

// API Key Validity Cache (populated from per-user key store at runtime)
let validKeys = {};

function updateProviderOptions() {
    // Strip ✅ first so stale marks are removed when a key becomes invalid.
    const select = document.getElementById('llm-provider-select');
    if (!select) return;

    Array.from(select.options).forEach((opt) => {
        const baseText = opt.text.replace(/\s*✅\s*$/, '').trim();
        opt.text = validKeys[opt.value] ? `${baseText} ✅` : baseText;
    });
}
window.updateProviderOptions = updateProviderOptions;

// Watchlist & Chart Variables
let currentUserId = null;

// Pulse Data Cache
if (!AppStore.has('currentPulseData')) {
    AppStore.set('currentPulseData', {});
}

// Trade Proposal

// Analysis Abort Controller
AppStore.set('currentAnalysisController', null);

// ========================================
// Tab Switching (called from HTML after basic UI update)
// ========================================
// Note: The main switchTab() function is now defined inline in index.html
// This function handles additional logic like intervals and API calls

// 記錄上一個 tab，防止相同 tab 重複觸發 setInterval
let _lastOnTabSwitchTab = null;

function onTabSwitch(tab) {
    // ✅ 防止相同 tab 重複創建 interval（快速點擊或初始化時的雙重呼叫）
    if (tab === _lastOnTabSwitchTab) return;
    _lastOnTabSwitchTab = tab;

    // Clear all intervals
    if (marketRefreshInterval) {
        clearInterval(marketRefreshInterval);
        marketRefreshInterval = null;
    }
    if (AppStore.get('pulseInterval')) {
        clearInterval(AppStore.get('pulseInterval'));
        AppStore.set('pulseInterval', null);
    }
    if (AppStore.get('assetsInterval')) {
        clearInterval(AppStore.get('assetsInterval'));
        AppStore.set('assetsInterval', null);
    }

    // Set up new intervals based on tab
    if (tab === 'crypto' || tab === 'market') {
        marketRefreshInterval = setInterval(() => {
            if (typeof refreshScreener === 'function') refreshScreener(false);
        }, 60000);
    }

    if (tab === 'crypto' || tab === 'pulse') {
        AppStore.set('pulseInterval', setInterval(() => {
            if (typeof checkMarketPulse === 'function') checkMarketPulse(false);
        }, 30000));
    }

    // Friends Tab
    if (tab === 'friends') {
        // Force inject component if not already done (though switchTab usually handles this)
        const initFriends = () => {
            if (typeof loadFriendsTabData === 'function') loadFriendsTabData();
        };

        if (window.Components && !window.Components.isInjected('friends')) {
            window.Components.inject('friends').then(initFriends);
        } else {
            initFriends();
        }

        // 移除自動輪詢 - Friends 更新應該透過 WebSocket 或用戶手動刷新
        // 不需要每 5 秒重新載入整個列表，這會造成閃爍和不必要的 API 請求
    }
}

// Make it globally accessible
window.onTabSwitch = onTabSwitch;

// ========================================
// BFCache Restoration — skip redundant init
// ========================================
window.addEventListener('pageshow', function (event) {
    if (!event.persisted) return;
    if (typeof DebugLog !== 'undefined') {
        DebugLog.info('app.pageshowBfCacheRestored');
    }
    if (typeof AppStore !== 'undefined' && typeof AuthManager !== 'undefined') {
        if (AuthManager.currentUser) {
            AuthManager.startTokenRefreshTimer();
        }
    }
});

// ========================================
// Memory Leak Fix: Cleanup on page unload
// ========================================
function cleanupIntervals() {
    // Clear market refresh interval
    if (marketRefreshInterval) {
        clearInterval(marketRefreshInterval);
        marketRefreshInterval = null;
    }
    // Clear pulse interval
    if (AppStore.get('pulseInterval')) {
        clearInterval(AppStore.get('pulseInterval'));
        AppStore.set('pulseInterval', null);
    }
    // Clear assets interval
    if (AppStore.get('assetsInterval')) {
        clearInterval(AppStore.get('assetsInterval'));
        AppStore.set('assetsInterval', null);
    }
}
window.cleanupIntervals = cleanupIntervals;

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    window.cleanupIntervals();
});

// ========================================
// Utility Functions
// ========================================
function updateUserId(uid) {
    currentUserId = uid || null;
}

/**
 * 顯示全局錯誤提示 — 委託給 showToast (Unified Error Display)
 * @param {string} message - 錯誤詳情
 * @param {string} [title] - 錯誤標題（預設 'Error'）
 */
function showError(message, title) {
    if (typeof showToast === 'function') {
        showToast(title || 'Error', 'error', 5000);
    }
    console.error('[Error] ' + message);
}
window.showError = showError;

function quickAsk(text) {
    const input = document.getElementById('user-input');
    if (input) {
        input.value = text;
        sendMessage();
    }
}
window.quickAsk = quickAsk;

const SETTINGS_CONFIG_CACHE_TTL_MS = 60000;

async function hydrateSettingsFromBackend(force = false) {
    if (!AppStore.has('settingsConfigCache')) {
        const cache = { ts: 0, payload: null };
        AppStore.set('settingsConfigCache', cache);
    }

    const cache = AppStore.get('settingsConfigCache');
    const now = Date.now();
    if (!force && cache.payload && now - cache.ts < SETTINGS_CONFIG_CACHE_TTL_MS) {
        return cache.payload;
    }

    const [configData, modelConfigData] = await Promise.all([
        AppAPI.getAppConfig(force),
        AppAPI.getModelConfig(force),
    ]);
    const settings = configData.current_settings || {};
    const preloadedModelConfig = modelConfigData || null;

    Object.keys(validKeys).forEach((k) => delete validKeys[k]);
    let hasBoundLLMKey = false;
    try {
        if (window.APIKeyManager?.getAllKeysMasked) {
            const userKeys = await window.APIKeyManager.getAllKeysMasked();
            if (userKeys && typeof userKeys === 'object') {
                const llmProviders = window.APIKeyManager.PROVIDERS || [];
                for (const [provider, info] of Object.entries(userKeys)) {
                    if (info && info.has_key) {
                        validKeys[provider] = true;
                        // 回應含工具金鑰（tavily 等），判斷 BYOK LLM 綁定要過濾
                        if (llmProviders.includes(provider)) hasBoundLLMKey = true;
                    }
                }
            }
        }
    } catch (_) {}
    if (Object.keys(validKeys).length === 0) {
        validKeys.openai = !!settings.has_openai_key;
        validKeys.google_gemini = !!settings.has_google_key;
        validKeys.openrouter = !!settings.has_openrouter_key;
    }
    updateProviderOptions();

    // 使用者已有 BYOK 綁定時，全域預設（admin 的 primary_model_provider/name）不得
    // 蓋掉使用者自己選的「使用中」provider 與已綁定的 model——否則每次進設定頁
    // 選擇都被重置，造成「換模型得重新綁定」。只在完全沒有 LLM 綁定時套用全域預設。
    // 另外全域值可能是 BYOK 哨兵 "user_provided"（非真 provider），一律不得寫入選擇。
    const globalProviderIsReal =
        settings.primary_model_provider &&
        (window.APIKeyManager?.PROVIDERS || []).includes(settings.primary_model_provider);
    if (globalProviderIsReal && !hasBoundLLMKey) {
        if (window.APIKeyManager?.setSelectedProvider) {
            window.APIKeyManager.setSelectedProvider(settings.primary_model_provider);
        }
        const providerSelect = document.getElementById('llm-provider-select');
        if (providerSelect) {
            providerSelect.value = settings.primary_model_provider;
            if (typeof updateLLMKeyInput === 'function') updateLLMKeyInput();
            if (typeof window.updateAvailableModels === 'function') {
                await window.updateAvailableModels(preloadedModelConfig);
            }
        }
    } else if (typeof window.updateAvailableModels === 'function') {
        // 仍要用預載設定填充 provider / model 下拉（會保留使用者目前的選擇）
        await window.updateAvailableModels(preloadedModelConfig);
    }

    if (settings.primary_model_name && globalProviderIsReal && !hasBoundLLMKey) {
        if (
            settings.primary_model_provider &&
            typeof window.APIKeyManager?.cacheModelForProvider === 'function'
        ) {
            // keyless 使用者沒有後端資料列可更新（POST 只會回 No API key），同步本地快取即可
            window.APIKeyManager.cacheModelForProvider(
                settings.primary_model_provider,
                settings.primary_model_name
            );
        }
        const modelSelect = document.getElementById('llm-model-select');
        const modelInput = document.getElementById('llm-model-input');
        if (isFreeInputProvider(settings.primary_model_provider)) {
            if (modelInput) modelInput.value = settings.primary_model_name;
        } else if (modelSelect) {
            modelSelect.value = settings.primary_model_name;
        }
    }

    cache.payload = { settings, preloadedModelConfig };
    cache.ts = Date.now();
    return cache.payload;
}
window.hydrateSettingsFromBackend = hydrateSettingsFromBackend;

async function openSettings() {
    if (typeof switchTab === 'function') {
        await switchTab('settings');
    }

    if (typeof window.loadSavedApiKeys === 'function') {
        Promise.resolve(window.loadSavedApiKeys()).catch((e) =>
            console.warn('loadSavedApiKeys in settings failed:', e)
        );
    }

    Promise.resolve(hydrateSettingsFromBackend()).catch((e) =>
        console.error('Failed to hydrate settings', e)
    );
}

function closeSettings() {
    // Just switch back to default chat tab or previous tab
    // For simplicity, go to Chat
    switchTab('chat');

    // Force UI status update
    if (typeof checkApiKeyStatus === 'function') {
        checkApiKeyStatus();
    }
}
window.closeSettings = closeSettings;

// ========================================
// LLM Model Selection
// ========================================

/**
 * 更新可用模型列表
 * @param {Object|null} preloadedConfig - 預載的模型配置（可選）
 */
// 依 /api/model-config 動態建立 provider 下拉選項（單一真實來源在後端 MODEL_CONFIG）。
// 新增 provider 後前端不必改——後端加一個 entry，這裡就自動多一個選項。
function populateProviderSelect(modelConfig) {
    const providerSelect = document.getElementById('llm-provider-select');
    if (!providerSelect || !modelConfig) return;

    const providers = Object.keys(modelConfig).filter((p) => p !== 'openai_server');
    if (providers.length === 0) return;

    // 保留目前選擇：優先用「使用者當下在下拉選到的值」，其次才是已存 provider。
    // 反過來(先讀已存的)會有 bug：使用者選了尚未儲存的 provider(如 NVIDIA NIM)，
    // change → updateAvailableModels → 這裡就把選擇蓋回上次儲存的 provider(常是
    // openrouter),造成「選某些廠商全跳回 openrouter」。初次載入時 select 還沒有
    // 選項、value 為空,會自然 fallback 到已存 provider,不影響還原。
    const desired =
        providerSelect.value || window.APIKeyManager?.getSelectedProvider?.() || providers[0];

    providerSelect.innerHTML = '';
    providers.forEach((p) => {
        const option = document.createElement('option');
        option.value = p;
        option.textContent = modelConfig[p]?.display || p;
        providerSelect.appendChild(option);
    });

    providerSelect.value = providers.includes(desired) ? desired : providers[0];
}
window.populateProviderSelect = populateProviderSelect;

async function updateAvailableModels(preloadedConfig = null) {
    const providerSelect = document.getElementById('llm-provider-select');
    const modelSelect = document.getElementById('llm-model-select');
    const modelInput = document.getElementById('llm-model-input');

    if (!providerSelect || !modelSelect) {
        return;
    }

    // 獲取模型配置
    let modelConfig = preloadedConfig;

    if (!modelConfig) {
        if (window.llmState) window.llmState.isModelsLoading = true;
        try {
            modelConfig = await AppAPI.getModelConfig();
        } catch (e) {
            console.error('[updateAvailableModels] Failed to fetch model config:', e);
        } finally {
            if (window.llmState) window.llmState.isModelsLoading = false;
        }
    }

    // 快取給其他模組（saveSettings / hydrate / chat-analysis）判斷 free_input 用
    if (modelConfig) window.__modelConfigCache = modelConfig;

    // 先用最新設定重建 provider 下拉，再讀目前選到的 provider
    populateProviderSelect(modelConfig);

    const provider = providerSelect.value;
    window.APP_CONFIG?.DEBUG_MODE && console.log('[updateAvailableModels] Provider:', provider);

    // free_input 的 provider（OpenRouter / NVIDIA / 火山方舟等）使用文字輸入框，
    // 讓用戶自填任意模型名。
    const isFreeInput =
        modelConfig?.[provider]?.free_input === true ||
        (modelConfig?.[provider]?.available_models || []).length === 0;
    if (isFreeInput) {
        modelSelect.style.display = 'none';
        if (modelInput) {
            modelInput.style.display = 'block';
            modelInput.placeholder = 'e.g., openai/gpt-4o, anthropic/claude-3.5-sonnet';
        }
        if (typeof window.updateLLMFormState === 'function') {
            window.updateLLMFormState();
        }
        return;
    }

    // 其他 provider 使用下拉選單
    modelSelect.style.display = 'block';
    if (modelInput) {
        modelInput.style.display = 'none';
    }

    // 填充模型選項
    const models = modelConfig?.[provider]?.available_models || [];

    // 清空現有選項（不添加 placeholder）
    modelSelect.innerHTML = '';

    if (models.length === 0) {
        console.warn('[updateAvailableModels] No models found for provider:', provider);
        // 添加一個提示選項
        const option = document.createElement('option');
        option.value = '';
        option.textContent = window.I18n ? window.I18n.t('settings.noModels') : 'No models available';
        option.disabled = true;
        modelSelect.appendChild(option);
        return;
    }

    models.forEach((model) => {
        const option = document.createElement('option');
        option.value = model.value;
        option.textContent = model.display || model.value;
        modelSelect.appendChild(option);
    });

    // 設置當前選擇的模型（優先使用已保存的，其次使用 default_model，最後使用第一個）
    const savedModel = window.APIKeyManager?.getModelForProvider?.(provider);
    if (savedModel && models.some((m) => m.value === savedModel)) {
        modelSelect.value = savedModel;
    } else if (modelConfig?.[provider]?.default_model) {
        modelSelect.value = modelConfig[provider].default_model;
    } else if (models.length > 0) {
        modelSelect.value = models[0].value;
    }

    if (typeof window.updateLLMFormState === 'function') {
        window.updateLLMFormState();
    }

    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('[updateAvailableModels] Loaded', models.length, 'models for', provider);
}
window.updateAvailableModels = updateAvailableModels;

// Allow external modules (like llmSettings.js) to update key validity
function setKeyValidity(provider, isValid) {
    validKeys[provider] = isValid;
    updateProviderOptions();
}
window.setKeyValidity = setKeyValidity;

// ========================================
// Navigation Logic - 委託給 global-nav.js (GlobalNav)
// 原有 234 行重複的拖拽/收縮邏輯已移除，統一由 GlobalNav 管理
// ========================================

// 向後相容：index.html 的按鈕仍呼叫此名稱
function toggleNavCollapse() {
    if (window.GlobalNav) window.GlobalNav.toggleCollapse();
}
window.toggleNavCollapse = toggleNavCollapse;

// 初始化主應用的導覽狀態恢復
// 導覽列已改為 index.html 的靜態 HTML，GlobalNav.injectNav() 會因容器已存在而提前 return，
// 連帶跳過原本在 injectNav 內呼叫的初始化。這裡對靜態導覽列補呼叫:
// - restoreNavState() 還原折疊狀態(navCollapsed)。
// - initSidebarNav() 桌機 sidebar 導覽（2026-08-20 Phase 1a）。
// - init{Theme,Language}Switcher()：靜態 nav 時 injectNav 提前 return 會跳過；
//   DOMContentLoaded 時模組（main.js import）已載入，此時 init 才拿得到元件。
document.addEventListener('DOMContentLoaded', () => {
    if (window.GlobalNav) {
        window.GlobalNav.restoreNavState();
        // 桌機 sidebar 導覽（2026-08-20 設計：pill 桌機退場、導覽入 sidebar）
        if (window.GlobalNav.initSidebarNav) {
            window.GlobalNav.initSidebarNav();
        }
        // login modal 手機返回鍵處理（2026-08-21：返回=關 modal 而非跳出網站）
        if (window._setupLoginModalBackHandling) {
            window._setupLoginModalBackHandling();
        }
        if (window.GlobalNav.initThemeSwitcher) {
            window.GlobalNav.initThemeSwitcher();
        }
        if (window.GlobalNav.initLanguageSwitcher) {
            window.GlobalNav.initLanguageSwitcher();
        }
    }
});

// free_input provider（openrouter / nvidia / volcengine 等）用文字框自填任意模型名，
// 其餘用下拉。統一判斷：優先看 model config 的 free_input 旗標（或無預設模型清單），
// 其次 fallback 到「文字框是否顯示」。避免各處寫死 provider === 'openrouter' 而漏掉
// nvidia / volcengine，造成存檔送空模型名、還原時填錯欄位等 bug。
// ⚠️ 限制：DOM fallback 看的是「文字框目前是否顯示」，反映 UI 當前選的 provider，
// 會忽略傳入的 provider 參數。只能在「provider 已反映在 UI 上」之後呼叫
// （例如 hydrate 是先 await updateAvailableModels() 才呼叫本函式）。
function isFreeInputProvider(provider) {
    const cfg = window.__modelConfigCache;
    if (cfg && cfg[provider]) {
        if (cfg[provider].free_input === true) return true;
        return (cfg[provider].available_models || []).length === 0;
    }
    const input = document.getElementById('llm-model-input');
    return !!(input && input.style.display !== 'none');
}
window.isFreeInputProvider = isFreeInputProvider;

// ========================================
// Display Name (Personalization — Trustworthy AI Principal)
// ========================================

function toggleEditDisplayName() {
    const editor = document.getElementById('display-name-editor');
    const input = document.getElementById('display-name-input');
    if (!editor || !input) return;
    editor.classList.toggle('hidden');
    if (!editor.classList.contains('hidden')) {
        // 預填現有 display_name（若有）；否則空
        const current = window.AuthManager?.currentUser?.display_name || '';
        input.value = current;
        input.focus();
    }
}
window.toggleEditDisplayName = toggleEditDisplayName;

async function saveDisplayName() {
    const input = document.getElementById('display-name-input');
    const btn = document.getElementById('btn-save-display-name');
    const cooldownEl = document.getElementById('display-name-cooldown');
    if (!input || !btn) return;

    const name = (input.value || '').trim();
    if (!name) {
        if (window.I18n) window.I18n.t && window.I18n.t('settings.profile.displayNameEmpty');
        if (window.toast) window.toast(window.I18n?.t('settings.profile.displayNameEmpty') || 'Nickname cannot be empty', 'error');
        return;
    }
    if (name.length > 20) {
        if (window.toast) window.toast('Max 20 characters', 'error');
        return;
    }

    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
    try {
        const res = await fetch('/api/user/display-name', {
            method: 'PUT',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: name }),
        });
        const data = await res.json().catch(() => ({}));

        if (res.status === 429 && data?.detail?.reason === 'cooldown') {
            // 冷卻中：顯示下次可改時間
            const next = data.detail.next_available_at;
            const msg = data.detail.message ||
                (window.I18n ? window.I18n.t('settings.profile.cooldown') : 'Can only rename once every 24h');
            if (cooldownEl) {
                cooldownEl.textContent = next ? `${msg} (${next})` : msg;
                cooldownEl.classList.remove('hidden');
            }
            if (window.toast) window.toast(msg, 'warning');
            return;
        }
        // 409:暱稱已被他人使用;422 reserved:取了系統保留名(TON_ 開頭/等於 username)
        if (res.status === 409 || (res.status === 422 && data?.detail?.reason)) {
            const msg = data?.detail?.message || (window.I18n.t('app.nicknameUnavailable') || '無法使用此暱稱');
            if (window.toast) window.toast(msg, 'error');
            return;
        }
        if (!res.ok || !data.success) {
            throw new Error(data?.detail || `HTTP ${res.status}`);
        }

        // 成功:更新本地使用者狀態 + UI + 持久化 + 重拉 greeting
        if (window.AuthManager?.currentUser) {
            window.AuthManager.currentUser.display_name = name;
            // 持久化到 localStorage,避免下次 backend restore 蓋掉(雖然 backend
            // 也會帶回 display_name,但這裡先存確保立即一致)
            if (typeof window.AuthManager._saveUserSession === 'function') {
                window.AuthManager._saveUserSession();
            }
            // 重繪所有顯示名的 UI(側欄/導覽/個人頁) — 優先用 display_name
            if (typeof window.AuthManager._updateUI === 'function') {
                window.AuthManager._updateUI(true);
            }
        }
        const usernameEl = document.getElementById('profile-username');
        if (usernameEl) usernameEl.textContent = name;
        const editor = document.getElementById('display-name-editor');
        if (editor) editor.classList.add('hidden');
        if (cooldownEl) cooldownEl.classList.add('hidden');
        if (window.toast) window.toast(
            window.I18n?.t('settings.profile.displayNameSaved') || 'Nickname saved',
            'success'
        );
        // 重拉歡迎訊息(後端已清 greeting 快取,會用新暱稱重新生成)
        if (typeof window._loadWelcomeGreeting === 'function') {
            window._loadWelcomeGreeting();
        }
    } catch (err) {
        console.error('[saveDisplayName]', err);
        if (window.toast) window.toast(
            window.I18n?.t('settings.profile.saveFailed') || 'Save failed',
            'error'
        );
    } finally {
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
}
window.saveDisplayName = saveDisplayName;

// ========================================
// Keyboard: Escape closes top modal
// ========================================
document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    const modals = document.querySelectorAll('.modal-overlay:not(.hidden)');
    if (modals.length === 0) return;
    const topModal = modals[modals.length - 1];
    const closeBtn = topModal.querySelector('[data-close-modal]');
    if (closeBtn) {
        closeBtn.click();
    } else {
        topModal.classList.add('hidden');
    }
});

export {
    md,
    escapeHtml,
    handleBackToApp,
    smoothNavigate,
    initPageTransition,
    showConfirm,
    showAlert,
    checkApiKeyStatus,
    updateChatUIState,
    initializeUIStatus,
    updateProviderOptions,
    onTabSwitch,
    cleanupIntervals,
    showError,
    quickAsk,
    hydrateSettingsFromBackend,
    openSettings,
    closeSettings,
    updateAvailableModels,
    setKeyValidity,
    toggleNavCollapse,
};
