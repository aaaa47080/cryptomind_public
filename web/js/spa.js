// ========================================
// spa.js - Single Page Application Core
// ========================================

// AppStore is the single source of truth for active tab
AppStore.set('activeTab', 'chat');

// Helper to get activeTab from AppStore (source of truth) with localStorage fallback
function getActiveTab() {
    return AppStore.get('activeTab') || localStorage.getItem('activeTab') || 'chat';
}

var VALID_TABS = [
    'chat', 'crypto', 'twstock', 'usstock',
    'journal', 'commodity', 'forex', 'hkstock', 'astock', 'jpstock', 'instock', 'krstock',
    'wallet', 'wallet-monitor', 'trust', 'friends', 'forum', 'settings', 'admin',
    'ai-studio', 'discover', 'studio',
];

// 功能 tab（ai-studio/discover）：不在底部導覽，但可經 deep-link 到達。
// 2026-08-24 起 customize 閘門整體移除（見 executeTabSwitch）——此集合
// 僅作文件說明保留，不再參與導覽判斷。
const NON_NAV_TABS = new Set(['ai-studio', 'discover']);

// Normalize removed/unknown routes before asynchronous app initialization begins.
// This prevents a dormant feature hash (for example an old bookmark) from
// remaining visible while authentication, i18n, and navigation preferences load.
const _requestedInitialTab = window.location.hash.replace('#', '');
// 2026-08-24 事故守門：spa.js 誤在非 SPA 頁執行（如 chunk graph 異常把 main
// 入口拉進論壇頁）時，replaceState '#chat' 會改寫論壇頁 URL、boot 流程會
// 操弄不存在 的 SPA 容器。#chat-tab 是 SPA 的根容器——不存在即整個模組靜默。
const _IS_SPA_PAGE = !!document.getElementById('chat-tab');
if (_IS_SPA_PAGE && _requestedInitialTab && !VALID_TABS.includes(_requestedInitialTab)) {
    history.replaceState({ tab: 'chat' }, '', '#chat');
}

// ========================================
// Lazy module loading (code-splitting)
// ========================================
// 首屏只載入核心 + chat。其餘 tab 的模組在切到該 tab 時才 dynamic import，
// 讓 Vite 切成獨立 chunk，首屏 bundle 大幅縮小。SPA 架構本來就是
// 「import 時註冊 window.X、切 tab 時才 init」，且跨模組呼叫全用
// typeof guard（click-delegator.js），所以延遲載入不會破壞功能——
// 唯一要確保的是 tab init 執行前模組已 await 完成。
//
// _TAB_MODULES: tabId → 該 tab 需要的模組清單（dynamic import factory）。
// 載入過的 tab Vite/瀏覽器會自動快取，重複切換不會重新下載。
const _TAB_MODULES = {
    // hidden:true（Phase 2 未開放，使用者根本看不到）
    friends: () => Promise.all([
        import('./friends.js'),
        import('./messages.js'),
        import('./components/tab-friends.js'),
    ]),
    // journal（統一帳本 Dashboard）：骨架在 index.html，模組只需 tab-journal。
    // 2026-08-22 盤點：此前缺此鍵 → tab-journal.js 從未被載入 → JournalTab
    // undefined → Dashboard 永遠卡「載入中」。
    journal: () => Promise.all([
        import('./components/tab-journal.js'),
    ]),
    forum: () => Promise.all([
        import('./forum-api.js'),
        import('./forum-app.js'),
        import('./components/tab-forum.js'),
    ]),
    // defaultEnabled:false（使用者要 Customize 勾選才出現）
    commodity: () => Promise.all([
        import('./commodity.js'),
        import('./components/tab-commodity.js'),
    ]),
    forex: () => Promise.all([
        import('./forex.js'),
        import('./components/tab-forex.js'),
    ]),
    hkstock: () => Promise.all([
        import('./hkstock.js'),
        import('./components/tab-hkstock.js'),
    ]),
    astock: () => Promise.all([
        import('./astock.js'),
        import('./components/tab-astock.js'),
    ]),
    jpstock: () => Promise.all([
        import('./jpstock.js'),
        import('./components/tab-jpstock.js'),
    ]),
    instock: () => Promise.all([
        import('./instock.js'),
        import('./components/tab-instock.js'),
    ]),
    krstock: () => Promise.all([
        import('./krstock.js'),
        import('./components/tab-krstock.js'),
    ]),
    // 預設啟用但非首屏（chat 為首屏預設 tab）
    twstock: () => Promise.all([
        import('./twstock.js'),
        import('./alerts.js'),            // loadUserAlerts 由 twstock/usstock 用
        import('./components/tab-twstock.js'),
    ]),
    usstock: () => Promise.all([
        import('./usstock.js'),
        import('./alerts.js'),
        import('./components/tab-usstock.js'),
    ]),
    wallet: () => Promise.all([
        import('./wallet.js'),
        // wallet tab 無獨立 tab-*.js 模板
    ]),
    'wallet-monitor': () => Promise.all([
        import('./walletMonitorTab.js'),
        import('./components/tab-wallet-monitor.js'),
    ]),
    trust: () => Promise.all([
        import('./trustTab.js'),
        import('./trustScoreManager.js'),
        import('./components/tab-trust.js'),
    ]),
    // Phase 1/3：AI Studio + Discover（lazy chunk；詳 design.md §7/§10）
    'ai-studio': () => Promise.all([
        import('./ai-studio.js'),
        import('./components/tab-ai-studio.js'),
    ]),
    discover: () => Promise.all([
        import('./discover.js'),
        import('./components/tab-discover.js'),
    ]),
    // 提案工作台（募資者模式，design 2026-08-16）
    studio: () => Promise.all([
        import('./studio.js'),
        import('./components/tab-studio.js'),
    ]),
    admin: () => Promise.all([
        import('./admin.js'),
        import('./admin-stats.js'),
        import('./admin-visitors.js'),
        import('./admin-audit.js'),
        import('./admin-wallet-monitor.js'),
        import('./components/tab-admin.js'),
    ]),
    // crypto tab（market-screener/chart/ws/pulse 互相依賴，整組一起載入）
    crypto: () => Promise.all([
        import('./market-screener.js'),
        import('./market-chart.js'),
        import('./market-ws.js'),
        import('./pulse.js'),
        import('./components/tab-crypto.js'),
    ]),
    // settings tab（init 呼叫 PremiumManager/loadPremiumStatus/updatePriceDisplays，
    // 故 premium + forum-config 需在 settings init 前載入）
    settings: () => Promise.all([
        import('./forum-config.js'),
        import('./premium.js'),
        import('./components/tab-settings.js'),
    ]),
};

