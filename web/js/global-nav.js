/**
 * Global Navigation Module
 * Provides shared bottom navigation across all pages (main app and forum)
 *
 * This module dynamically injects the draggable bottom navigation
 * and controls its visibility based on page type.
 */

const GlobalNav = {
    // DOM IDs
    CONTAINER_ID: 'global-nav-container',
    NAV_ID: 'draggable-nav',

    // Pages that should NOT show the bottom navigation
    HIDDEN_PAGES: ['post', 'create', 'profile', 'messages', 'wallet', 'premium'],

    /**
     * Initialize the global navigation
     * Determines whether to show nav based on current page type
     */
    init() {
        const pageType = document.body.dataset.page;
        const shouldShow = pageType && !this.HIDDEN_PAGES.includes(pageType);

        this._cleanupLegacyNavPosition();
        if (shouldShow) {
            this.injectNav();
        }
    },

    /**
     * Inject the navigation HTML into the page
     */
    injectNav() {
        // Skip if already injected
        if (document.getElementById(this.CONTAINER_ID)) return;

        const navHTML = this.getNavTemplate();
        // 桌機 dock 頂部（2026-08-20）：注入在頁面自身導覽列之後、內容之前——
        // 桌機 md:static in-flow 於此位置；手機 fixed 貼底不受注入點影響。
        const pageNav = document.querySelector('body > nav, body > header');
        if (pageNav) {
            pageNav.insertAdjacentHTML('afterend', navHTML);
        } else {
            document.body.insertAdjacentHTML('afterbegin', navHTML);
        }

        // Initialize language switcher, theme switcher
        this.initLanguageSwitcher();
        this.initThemeSwitcher();
        this.restoreNavState();

        // Initialize Lucide icons
        AppUtils.refreshIcons();

        // Wait for I18n to be ready before rendering buttons
        // Check if I18n is fully initialized (not just function exists), otherwise wait for it
        if (window.I18n && window.I18n.isReady && window.I18n.isReady()) {
            // I18n is fully initialized, render immediately
            this.renderNavButtons();
        } else {
            // Wait for I18n to be initialized with timeout
            let attempts = 0;
            const maxAttempts = 50; // 5 seconds max (50 * 100ms)
            const checkI18n = setInterval(() => {
                attempts++;
                if (window.I18n && window.I18n.isReady && window.I18n.isReady()) {
                    clearInterval(checkI18n);
                    this.renderNavButtons();
                } else if (attempts >= maxAttempts) {
                    // Timeout: render with fallback labels
                    console.warn('[GlobalNav] I18n init timeout, using fallback labels');
                    clearInterval(checkI18n);
                    this.renderNavButtons();
                }
            }, 100);
        }
    },

    /**
     * Get the navigation HTML template
     * @returns {string} HTML string for navigation
     */
    getNavTemplate() {
        return `
            <div id="${this.CONTAINER_ID}" class="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 md:static md:bottom-auto md:left-auto md:translate-x-0 md:z-auto md:mx-auto md:my-3 md:shrink-0 md:w-fit">
                <nav id="${this.NAV_ID}"
                    class="bg-surface border border-borderLight rounded-2xl p-1.5 flex items-center gap-1 select-none transition-all duration-300 max-w-[calc(100vw-1.5rem)]">
                    <!-- Collapse/Expand Toggle (desktop only; mobile tab bar 不需要折疊) -->
                    <button id="nav-toggle" data-click="GlobalNav.toggleCollapse"
                        class="hidden md:flex w-10 h-10 shrink-0 items-center justify-center rounded-xl bg-surfaceHighlight hover:bg-surfaceHighlight text-textMuted hover:text-primary transition-all duration-200"
                        title="${window.I18n.t('nav.collapse')}">
                        <i data-lucide="chevrons-left" class="w-4 h-4 transition-transform duration-300"
                            id="nav-toggle-icon"></i>
                    </button>

                    <!-- Navigation Buttons (Scrollable) -->
                    <div id="nav-buttons"
                        class="flex items-center gap-1 overflow-x-auto flex-1 min-w-0 transition-all duration-300 px-1 pb-1"
                        style="scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.2) transparent;">
                        <style>
                            #nav-buttons::-webkit-scrollbar {
                                height: 3px;
                            }
                            #nav-buttons::-webkit-scrollbar-track {
                                background: transparent;
                            }
                            #nav-buttons::-webkit-scrollbar-thumb {
                                background-color: rgba(255, 255, 255, 0.2);
                                border-radius: 9999px;
                            }
                        </style>
                        <!-- Navigation buttons will be dynamically rendered here -->
                    </div>

                    <!-- Language Switcher Container -->
                    <div class="lang-switcher-container shrink-0"></div>

                    <!-- Theme Switcher Container -->
                    <div class="theme-switcher-container shrink-0"></div>
                    <!-- 拖曳把手已移除（Phase 1b）：論壇頁桌機 dock 於頁面導覽列下方
                         in-flow，不再浮動；手機貼底 tab bar 本就隱藏把手 -->
                </nav>
            </div>
        `;
    },

    /**
     * Render navigation buttons based on user preferences
     */
    renderNavButtons() {
        if (!window.NavPreferences) {
            console.warn('NavPreferences not loaded yet, deferring button rendering');
            // Retry after a short delay
            setTimeout(() => this.renderNavButtons(), 100);
            return;
        }

        const container = document.getElementById('nav-buttons');
        if (!container) return;

        const enabledItems = NavPreferences.getEnabledItems();
        const pageType = document.body.dataset.page;

        // Clear existing buttons
        container.innerHTML = '';

        // 貼底列顯示數與 NavPreferences MAX_ENABLED_ITEMS（5）對齊——
        // 使用者選了 5 顆就要看到 5 顆（DANNY 2026-08-22 回饋）。
        // 空間靠縮小按鈕（w-10）與隱藏 pill 內的語言/主題切換
        // （手機頂欄已有同款，不重複）容納。
        const MOBILE_NAV_VISIBLE =
            (window.NavPreferences && NavPreferences.MAX_ENABLED_ITEMS) || 5;
        enabledItems.slice(0, MOBILE_NAV_VISIBLE).forEach((item) => {
            // Hide admin-only tabs for non-admin users
            if (item.adminOnly) {
                const user = window.AuthManager && AuthManager.currentUser;
                if (!user || user.role !== 'admin') return;
            }

            const button = document.createElement('button');
            const isActive = pageType === item.id || (pageType === 'index' && item.id === 'forum');

            // Use i18n key if available, otherwise fall back to label
            let labelText = item.label; // Default fallback
            if (item.i18nKey && window.I18n && window.I18n.isReady && window.I18n.isReady()) {
                try {
                    const translated = window.I18n.t(item.i18nKey);
                    // Only use translation if it's different from the key (translation succeeded)
                    if (translated !== item.i18nKey) {
                        labelText = translated;
                    }
                } catch (e) {
                    console.warn('Translation error for key:', item.i18nKey, e);
                    // labelText already set to item.label above
                }
            }

            button.className = `nav-btn shrink-0 w-10 h-10 flex flex-col items-center justify-center rounded-xl hover:bg-surfaceHighlight transition-all duration-200 gap-0.5 nav-item-enter ${isActive ? 'text-primary bg-surfaceHighlight' : 'text-textMuted hover:text-primary'}`;
            button.title = labelText;
            button.dataset.tab = item.id;

            // Set click handler
            if (item.id === 'forum') {
                button.onclick = function () {
                    GlobalNav.navigateToForum();
                };
            } else {
                button.onclick = function () {
                    GlobalNav.navigateToTab(item.id);
                };
            }

            button.innerHTML = `
                <i data-lucide="${item.icon}" class="w-5 h-5 ${isActive ? 'text-primary' : 'text-textMuted'}"></i>
                <span class="text-[9px] font-medium opacity-80">${labelText}</span>
            `;

            container.appendChild(button);
        });

        // Re-initialize Lucide icons
        AppUtils.refreshIcons();

        this._updateScrollHints();
    },

    _updateScrollHints() {
        const scroller = document.getElementById('nav-buttons');
        const wrapper = document.getElementById('nav-buttons-wrapper');
        if (!scroller || !wrapper) return;

        const update = () => {
            const { scrollLeft, scrollWidth, clientWidth } = scroller;
            const canLeft = scrollLeft > 4;
            const canRight = scrollLeft + clientWidth < scrollWidth - 4;
            wrapper.classList.toggle('can-scroll-left', canLeft);
            wrapper.classList.toggle('can-scroll-right', canRight);
        };

        update();
        if (this._navScrollHandler) {
            scroller.removeEventListener('scroll', this._navScrollHandler);
        }
        this._navScrollHandler = update;
        scroller.addEventListener('scroll', update, { passive: true });
        window.removeEventListener('resize', this._navResizeHandler || (() => {}));
        this._navResizeHandler = update;
        window.addEventListener('resize', update, { passive: true });
    },

    /**
     * Navigate to a main app tab
     * @param {string} tabId - The tab ID to navigate to
     */
    navigateToTab(tabId) {
        // Check if we're in the main SPA and switchTab function exists
        if (typeof switchTab === 'function') {
            // We're in the main app, use SPA navigation
            switchTab(tabId);
        } else {
            // Save current page info for potential return
            const currentPage = document.body.dataset.page;
            if (currentPage) {
                sessionStorage.setItem('lastForumPage', currentPage);
            }
            // Fallback: navigate to main app with tab
            window.location.href = `/static/index.html#${tabId}`;
        }
    },

    /**
     * Navigate to forum
     */
    navigateToForum() {
        // Check if we're in the main SPA
        if (typeof switchTab === 'function') {
            // We're in the main app, use SPA navigation
            switchTab('forum');
        } else {
            // Fallback: navigate to main app with forum hash
            window.location.href = '/static/index.html#forum';
        }
    },

    /* ============ Sidebar 導覽（2026-08-20，docs/plans/2026-08-20-sidebar-nav-design.md） ============
       桌機主要導覽併入既有左側 sidebar（ChatGPT/Discord 模式），浮動 pill 在 SPA
       桌機以 md:hidden 退場。手機貼底 tab bar、論壇頁注入 pill 皆不變。
       偏好（MIN 3 / MAX 5 可見分頁）沿用 NavPreferences。
       2026-08-23：導覽區與對話歷史改為雙 tab 切換（setSidebarTab），
       不再上下堆疊——各佔全高（DANNY 回饋：空間不足擠在一起太醜）。 */

    // 側欄雙分頁切換：history=對話歷史 / menu=功能選單。
    // HTML 初始為 history；此函式同步兩區顯示與 tab 視覺態（aria 同步）。
    // 選擇記入 localStorage——重造訪回到上次用的分頁（ChatGPT/Claude 同款）。
    setSidebarTab(name) {
        const navSection = document.getElementById('sidebar-nav-section');
        const sessionList = document.getElementById('chat-session-list');
        const tabHistory = document.getElementById('sidebar-tab-history');
        const tabMenu = document.getElementById('sidebar-tab-menu');
        if (!navSection || !sessionList || !tabHistory || !tabMenu) return;
        const isMenu = name === 'menu';
        navSection.classList.toggle('hidden', !isMenu);
        sessionList.classList.toggle('hidden', isMenu);
        tabHistory.setAttribute('aria-selected', String(!isMenu));
        tabMenu.setAttribute('aria-selected', String(isMenu));
        const onCls = ['bg-background', 'text-secondary', 'shadow-sm'];
        const offCls = ['bg-transparent', 'text-textMuted'];
        tabHistory.classList.remove(...(isMenu ? onCls : offCls));
        tabHistory.classList.add(...(isMenu ? offCls : onCls));
        tabMenu.classList.remove(...(isMenu ? offCls : onCls));
        tabMenu.classList.add(...(isMenu ? onCls : offCls));
        try {
            localStorage.setItem('sidebarActiveTab', isMenu ? 'menu' : 'history');
        } catch (_e) {
            /* localStorage 不可用（隱私模式等）——不影響切換，只不記憶 */
        }
        if (isMenu) {
            // 進 menu 前刷新（語言 / 登入態在背景可能已變）
            this.renderSidebarNav();
        } else {
            // 切離 menu：收起「更多分頁」popover，避免殘留
            const pop = document.getElementById('sidebar-nav-popover');
            if (pop) pop.classList.add('hidden');
        }
    },

    initSidebarNav() {
        if (this._sidebarNavInit) return;
        this._sidebarNavInit = true;
        if (!document.getElementById('sidebar-nav-items')) return; // 非 SPA 頁（論壇）無此區塊

        let saved = 'history';
        try {
            saved = localStorage.getItem('sidebarActiveTab') === 'menu' ? 'menu' : 'history';
        } catch (_e) {
            /* 同上——不記憶即預設 history */
        }
        this.setSidebarTab(saved);
        this.renderSidebarNav();

        // switchTab 包裝：切頁後更新 active 標記（replaceState 不觸發 hashchange，
        // 沒有現成 tab 變更事件可訂）。switchTab 內部有 150ms 淡出動畫才真正換
        // 內容——立即刷一次、動畫後再刷一次，確保標記落在最終分頁。
        const orig = window.switchTab;
        if (typeof orig === 'function' && !orig._sidebarNavWrapped) {
            const wrapped = function (...args) {
                const result = orig.apply(this, args);
                if (window.GlobalNav) {
                    window.GlobalNav.refreshSidebarActive();
                    setTimeout(
                        () => window.GlobalNav && window.GlobalNav.refreshSidebarActive(),
                        300
                    );
                }
                return result;
            };
            wrapped._sidebarNavWrapped = true;
            window.switchTab = wrapped;
        }

        // 語言切換時重渲染（label 翻譯）
        window.addEventListener('languageChanged', () => this.renderSidebarNav());
        // 登入/登出後重渲染（訪客鎖定 → 解鎖）
        window.addEventListener('auth-success', () => this.renderSidebarNav());
        window.addEventListener('auth:initialized', () => this.renderSidebarNav());
    },

    // 訪客判定（init 早期 AuthManager 可能未就緒——未就緒時從寬判定為訪客，
    // auth:initialized 事件後會重渲染修正）
    _isGuest() {
        try {
            const A = window.AuthManager;
            return !(A && typeof A.isLoggedIn === 'function' && A.isLoggedIn());
        } catch (_e) {
            return true;
        }
    },

    // 訪客可直接使用的分頁（僅 chat——spa.js 守門同款邊界）
    _isGuestAllowed(item) {
        return item.id === 'chat';
    },

    _openLoginModal() {
        const modal = document.getElementById('login-modal');
        if (modal) modal.classList.remove('hidden');
    },

    refreshSidebarActive() {
        const active = (document.querySelector('.tab-content:not(.hidden)')?.id || '').replace(/-tab$/, '');
        document.querySelectorAll('#sidebar-nav-items [data-tab]').forEach((btn) => {
            const on = btn.dataset.tab === active;
            btn.classList.toggle('text-primary', on);
            btn.classList.toggle('bg-primary/10', on);
            btn.classList.toggle('font-bold', on);
            btn.classList.toggle('text-textMuted', !on);
            btn.querySelector('i')?.classList.toggle('text-primary', on);
        });
    },

    renderSidebarNav() {
        const container = document.getElementById('sidebar-nav-items');
        if (!container) return;
        const items = window.NavPreferences
            ? NavPreferences.getEnabledItems()
            : (window.NAV_ITEMS || []).filter((i) => i.defaultEnabled);
        const esc = window.escapeHtml || ((s) => String(s));
        const isGuest = this._isGuest();
        const lockedHint =
            window.I18n && window.I18n.isReady && window.I18n.isReady()
                ? window.I18n.t('sidebar.lockedHint')
                : 'Login to unlock';
        let lockedCount = 0;

        // 側欄導覽最多顯示 MAX_ENABLED_ITEMS 項（設計文件 MIN 3 / MAX 5，
        // docs/plans/2026-08-20-sidebar-nav-design.md）。超出的啟用項從
        // 「更多分頁」popover 開關——沒有這個上限，導覽區會吃掉歷史對話
        // 的高度（DANNY 2026-08-21 回饋：歷史視窗太小難閱覽）。
        const SIDEBAR_NAV_VISIBLE =
            (window.NavPreferences && NavPreferences.MAX_ENABLED_ITEMS) || 5;

        container.innerHTML = '';
        items.slice(0, SIDEBAR_NAV_VISIBLE).forEach((item) => {
            if (item.adminOnly) {
                const user = window.AuthManager && AuthManager.currentUser;
                if (!user || user.role !== 'admin') return;
            }
            const label =
                item.i18nKey && window.I18n && window.I18n.isReady && window.I18n.isReady()
                    ? window.I18n.t(item.i18nKey)
                    : item.label;
            const locked = isGuest && !this._isGuestAllowed(item);
            if (locked) lockedCount += 1;
            const btn = document.createElement('button');
            btn.dataset.tab = item.id;
            btn.className = locked
                ? 'w-full flex items-center gap-3 p-2.5 rounded-xl text-sm font-medium text-textMuted/45 ' +
                  'hover:text-textMuted hover:bg-surfaceHighlight/60 transition text-left'
                : 'w-full flex items-center gap-3 p-2.5 rounded-xl text-sm font-medium text-textMuted ' +
                  'hover:text-secondary hover:bg-surfaceHighlight transition text-left';
            btn.title = locked ? lockedHint : '';
            btn.innerHTML =
                `<i data-lucide="${item.icon}" class="w-4 h-4 shrink-0"></i>` +
                `<span class="truncate flex-1">${esc(label)}</span>` +
                (locked ? '<i data-lucide="lock" class="w-3.5 h-3.5 shrink-0 opacity-70"></i>' : '');
            btn.onclick = () => {
                if (locked) {
                    // 訪客點鎖定項：直接開登入窗（比 switchTab 守門的路徑更直觀）
                    this._openLoginModal();
                    return;
                }
                if (item.id === 'forum') this.navigateToForum();
                else this.navigateToTab(item.id);
                this.refreshSidebarActive();
                // 手機抽屜：選完功能即收合（貼底 bar 是主要導覽，抽屜只是路過；
                // 桌機 sidebar 常駐，innerWidth 守門擋掉 md+）
                if (window.innerWidth < 768 && typeof toggleSidebar === 'function') {
                    toggleSidebar();
                }
            };
            container.appendChild(btn);
        });

        // 訪客且有鎖定項時：導覽區塊尾端放登入 CTA（與灰色鎖定項同群，
        // 「哪些要登入、怎麼登入」一眼看完——DANNY 2026-08-20 建議）
        if (isGuest && lockedCount > 0) {
            const cta = document.createElement('button');
            cta.className =
                'mt-1 w-full flex items-center justify-center gap-2 p-2.5 rounded-xl text-xs font-bold ' +
                'bg-primary/10 hover:bg-primary/20 border border-primary/25 text-primary transition';
            cta.innerHTML =
                '<i data-lucide="wallet" class="w-3.5 h-3.5 shrink-0"></i>' +
                `<span>${esc(
                    window.I18n && window.I18n.isReady && window.I18n.isReady()
                        ? window.I18n.t('sidebar.loginToUnlock')
                        : 'Connect wallet to unlock'
                )}</span>`;
            cta.onclick = () => this._openLoginModal();
            container.appendChild(cta);
        }

        if (window.AppUtils) AppUtils.refreshIcons();
        this.refreshSidebarActive();
    },

    toggleSidebarNavMore() {
        const pop = document.getElementById('sidebar-nav-popover');
        if (!pop) return;
        if (pop.classList.contains('hidden')) {
            this.renderSidebarNavPopover();
            // 視窗夾限：popover 絕對定位於導覽區下方，在矮視窗可能超過
            // 視窗底——以剩餘高度動態設 max-height（滾動留在 popover 內）。
            requestAnimationFrame(() => {
                const rect = pop.getBoundingClientRect();
                if (rect.bottom > window.innerHeight - 12) {
                    const available = Math.max(
                        160,
                        window.innerHeight - rect.top - 16
                    );
                    pop.style.maxHeight = available + 'px';
                } else {
                    pop.style.maxHeight = '';
                }
            });
            pop.classList.remove('hidden');
            // 點擊外部關閉（一次性）
            // Bug 1 修正：__suppressClickOutside 期間忽略（面板剛打開時的
            // pointerup click 不是「點外部」，是同一觸控手勢）
            setTimeout(() => {
                const closer = (e) => {
                    if (window.__suppressClickOutside && Date.now() < window.__suppressClickOutside) return;
                    if (!pop.contains(e.target) && e.target.id !== 'sidebar-nav-more') {
                        pop.classList.add('hidden');
                        document.removeEventListener('pointerdown', closer);
                    }
                };
                document.addEventListener('pointerdown', closer);
            }, 50);
        } else {
            pop.classList.add('hidden');
        }
    },

    renderSidebarNavPopover() {
        const list = document.getElementById('sidebar-nav-popover-list');
        if (!list || !window.NavPreferences) return;
        const enabledIds = NavPreferences.getEnabledItems().map((i) => i.id);
        const esc = window.escapeHtml || ((s) => String(s));
        const t = (item) =>
            item.i18nKey && window.I18n && window.I18n.isReady && window.I18n.isReady()
                ? window.I18n.t(item.i18nKey)
                : item.label;

        list.innerHTML = '';
        (window.NAV_ITEMS || []).forEach((item) => {
            if (item.hidden) return;
            if (item.adminOnly) {
                const user = window.AuthManager && AuthManager.currentUser;
                if (!user || user.role !== 'admin') return;
            }
            const isOn = enabledIds.includes(item.id);
            const locked = this._isGuest() && !this._isGuestAllowed(item);
            const row = document.createElement('button');
            row.className =
                'w-full flex items-center gap-2.5 p-2 rounded-xl text-sm text-left transition ' +
                (locked
                    ? 'text-textMuted/45'
                    : isOn
                      ? 'text-primary bg-primary/10'
                      : 'text-textMuted hover:bg-surfaceHighlight');
            row.innerHTML =
                `<i data-lucide="${item.icon}" class="w-4 h-4 shrink-0"></i>` +
                `<span class="truncate flex-1">${esc(t(item))}</span>` +
                (locked
                    ? '<i data-lucide="lock" class="w-4 h-4 shrink-0 opacity-70"></i>'
                    : `<i data-lucide="${isOn ? 'check-circle' : 'circle'}" class="w-4 h-4 shrink-0"></i>`);
            if (locked) {
                row.onclick = () => this._openLoginModal();
                list.appendChild(row);
                return;
            }
            row.onclick = () => {
                const ok = NavPreferences.setItemEnabled(item.id, !isOn);
                if (!ok && typeof window.showToast === 'function') {
                    showToast(
                        window.I18n && window.I18n.isReady && window.I18n.isReady()
                            ? window.I18n.t(isOn ? 'sidebar.navMinRequired' : 'sidebar.navMaxReached')
                            : 'Tab limit reached',
                        'warning'
                    );
                }
                this.renderSidebarNavPopover();
                this.renderSidebarNav();
            };
            list.appendChild(row);
        });
        if (window.AppUtils) AppUtils.refreshIcons();
    },

    /**
     * Toggle navigation collapse/expand state
     */
    toggleCollapse() {
        const navButtons = document.getElementById('nav-buttons');
        const toggleIcon = document.getElementById('nav-toggle-icon');
        const nav = document.getElementById(this.NAV_ID);

        if (!navButtons || !toggleIcon || !nav) return;

        const currentState = localStorage.getItem('navCollapsed') === 'true';
        const newState = !currentState;

        if (newState) {
            // Collapse
            navButtons.style.width = '0';
            navButtons.style.opacity = '0';
            navButtons.style.pointerEvents = 'none';
            toggleIcon.style.transform = 'rotate(180deg)';
            nav.style.borderRadius = '1rem';
        } else {
            // Expand
            navButtons.style.width = '';
            navButtons.style.opacity = '1';
            navButtons.style.pointerEvents = 'auto';
            toggleIcon.style.transform = 'rotate(0deg)';
            nav.style.borderRadius = '1rem';
        }

        // Save state
        localStorage.setItem('navCollapsed', newState);
    },

    /**
     * Restore saved navigation state（折疊狀態）
     */
    restoreNavState() {
        // Restore collapse state
        const savedCollapsed = localStorage.getItem('navCollapsed');
        if (savedCollapsed === 'true') {
            // Need to wait a tick for DOM to be ready
            setTimeout(() => this.toggleCollapse(), 0);
        }
    },

    /* 拖曳功能已移除（2026-08-20 Phase 1b，設計 docs/plans/2026-08-20-sidebar-nav-design.md）：
       桌機主要導覽併入 sidebar / 論壇頁 dock in-flow 後，浮動可拖 pill 不存在，
       拖曳（#510 短暫恢復過）與把手一併退場。此處僅一次性清理 #510 寫入的
       navPosition，避免殘留位置資料。 */
    _cleanupLegacyNavPosition() {
        try {
            localStorage.removeItem('navPosition');
        } catch (_e) { /* ignore */ }
    },

    /**
     * Initialize language switcher component
     * 2026-08-20 sidebar 導覽：pill 之外 sidebar footer 也有容器——
     * 全部容器各自初始化（querySelector 只挑第一個會讓另一個空著）。
     */
    initLanguageSwitcher() {
        document.querySelectorAll('.lang-switcher-container').forEach((container) => {
            if (container.childElementCount > 0) return; // 已初始化
            if (window.LanguageSwitcher && typeof window.LanguageSwitcher.init === 'function') {
                window.LanguageSwitcher.init(container);
            } else if (window.Components && window.Components.languageSwitcher) {
                // Fallback to component-based initialization
                container.innerHTML = window.Components.languageSwitcher;
                if (window.LanguageSwitcher && typeof window.LanguageSwitcher.init === 'function') {
                    window.LanguageSwitcher.init(container);
                }
            }
        });
    },

    /**
     * Initialize theme switcher component（深淺主題切換；多容器同 language switcher）
     */
    initThemeSwitcher() {
        document.querySelectorAll('.theme-switcher-container').forEach((container) => {
            if (container.childElementCount > 0) return;
            if (window.ThemeSwitcher && typeof window.ThemeSwitcher.init === 'function') {
                window.ThemeSwitcher.init(container);
            }
        });
    },

    /**
     * Re-render buttons (called when preferences change)
     */
    refreshButtons() {
        this.renderNavButtons();
    },
};

// Listen for language changes and re-render buttons
window.addEventListener('languageChanged', () => {
    if (document.getElementById('nav-buttons')) {
        GlobalNav.renderNavButtons();
    }
});

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => GlobalNav.init());
} else {
    GlobalNav.init();
}

// Export for use in other modules
window.GlobalNav = GlobalNav;
export { GlobalNav };