/** 按需載入該 tab 的模組（若已列在 _TAB_MODULES）。未列的 tab 表示模組仍在首屏。 */
async function _ensureTabModules(tabId) {
    const loader = _TAB_MODULES[tabId];
    if (!loader) return;
    try {
        await loader();
    } catch (e) {
        console.error(`[spa] dynamic import failed for tab "${tabId}":`, e);
    }
}

// ========================================
// Navigation Logic (Updated with Smooth Transitions)
// ========================================

/**
 * Switch to a different tab with smooth transition
 * @param {string} tabId - The tab ID to switch to
 * @param {boolean} fromPopState - Whether this is triggered by browser back/forward
 * @returns {Promise<void>}
 */
var _switchTabTimer = null;

async function switchTab(tabId, fromPopState = false) {
    if (!VALID_TABS.includes(tabId)) {
        console.warn(`Invalid tab '${tabId}', falling back to 'chat'`);
        tabId = 'chat';
    }

    // [Security] Strict Login Check
    // 訪客模式（2026-08-19 設計）：chat tab 開放訪客（guest AI 免登入體驗），
    // 其他 tab 仍需登入 —— 彈登入 modal 並退回 chat。
    if (window.AuthManager && !window.AuthManager.isLoggedIn()) {
        if (tabId !== 'chat') {
            const modal = document.getElementById('login-modal');
            if (modal && modal.classList.contains('hidden')) {
                console.warn('⚠️ Access denied: User not logged in. Showing login modal.');
                modal.classList.remove('hidden');
            }
            tabId = 'chat';
        }
    }

    if (_switchTabTimer) {
        clearTimeout(_switchTabTimer);
        _switchTabTimer = null;
    }

    const currentTab = document.querySelector('.tab-content:not(.hidden)');

    if (currentTab && currentTab.id !== tabId + '-tab') {
        currentTab.style.opacity = '0';
        currentTab.style.transform = 'translateY(-5px)';
        currentTab.style.transition = 'all 0.2s ease-in';

        return new Promise((resolve) => {
            _switchTabTimer = setTimeout(async () => {
                _switchTabTimer = null;
                await executeTabSwitch(tabId, fromPopState);
                resolve();
            }, 150);
        });
    } else {
        return await executeTabSwitch(tabId, fromPopState);
    }
}
window.switchTab = switchTab;

// 監聽瀏覽器返回/前進按鈕
window.addEventListener('popstate', (event) => {
    let targetTab = 'chat';

    if (event.state && event.state.tab) {
        targetTab = event.state.tab;
    } else if (window.location.hash) {
        const hashTab = window.location.hash.replace('#', '');
        if (VALID_TABS.includes(hashTab)) {
            targetTab = hashTab;
        }
    }

    // 使用 fromPopState=true 避免再次 pushState
    switchTab(targetTab, true);
});

/**
 * Navigate to forum (save current tab for return)
 */
function navigateToForum() {
    // 保存當前 tab 到 sessionStorage
    const currentTab = getActiveTab();
    sessionStorage.setItem('returnToTab', currentTab);
    smoothNavigate('/static/index.html#forum');
}
window.navigateToForum = navigateToForum;

/**
 * Execute the actual tab switching logic
 * @param {string} tabId - The tab ID to switch to
 * @param {boolean} fromPopState - Whether this is triggered by browser back/forward
 * @returns {Promise<void>}
 */
// 「我的 AI」摘要卡計數：Agents（catalog，flag off 顯示 –）、Presets（flag off
// 顯示 –）、Skills、Memories。任何失敗只留 –，不阻斷 Settings 載入。
async function loadMyAISummaryCounts() {
    const set = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v;
    };
    try {
        const [profiles, presets, skills, memories] = await Promise.allSettled([
            AppAPI.get('/api/agent-profiles'),
            AppAPI.get('/api/agent-presets'),
            AppAPI.get('/api/skills'),
            AppAPI.get('/api/memory/facts'),
        ]);
        set('myai-count-agents', profiles.status === 'fulfilled' && profiles.value?.profiles ? String(profiles.value.profiles.length) : '–');
        set('myai-count-presets', presets.status === 'fulfilled' && presets.value?.quota ? String(presets.value.quota.used ?? '–') : '–');
        const skillsData = skills.status === 'fulfilled' ? skills.value : null;
        const skillCount = skillsData
            ? ((skillsData.official?.length ?? 0) + (skillsData.custom?.length ?? 0)) ||
              (Array.isArray(skillsData.skills) ? skillsData.skills.length : 0)
            : 0;
        set('myai-count-skills', skills.status === 'fulfilled' ? String(skillCount) : '–');
        set('myai-count-memories', memories.status === 'fulfilled' && memories.value?.total != null ? String(memories.value.total) : '–');
    } catch (err) {
        // 全部留 –
    }
}
window.loadMyAISummaryCounts = loadMyAISummaryCounts;

async function executeTabSwitch(tabId, fromPopState = false) {
    // AI Studio 返回鈕：記錄進入前的分頁（回不去就 fallback chat）
    if (tabId === 'ai-studio' && window.AppStore) {
        const prevTabEl = document.querySelector('.tab-content:not(.hidden)');
        const prevTab = prevTabEl && prevTabEl.id.replace(/-tab$/, '');
        if (prevTab && prevTab !== 'ai-studio') {
            AppStore.set('aiStudioReturnTab', prevTab);
        }
    }

    // [customize 閘門移除——2026-08-24 DANNY 回報「前往板塊沒反應」]
    // 此前：目標 tab 若未在 Customize 啟用，靜默改跳第一個啟用 tab（通常
    // = 目前的 chat）→ 訊息裡的「前往 X 板塊」chip、#hash deep-link、
    // 「新對話」（chat 被停用時）全部表面無反應。
    // 修正：Customize 只控制「底部導覽列顯示哪些按鈕」，不是存取控制——
    // 任何 VALID_TABS 都可到達；導覽列無對應按鈕時僅不高亮（下方
    // activeBtn 已有 null 防護）。

    localStorage.setItem('activeTab', tabId);
    AppStore.set('activeTab', tabId); // source of truth

    // 更新瀏覽器歷史記錄（只有非 popstate 觸發時才 push）
    if (!fromPopState && window.location.hash !== '#' + tabId) {
        history.pushState({ tab: tabId }, '', '#' + tabId);
    }

    // Close any open stock chart overlays (they are fixed-position, not inside tab DOM)
    if (window.TWStockTab && typeof window.TWStockTab.closeTwChart === 'function')
        window.TWStockTab.closeTwChart();
    if (window.USStockTab && typeof window.USStockTab.closeChart === 'function')
        window.USStockTab.closeChart();
    // Crypto K-line chart (#chart-section) is also a fixed-position overlay → close it too
    if (typeof window.closeChart === 'function') window.closeChart();
    // Close price alert modal if open
    if (typeof window.closeAlertModal === 'function') window.closeAlertModal();
    // Remove any leftover symbol-picker overlays (commodity/forex/astock/jpstock/instock/krstock
    // append `<market>-picker-modal` to <body> with fixed inset-0 z-50; they only self-remove on
    // X/confirm, so switching tabs while one is open would leave it floating on top).
    document.querySelectorAll('[id$="-picker-modal"]').forEach((el) => el.remove());

    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach((el) => {
        el.classList.add('hidden');
        el.style.opacity = '';
        el.style.transform = '';
        el.style.transition = '';
    });

    // Dynamic Component Injection (Lazy Loading)
    // 先按需 dynamic import 該 tab 的模組（tab 模板 + 業務邏輯），
    // 完成後 Components.inject 才拿得到 window.Components[tabId] 模板。
    await _ensureTabModules(tabId);
    if (
        [
            'crypto',
            'twstock',
            'usstock',
            'settings',
            'friends',
            'forum',
            'admin',
            'commodity',
            'forex',
            'hkstock',
            'astock',
            'jpstock',
            'instock',
            'krstock',
            'trust',
            'wallet-monitor',
            'ai-studio',
            'discover',
            'studio',
        ].includes(tabId)
    ) {
        if (window.Components && typeof window.Components.inject === 'function') {
            await window.Components.inject(tabId);
        }
    }

    // [Sidebar Visibility]
    // 2026-08-21：sidebar 現在包含主要導覽（journal/crypto/twstock…），
    // 不再只屬於 chat——所有分頁都必須顯示，否則使用者無法切換。
    // 原本 tabsWithSidebar=['chat'] 是「sidebar=對話歷史」時代的邏輯。
    const globalSidebar = document.getElementById('chat-sidebar');
    const sidebarBackdrop = document.getElementById('sidebar-backdrop');
    if (globalSidebar) {
        globalSidebar.style.display = '';
        globalSidebar.classList.remove('hidden');
        // backdrop 只在手機 drawer 打開時顯示（toggleSidebar 控制），這裡不動
    }

    // Show target tab
    const target = document.getElementById(tabId + '-tab');
    if (target) {
        target.classList.remove('hidden');
    }

    // Update Nav Icons
    document.querySelectorAll('.nav-btn').forEach((btn) => {
        const icon = btn.querySelector('i');
        const label = btn.querySelector('span');

        if (icon) {
            icon.classList.remove('text-primary');
            icon.classList.add('text-textMuted');
        }
        btn.classList.remove('bg-surfaceHighlight', 'text-primary');
        btn.classList.add('text-textMuted');
    });

    // Highlight Active
    const activeBtn = document.querySelector(`.nav-btn[data-tab="${tabId}"]`);
    if (activeBtn) {
        const icon = activeBtn.querySelector('i');
        const label = activeBtn.querySelector('span');

        if (icon) {
            icon.classList.remove('text-textMuted');
            icon.classList.add('text-primary');
        }
        activeBtn.classList.remove('text-textMuted');
        activeBtn.classList.add('bg-surfaceHighlight', 'text-primary');
    }

    // Trigger tab-specific initialization
    if (tabId === 'crypto') {
        if (typeof connectTickerWebSocket === 'function') connectTickerWebSocket();
        if (typeof initCrypto === 'function') {
            await initCrypto();
        }
    }
    if (tabId === 'twstock') {
        if (window.TWStockTab && typeof window.TWStockTab.initTwStock === 'function') {
            window.TWStockTab.initTwStock();
        }
        if (typeof window.loadUserAlerts === 'function') window.loadUserAlerts();
    }
    if (tabId === 'usstock') {
        if (window.USStockTab && typeof window.USStockTab.init === 'function') {
            window.USStockTab.init();
        }
        if (typeof window.loadUserAlerts === 'function') window.loadUserAlerts();
    }
    if (tabId === 'commodity' && typeof CommodityTab !== 'undefined') CommodityTab.init();
    if (tabId === 'forex' && typeof ForexTab !== 'undefined') ForexTab.init();
    if (tabId === 'hkstock' && typeof HKStockTab !== 'undefined') HKStockTab.init();
    if (tabId === 'astock'  && typeof AStockTab  !== 'undefined') AStockTab.init();
    if (tabId === 'jpstock' && typeof JPStockTab !== 'undefined') JPStockTab.init();
    if (tabId === 'instock' && typeof INStockTab !== 'undefined') INStockTab.init();
    if (tabId === 'krstock' && typeof KRStockTab !== 'undefined') KRStockTab.init();
    if (tabId === 'wallet') {
        if (window.WalletApp) window.WalletApp.init();
        // Swap History（全面重組 Phase 2：從 Settings 搬入 Wallet tab）
        if (typeof window.SwapHistoryManager !== 'undefined' &&
            typeof window.SwapHistoryManager.init === 'function') {
            window.SwapHistoryManager.init();
        }
        // Swap Limit（使用者自訂單筆上限，與 Swap History 同區塊）
        if (typeof initSwapLimitSettings === 'function') {
            initSwapLimitSettings();
        }
    }
    if (tabId === 'wallet-monitor' && typeof WalletMonitorTab !== 'undefined') WalletMonitorTab.init();
    if (tabId === 'trust' && typeof TrustTab !== 'undefined') TrustTab.init();
    if (tabId === 'ai-studio' && typeof AIStudioTab !== 'undefined') AIStudioTab.init();
    if (tabId === 'discover' && typeof DiscoverTab !== 'undefined') DiscoverTab.init();
    if (tabId === 'studio' && typeof StudioTab !== 'undefined') StudioTab.init();
    // journal：骨架內建於 index.html（非 Components 模板型），init 負責拉資料渲染
    // Dashboard——先前只列進 inject 清單（inject 必然 template=false 失敗）而
    // 沒人呼叫 init，Dashboard 永遠卡「載入中...」（2026-08-22 盤點）。
    if (tabId === 'journal' && window.JournalTab) window.JournalTab.init();
    if (tabId === 'friends') {
        if (window.SocialHub) window.SocialHub.init();
    }
    if (tabId === 'forum') {
        if (window.ForumApp) window.ForumApp.init();
    }
    if (tabId === 'admin') {
        if (window.AdminPanel) AdminPanel.init();
    }
    if (tabId === 'settings') {
        // 「我的 AI」摘要卡 → AI Studio（Phase 1 入口）
        var myAiBtn = document.getElementById('btn-open-ai-studio');
        if (myAiBtn && !myAiBtn._aiStudioBound) {
            myAiBtn._aiStudioBound = true;
            myAiBtn.addEventListener('click', () => switchTab('ai-studio'));
        }
        // Settings 內容是動態注入，需在注入後重新同步已登入身份顯示（username / UID）
        if (window.AuthManager && typeof window.AuthManager._updateUI === 'function') {
            window.AuthManager._updateUI(window.AuthManager.isLoggedIn());
        }
        // ✅ 效能優化：並行執行所有 settings 初始化，而非依序等待
        const settingsInits = [];
        if (typeof loadSettingsWalletStatus === 'function')
            settingsInits.push(Promise.resolve(loadSettingsWalletStatus()));
        if (typeof loadPremiumStatus === 'function')
            settingsInits.push(Promise.resolve(loadPremiumStatus()));
        if (typeof updateLLMStatusUI === 'function')
            settingsInits.push(Promise.resolve(updateLLMStatusUI()));
        // Settings DOM 為動態注入：進入分頁時重抓綁定資料並渲染「已綁定的模型」清單
        // （auth:ready 時的那次 render 常發生在容器還不存在的時候）
        if (typeof window.loadSavedApiKeys === 'function')
            settingsInits.push(Promise.resolve(window.loadSavedApiKeys()));
                if (!AppStore.get('settingsHeavyInitAt')) AppStore.set('settingsHeavyInitAt', 0);
                const now = Date.now();
                if (now - AppStore.get('settingsHeavyInitAt') > 15000) {
                    AppStore.set('settingsHeavyInitAt', now);
            if (typeof window.initTestMode === 'function') {
                settingsInits.push(Promise.resolve(window.initTestMode()));
            }
        }
        if (typeof updatePriceDisplays === 'function') updatePriceDisplays();
        if (
            window.PremiumManager &&
            typeof window.PremiumManager.updatePriceDisplay === 'function'
        ) {
            window.PremiumManager.updatePriceDisplay();
        }
        if (typeof window.updateAvailableModels === 'function') window.updateAvailableModels();
        if (window.TelegramLinkApp && typeof window.TelegramLinkApp.init === 'function')
            settingsInits.push(Promise.resolve(window.TelegramLinkApp.init()));
        // 「我的 AI」摘要卡計數（Memory/Skill/Tool 管理器已搬入 AI Studio）
        settingsInits.push(Promise.resolve(loadMyAISummaryCounts()));
        // 並行發出所有 API 請求
        Promise.allSettled(settingsInits).catch((e) => console.warn('Settings init error:', e));
    }
    if (tabId === 'chat') {
        if (typeof initChat === 'function') initChat();
        // ✅ 效能優化：checkApiKeyStatus 加 TTL 快取，避免每次切換都打後端 API
        const now = Date.now();
        if (!AppStore.get('lastApiKeyCheck') || now - AppStore.get('lastApiKeyCheck') > 30000) {
            AppStore.set('lastApiKeyCheck', now);
            // 確保 APIKeyManager 已初始化
            if (typeof checkApiKeyStatus === 'function' && window.APIKeyManager) {
                checkApiKeyStatus();
            }
        }
    }

    if (typeof onTabSwitch === 'function') onTabSwitch(tabId);
}
window.executeTabSwitch = executeTabSwitch;

function restoreUiStateAfterResume() {
    const savedTab = getActiveTab();
    const validTabs = new Set([
        'chat',
        'crypto',
        'twstock',
        'usstock',
    'journal',
        'commodity',
        'forex',
        'hkstock',
        'astock',
        'jpstock',
        'instock',
        'krstock',
        'wallet',
        'friends',
        'forum',
        'settings',
        'admin',
    ]);

    if (!validTabs.has(savedTab)) {
        return;
    }

    const hasVisibleTab = Array.from(document.querySelectorAll('.tab-content')).some(
        (element) => !element.classList.contains('hidden')
    );

    if (!hasVisibleTab || AppStore.get('activeTab') !== savedTab) {
        switchTab(savedTab, true).catch((error) => {
            console.warn('Resume UI restore failed:', error);
        });
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        restoreUiStateAfterResume();
    }
});

window.addEventListener('pageshow', restoreUiStateAfterResume);

// ========================================
// Navigation Rendering & Feature Menu
// ========================================

/**
 * Render navigation buttons based on user preferences
 */
function renderNavButtons() {
    if (window.GlobalNav && typeof window.GlobalNav.renderNavButtons === 'function') {
        window.GlobalNav.renderNavButtons();
        return;
    }
}
window.renderNavButtons = renderNavButtons;

/**
 * Feature Menu Manager
 * Handles the navigation customization modal
 */
const FeatureMenu = {
    _tempPreferences: null,
    _modal: null,

    /**
     * Open the feature menu modal
     *
     * featureMenu 是獨立 lazy component；開啟時才載入，避免首屏增加體積。
     */
    async open() {
        if (!window.NavPreferences) {
            console.error('NavPreferences not loaded');
            return;
        }

        // Inject feature menu component if not already in DOM
        if (!document.getElementById('feature-menu-modal')) {
            if (!window.Components || !window.Components.featureMenu) {
                try {
                    await import('./components/feature-menu.js');
                } catch (e) {
                    console.error('Failed to load feature-menu.js', e);
                    return;
                }
            }
            if (window.Components && window.Components.featureMenu) {
                const container = document.createElement('div');
                container.innerHTML = window.Components.featureMenu;
                document.body.appendChild(container.firstElementChild);
            } else {
                console.error('Feature menu component not available');
                return;
            }
        }

        this._modal = document.getElementById('feature-menu-modal');
        const itemsContainer = document.getElementById('feature-menu-items');
        const warningBanner = document.getElementById('feature-menu-warning');

        // Store current preferences for temp state
        const currentEnabled = NavPreferences.loadPreferences().enabledItems;
        this._tempPreferences = new Set(currentEnabled);

        // Clear and render items
        itemsContainer.innerHTML = '';

        window.NAV_ITEMS.forEach((item) => {
            if (item.locked) return;
            if (item.hidden) return;

            const isEnabled = this._tempPreferences.has(item.id);
            const itemEl = document.createElement('div');
            itemEl.className = `feature-menu-item ${!isEnabled ? 'disabled' : ''}`;
            itemEl.dataset.itemId = item.id;

            // Use i18n key if available, otherwise fall back to label
            const labelText =
                item.i18nKey && window.I18n ? window.I18n.t(item.i18nKey) : item.label;

            itemEl.innerHTML = `
                <div class="feature-item-icon">
                    <i data-lucide="${item.icon}"></i>
                </div>
                <span class="feature-item-label">${labelText}</span>
                <div class="feature-toggle ${isEnabled ? 'enabled' : ''}"></div>
            `;

            itemEl.addEventListener('click', () => this.toggleItem(item.id, itemEl));
            itemsContainer.appendChild(itemEl);
        });

        // Initialize Lucide icons
        AppUtils.refreshIcons();

        // Show modal with animation
        this._modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            this._modal
                .querySelector('.feature-menu-content')
                .classList.add('modal-content-active');
        });
    },

    /**
     * Toggle a navigation item on/off
     */
    toggleItem(itemId, element) {
        // Locked items cannot be toggled
        const navItem = window.NAV_ITEMS.find((i) => i.id === itemId);
        if (navItem && navItem.locked) return;

        const isCurrentlyEnabled = this._tempPreferences.has(itemId);

        if (isCurrentlyEnabled) {
            if (this._countTowardLimit() <= NavPreferences.MIN_ENABLED_ITEMS) {
                const warningBanner = document.getElementById('feature-menu-warning');
                this._showWarning(warningBanner, 'min');
                element.classList.add('shake');
                setTimeout(() => element.classList.remove('shake'), 400);
                return;
            }
            this._tempPreferences.delete(itemId);
        } else {
            // 硬限制：最多 MAX_ENABLED_ITEMS 個，超過就擋下（比照下限不放行），
            // 不能只跳警告卻仍把第 6 個加進去 → 否則 save() 會原樣存入超量項目。
            if (this._countTowardLimit() >= NavPreferences.MAX_ENABLED_ITEMS) {
                const warningBanner = document.getElementById('feature-menu-warning');
                this._showWarning(warningBanner, 'max');
                element.classList.add('shake');
                setTimeout(() => element.classList.remove('shake'), 400);
                return;
            }
            this._tempPreferences.add(itemId);
        }

        // Update UI
        const toggle = element.querySelector('.feature-toggle');
        if (this._tempPreferences.has(itemId)) {
            toggle.classList.add('enabled');
            element.classList.remove('disabled');
        } else {
            toggle.classList.remove('enabled');
            element.classList.add('disabled');
        }

        const warningBanner = document.getElementById('feature-menu-warning');
        const count = this._countTowardLimit();
        if (count < NavPreferences.MIN_ENABLED_ITEMS) {
            this._showWarning(warningBanner, 'min');
        } else if (count > NavPreferences.MAX_ENABLED_ITEMS) {
            this._showWarning(warningBanner, 'max');
        } else {
            warningBanner.classList.add('hidden');
        }
    },

    /**
     * Count enabled items that count toward the MIN/MAX cap.
     * Mirrors NavPreferences.setItemEnabled: adminOnly items (e.g. admin) are
     * not rendered for normal users and must NOT count toward the limit, or the
     * customize modal blocks one item too early for users who have admin in prefs.
     */
    _countTowardLimit() {
        let n = 0;
        for (const id of this._tempPreferences) {
            const it = (window.NAV_ITEMS || []).find((i) => i.id === id);
            // locked（如 Settings）與 adminOnly 不計入上限——它們永遠顯示，
            // 不佔用使用者可調整的 MAX_ENABLED_ITEMS 額度。
            if (it && !it.adminOnly && !it.locked) n++;
        }
        return n;
    },

    _showWarning(banner, kind) {
        if (!banner) return;
        const p = banner.querySelector('p');
        const key = kind === 'max' ? 'featureMenu.maxWarning' : 'featureMenu.minWarning';
        const count = kind === 'max' ? NavPreferences.MAX_ENABLED_ITEMS : NavPreferences.MIN_ENABLED_ITEMS;
        if (window.I18n) {
            p.textContent = window.I18n.t(key, { max: count, min: count });
        }
        banner.classList.remove('hidden');
        clearTimeout(this._warningTimer);
        this._warningTimer = setTimeout(() => banner.classList.add('hidden'), 3500);
    },

    /**
     * Save changes and close modal
     */
    save() {
        if (this._tempPreferences.size < NavPreferences.MIN_ENABLED_ITEMS) {
            if (typeof showToast === 'function') {
                showToast(
                    `At least ${NavPreferences.MIN_ENABLED_ITEMS} items must be enabled`,
                    'warning'
                );
            }
            return;
        }

        // Save preferences
        const preferences = {
            version: NavPreferences.PREFERENCES_VERSION,
            enabledItems: Array.from(this._tempPreferences),
        };
        NavPreferences.savePreferences(preferences);

        // Re-render navigation
        renderNavButtons();

        // Close modal
        this.close();

        // Show success feedback
        this.showToast(window.I18n ? window.I18n.t('nav.preferencesSaved') : 'Navigation preferences saved');
    },

    /**
     * Reset to defaults
     */
    resetToDefaults() {
        if (typeof showConfirm === 'function') {
            showConfirm({
                title: window.I18n?.t('settings.navigation.reset') || 'Reset to Default',
                message: window.I18n ? window.I18n.t('nav.resetConfirm') : 'Reset all navigation items to default?',
                confirmText: window.I18n?.t('common.confirm') || 'Confirm',
                cancelText: window.I18n?.t('common.cancel') || 'Cancel',
            }).then((confirmed) => {
                if (confirmed) {
                    NavPreferences.resetToDefaults();
                    renderNavButtons();
                    this.close();
                    this.showToast(window.I18n ? window.I18n.t('nav.resetToDefaults') : 'Navigation reset to defaults');
                }
            });
        } else {
            NavPreferences.resetToDefaults();
            renderNavButtons();
            this.close();
            this.showToast(window.I18n ? window.I18n.t('nav.resetToDefaults') : 'Navigation reset to defaults');
        }
    },

    /**
     * Close the modal without saving
     */
    close() {
        if (this._modal) {
            const content = this._modal.querySelector('.feature-menu-content');
            if (content) content.classList.remove('modal-content-active');

            setTimeout(() => {
                if (this._modal) this._modal.classList.add('hidden');
                this._tempPreferences = null;
            }, 200);
        }
    },

    /**
     * Show a toast notification (delegates to global showToast)
     */
    showToast(message) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'success');
        }
    },
};

// Expose FeatureMenu globally
window.FeatureMenu = FeatureMenu;

// ========================================
// Application Initialization
// ========================================

// Initialize Greeting Time
const hour = new Date().getHours();
const greeting = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
const greetingTimeEl = document.getElementById('greeting-time');
if (greetingTimeEl) {
    greetingTimeEl.innerText = greeting;
}

document.addEventListener('DOMContentLoaded', async () => {
    // 非 SPA 頁守門（2026-08-24 messages.html#chat 事故）：boot 流程會動
    // body opacity、切 tab、注入 chat UI——在論壇頁跑等於直接摧毀版面。
    if (!document.getElementById('chat-tab')) {
        console.warn('[spa] SPA container (#chat-tab) missing — skip SPA boot (non-SPA page)');
        return;
    }
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('DOM fully loaded, starting controlled initialization...');

    // 頁面淡入效果
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.25s ease-in';
    requestAnimationFrame(() => {
        document.body.style.opacity = '1';
    });

    // 等待核心組件就緒的輔助函式
    const waitForGlobal = (key, timeout = 3000) => {
        return new Promise((resolve) => {
            if (window[key]) return resolve(window[key]);
            const start = Date.now();
            // ✅ 效能優化：polling 間隔從 100ms 降到 10ms，加快啟動速度
            const interval = setInterval(() => {
                if (window[key] || Date.now() - start > timeout) {
                    clearInterval(interval);
                    resolve(window[key]);
                }
            }, 10);
        });
    };

    // 確保核心腳本都已載入
    window.APP_CONFIG?.DEBUG_MODE && console.log('Waiting for core systems...');
    await Promise.all([
        waitForGlobal('Components').then(
            (v) => window.APP_CONFIG?.DEBUG_MODE && console.log('Components ready:', !!v)
        ),
        waitForGlobal('initializeAuth').then(
            (v) => window.APP_CONFIG?.DEBUG_MODE && console.log('Auth ready:', !!v)
        ),
        waitForGlobal('initializeUIStatus').then(
            (v) => window.APP_CONFIG?.DEBUG_MODE && console.log('UI ready:', !!v)
        ),
    ]);

    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Core systems ready status:', {
            Components: !!window.Components,
            Auth: !!window.initializeAuth,
            UI: !!window.initializeUIStatus,
        });

    // 0. 初始化 i18n（必須在 renderNavButtons 之前完成）
    if (window.I18n) {
        try {
            await window.I18n.init();
            window.APP_CONFIG?.DEBUG_MODE && console.log('i18n ready');
        } catch (e) {
            console.error('i18n Init Error:', e);
        }
    }

    // 1. 初始化認證系統（支援測試模式自動登入）
    if (typeof initializeAuth === 'function') {
        try {
            await initializeAuth();
        } catch (e) {
            console.error('Auth Init Error:', e);
        }
    }

    // 1.5 載入已保存的 API Key 狀態（必須在 Auth 完成後）
    if (typeof window.loadSavedApiKeys === 'function') {
        try {
            await window.loadSavedApiKeys();
        } catch (e) {
            console.error('Load API Keys Error:', e);
        }
    }

    // 2. Render navigation buttons based on user preferences
    renderNavButtons();

    // 2.5 初始化語系切換器
    if (window.LanguageSwitcher) {
        new LanguageSwitcher('.lang-switcher-container');
        // 登入 modal 內的獨立切換器：未登入的外國使用者也能先切語言
        if (document.querySelector('.login-lang-switcher')) {
            new LanguageSwitcher('.login-lang-switcher');
        }
        // 手機版頂欄：底欄 switcher 在手機被 CSS 隱藏，語言改從頂欄切
        if (document.querySelector('.header-lang-switcher')) {
            new LanguageSwitcher('.header-lang-switcher');
        }
    }

    // 2.6 初始化主題切換器（深淺）
    if (window.ThemeSwitcher) {
        new ThemeSwitcher('.theme-switcher-container');
        if (document.querySelector('.login-theme-switcher')) {
            new ThemeSwitcher('.login-theme-switcher');
        }
        // 手機版頂欄：同語言切換器，手機的主題改從頂欄切
        if (document.querySelector('.header-theme-switcher')) {
            new ThemeSwitcher('.header-theme-switcher');
        }
    }

    // 2.6 初始化通知組件（手機版 + 桌面版）
    if (window.NotificationBell && window.NotificationService) {
        const mobileBell = document.getElementById('notification-bell-mobile');
        const desktopBell = document.getElementById('notification-bell-desktop');
        if (mobileBell) {
            window.notificationBell = new NotificationBell(mobileBell);
        }
        if (desktopBell) {
            window.notificationBellDesktop = new NotificationBell(desktopBell);
        }
        window.APP_CONFIG?.DEBUG_MODE && console.log('NotificationBell initialized (global)');
    }

    // 監聽語言切換事件
    let _lastLangRendered = null;
    window.addEventListener('languageChanged', (e) => {
        // 1. 導覽列標籤
        renderNavButtons();

        // 2. 重新渲染「目前正在看的分頁」，讓 JS 以 innerHTML 動態產生、
        //    沒有 data-i18n 屬性的內容也套用新語言（靜態 data-i18n 由
        //    i18n.js 的 updatePageContent 處理，動態內容則需重跑分頁 init）。
        //    重跑 executeTabSwitch 等同「切走再切回」，分頁 init 本就需可重入。
        //    - chat 由 chat-sessions.js 的歡迎畫面監聽器另行處理，避免干擾進行中的對話。
        //    - 同一次切換會派發兩次事件（i18next + 手動），以語言去重避免雙重渲染。
        const lang = e?.detail?.language;
        if (lang && lang === _lastLangRendered) return;
        _lastLangRendered = lang;

        // 已自行監聽 languageChanged 的分頁不重跑，避免重複渲染；
        // 且這些分頁的 init 會無條件再註冊 languageChanged，重跑會造成監聽器洩漏。
        // chat 由 chat-sessions.js 的歡迎畫面監聽器處理。
        const SELF_HANDLED = new Set(['chat', 'twstock', 'usstock',
    'journal', 'hkstock']);
        const active = getActiveTab();
        const loggedIn = !window.AuthManager || window.AuthManager.isLoggedIn();
        if (active && !SELF_HANDLED.has(active) && loggedIn && typeof executeTabSwitch === 'function') {
            // fromPopState=true：不污染瀏覽歷史
            Promise.resolve(executeTabSwitch(active, true)).catch((err) =>
                console.warn('Re-render active tab on language change failed:', err)
            );
        }
    });

    // 3. 載入預設分頁（優先順序：sessionStorage returnToTab > URL hash > localStorage）
    const returnToTab = sessionStorage.getItem('returnToTab');
    const hashTab = window.location.hash.replace('#', '');
    const savedTab = getActiveTab();
    const normalizedSavedTab = VALID_TABS.includes(savedTab) ? savedTab : 'chat';

    // 優先使用 returnToTab（從論壇返回），其次 hash，最後 localStorage
    let initialTab;
    if (hashTab && !VALID_TABS.includes(hashTab)) {
        initialTab = 'chat';
        history.replaceState({ tab: 'chat' }, '', '#chat');
    } else if (returnToTab && VALID_TABS.includes(returnToTab)) {
        initialTab = returnToTab;
        sessionStorage.removeItem('returnToTab'); // 使用後清除
    } else if (VALID_TABS.includes(hashTab)) {
        initialTab = hashTab;
    } else {
        initialTab = normalizedSavedTab;
    }

    const loginModal = document.getElementById('login-modal');
    const shouldLockGuestLanding =
        AppStore.get('forceGuestLandingTab') === true ||
        (!!window.AuthManager &&
            !window.AuthManager.isLoggedIn() &&
            loginModal &&
            !loginModal.classList.contains('hidden'));
    if (shouldLockGuestLanding) {
        initialTab = 'chat';
    }

    window.APP_CONFIG?.DEBUG_MODE &&
        console.log(
            'Initial tab switching to:',
            initialTab,
            '(returnTo:',
            returnToTab,
            ', hash:',
            hashTab,
            ', saved:',
            savedTab,
            ')'
        );

    // 清除 hash 並設置正確的初始歷史狀態
    history.replaceState({ tab: initialTab }, '', '#' + initialTab);

    try {
        await switchTab(initialTab, true); // fromPopState=true 避免重複 pushState
    } catch (e) {
        console.error('Initial Tab Error:', e);
    }

    // 3. 更新 UI 狀態
    if (typeof initializeUIStatus === 'function') {
        try {
            initializeUIStatus();
        } catch (e) {
            console.error('UI Init Error:', e);
        }
    }

    // 4. 延遲啟動 Ticker WebSocket（僅在 market/commodity/forex tab 時立即啟動）
    setTimeout(() => {
        const currentTab = getActiveTab();
        const marketTabs = ['market', 'crypto', 'twstock', 'usstock',
    'journal', 'commodity', 'forex'];
        if (marketTabs.includes(currentTab)) {
            if (typeof connectTickerWebSocket === 'function') connectTickerWebSocket();
        }
    }, 1000);

    // 5. 預加載 Market 和 Pulse 數據（僅在 market 相關 tab 時執行）
    setTimeout(async () => {
        const currentTab = getActiveTab();
        const marketTabs = ['market', 'crypto', 'twstock', 'usstock',
    'journal', 'commodity', 'forex'];
        if (!marketTabs.includes(currentTab)) return;

        window.APP_CONFIG?.DEBUG_MODE && console.log('Preloading market data...');
        // 動態載入的模組只能走 window（bare 識別字在模組作用域恆 undefined，
        // 2026-08-22 修：這裡曾因 bare typeof 靜默跳過導致 Pulse 預載從未執行）
        if (typeof window.initMarket === 'function') {
            await window.initMarket();
        }
        if (typeof window.initPulse === 'function') {
            await window.initPulse();
        }
        window.APP_CONFIG?.DEBUG_MODE && console.log('Market data preloaded');
    }, 2000);
});

// ========================================
// WebSocket Status Debugging
// ========================================

/**
 * Check and display WebSocket connection status
 */
function checkWebSocketStatus() {
    window.APP_CONFIG?.DEBUG_MODE && console.log('=== WebSocket Status ===');
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Ticker WS Connected:', window.marketWsConnected || false);
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('K-line WS Connected:', window.wsConnected || false);
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Ticker WS Object:', window.marketWebSocket ? 'Exists' : 'Not Found');
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('K-line WS Object:', window.klineWebSocket ? 'Exists' : 'Not Found');
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Auto-refresh Enabled:', window.autoRefreshEnabled || false);
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Current Chart Symbol:', window.currentChartSymbol || 'None');
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Subscribed Ticker Symbols:', Array.from(window.subscribedTickerSymbols || []));
    window.APP_CONFIG?.DEBUG_MODE &&
        console.log('Pending Ticker Symbols:', Array.from(window.pendingTickerSymbols || []));
}
window.checkWebSocketStatus = checkWebSocketStatus;

export {
    switchTab,
    executeTabSwitch,
    navigateToForum,
    renderNavButtons,
    FeatureMenu,
    checkWebSocketStatus,
};
