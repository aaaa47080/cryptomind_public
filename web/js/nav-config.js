/**
 * Navigation Configuration Module
 * Defines all available navigation items and default states
 */

const NAV_ITEMS = [
    {
        id: 'chat',
        icon: 'message-circle',
        label: 'Chat',
        i18nKey: 'nav.chat',
        defaultEnabled: true,
        // 2026-08-24 DANNY 確認鎖定：chat 是核心 UX（訪客模式也只有 chat），
        // 停用後「新對話」等入口會跳不到聊天面板。locked 項每次載入自動
        // 修復回 enabledItems（見 loadPreferences），先前停用的使用者自動恢復。
        locked: true,
    },
    { id: 'crypto', icon: 'zap', label: 'Crypto', i18nKey: 'nav.crypto', defaultEnabled: true },
    {
        id: 'twstock',
        icon: 'bar-chart',
        label: 'TW Stock',
        i18nKey: 'nav.twstock',
        defaultEnabled: true,
    },
    {
        id: 'usstock',
        icon: 'trending-up',
        label: 'US Stock',
        i18nKey: 'nav.usstock',
        defaultEnabled: true,
    },
    {
        id: 'journal',
        icon: 'book-open',
        label: 'Ledger',
        i18nKey: 'nav.journal',
        defaultEnabled: true,
    },
    {
        id: 'wallet',
        icon: 'credit-card',
        label: 'Wallet',
        i18nKey: 'nav.wallet',
        defaultEnabled: false,
    },
    { id: 'commodity', icon: 'bar-chart-2',      label: 'Commodity', i18nKey: 'nav.commodity', defaultEnabled: false },
    {
        id: 'wallet-monitor',
        icon: 'radar',
        label: 'Wallet Monitor',
        i18nKey: 'nav.walletMonitor',
        defaultEnabled: false,
    },
    { id: 'forex',     icon: 'arrow-left-right', label: 'Forex',     i18nKey: 'nav.forex',     defaultEnabled: false },
    {
        id: 'trust',
        icon: 'shield-check',
        label: 'Trust',
        i18nKey: 'nav.trust',
        defaultEnabled: false,
    },
    { id: 'hkstock',   icon: 'landmark',         label: 'HK Stock',   i18nKey: 'nav.hkstock',   defaultEnabled: false },
    { id: 'astock',    icon: 'building-2',       label: 'A Share',    i18nKey: 'nav.astock',    defaultEnabled: false },
    { id: 'jpstock',   icon: 'sun',              label: 'JP Stock',   i18nKey: 'nav.jpstock',   defaultEnabled: false },
    { id: 'instock',   icon: 'flame',            label: 'India Stock', i18nKey: 'nav.instock',   defaultEnabled: false, hidden: true },  // 2026-08: 印度股暫停開放（資料源不穩 + 使用率低），隱藏保留可復原
    { id: 'krstock',   icon: 'flag',             label: 'Korea Stock', i18nKey: 'nav.krstock',   defaultEnabled: false },
    {
        id: 'friends',
        icon: 'users',
        label: 'Friends',
        i18nKey: 'nav.friends',
        defaultEnabled: false,
        hidden: true,  // Phase 2 社群功能尚未開放，完全不顯示（含 Customize 選單）
    },
    {
        id: 'forum',
        icon: 'messages-square',
        label: 'Forum',
        i18nKey: 'nav.forum',
        defaultEnabled: false,
        hidden: true,  // Phase 2 社群功能尚未開放，完全不顯示（含 Customize 選單）
    },
    {
        id: 'discover',
        icon: 'compass',
        label: 'Discover',
        i18nKey: 'nav.discover',
        defaultEnabled: true,  // 2026-08-15 出資者旅程 P0-1 轉正（design Approved）；仍可在 Customize 停用
    },
    {
        id: 'studio',
        icon: 'pencil-ruler',
        label: 'Studio',
        i18nKey: 'nav.studio',
        defaultEnabled: true,  // 提案工作台（募資者模式，design 2026-08-16）；PROPOSAL_STUDIO_ENABLED 控制 API
    },
    {
        id: 'ai-studio',
        icon: 'bot',
        label: 'AI Studio',
        i18nKey: 'nav.aiStudio',
        defaultEnabled: false,
        hidden: true,  // 不進底部導覽/自訂清單；入口 = Settings「我的 AI」摘要卡
    },
    {
        id: 'admin',
        icon: 'shield',
        label: 'Admin',
        i18nKey: 'nav.admin',
        defaultEnabled: true,
        locked: true,
        adminOnly: true,
    },
    {
        id: 'settings',
        icon: 'settings-2',
        label: 'Settings',
        i18nKey: 'nav.settings',
        defaultEnabled: true,
        locked: true,
    },
];

/**
 * Navigation Preferences Manager
 * Handles user's navigation customization preferences
 */
const NavPreferences = {
    STORAGE_KEY: 'userNavPreferences',
    PREFERENCES_VERSION: 21,  // v21: 記帳（journal）正式加入 NAV_ITEMS——先前條目遺失導致功能選單看不到（DANNY 2026-08-22 回報）；bump 重置為含 journal 的預設
    MIN_ENABLED_ITEMS: 3,
    MAX_ENABLED_ITEMS: 5,
    _cache: null,

    /**
     * Get all enabled navigation items
     * @returns {Array} Array of enabled NAV_ITEMS
     */
    getEnabledItems() {
        const preferences = this.loadPreferences();
        return NAV_ITEMS.filter(
            (item) => preferences.enabledItems.includes(item.id) && !item.hidden
        );
    },

    /**
     * Check if a specific item is enabled
     * @param {string} itemId - The item ID to check
     * @returns {boolean}
     */
    isItemEnabled(itemId) {
        const item = NAV_ITEMS.find((i) => i.id === itemId);
        if (item?.hidden) return false;
        const preferences = this.loadPreferences();
        return preferences.enabledItems.includes(itemId);
    },

    /**
     * Enable or disable a navigation item
     * @param {string} itemId - The item ID to update
     * @param {boolean} enabled - Whether to enable or disable
     * @returns {boolean} Success status
     */
    setItemEnabled(itemId, enabled) {
        const preferences = this.loadPreferences();
        const item = NAV_ITEMS.find((i) => i.id === itemId);

        if (!item) {
            console.warn(`Navigation item '${itemId}' does not exist`);
            return false;
        }
        if (item.hidden) {
            console.warn(`Navigation item '${itemId}' is hidden (not launched), cannot toggle`);
            return false;
        }

        if (enabled) {
            if (!preferences.enabledItems.includes(itemId)) {
                // 硬限制：使用者可見項目最多 MAX_ENABLED_ITEMS 個。
                // adminOnly（admin）與 locked（Settings）項目永遠顯示，不計入上限。
                const visibleCount = preferences.enabledItems.filter((id) => {
                    const it = NAV_ITEMS.find((i) => i.id === id);
                    return it && !it.adminOnly && !it.locked;
                }).length;
                if (visibleCount >= this.MAX_ENABLED_ITEMS) {
                    console.warn(
                        `Cannot enable '${itemId}': maximum ${this.MAX_ENABLED_ITEMS} items allowed`
                    );
                    return false;
                }
                preferences.enabledItems.push(itemId);
            }
        } else {
            if (!this.canDisableItem(itemId)) {
                console.warn(
                    `Cannot disable '${itemId}': minimum ${this.MIN_ENABLED_ITEMS} items must be enabled`
                );
                return false;
            }
            preferences.enabledItems = preferences.enabledItems.filter((id) => id !== itemId);
        }

        this.savePreferences(preferences);
        return true;
    },

    /**
     * Check if an item can be disabled (ensures minimum items)
     * @param {string} itemId - The item to check
     * @returns {boolean}
     */
    canDisableItem(itemId) {
        // Locked items can never be disabled
        const item = NAV_ITEMS.find((i) => i.id === itemId);
        if (item && item.locked) return false;

        const preferences = this.loadPreferences();
        const currentlyEnabled = preferences.enabledItems.filter((id) => id !== itemId);
        return currentlyEnabled.length >= this.MIN_ENABLED_ITEMS;
    },

    /**
     * Reset all items to default enabled state
     */
    resetToDefaults() {
        const defaultPreferences = {
            version: this.PREFERENCES_VERSION,
            enabledItems: NAV_ITEMS.filter((item) => item.defaultEnabled).map((item) => item.id),
        };
        this.savePreferences(defaultPreferences);
    },

    /**
     * Validate preferences object
     * @param {Object} preferences - Preferences to validate
     * @returns {Object} { valid: boolean, errors: Array }
     */
    validate(preferences) {
        const errors = [];

        if (!preferences.version || typeof preferences.version !== 'number') {
            errors.push('Invalid or missing version');
        }

        if (!Array.isArray(preferences.enabledItems)) {
            errors.push('enabledItems must be an array');
        } else {
            if (preferences.enabledItems.length < this.MIN_ENABLED_ITEMS) {
                errors.push(`At least ${this.MIN_ENABLED_ITEMS} items must be enabled`);
            }

            const validIds = NAV_ITEMS.map((item) => item.id);
            const invalidIds = preferences.enabledItems.filter((id) => !validIds.includes(id));
            if (invalidIds.length > 0) {
                errors.push(`Invalid item IDs: ${invalidIds.join(', ')}`);
            }
        }

        return {
            valid: errors.length === 0,
            errors,
        };
    },

    /**
     * Load preferences from localStorage
     * @returns {Object} Preferences object
     */
    loadPreferences() {
        if (this._cache) return this._cache;
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (stored) {
                const preferences = JSON.parse(stored);

                // Validate loaded preferences
                const validation = this.validate(preferences);
                if (!validation.valid) {
                    console.warn(
                        'Invalid preferences loaded, resetting to defaults:',
                        validation.errors
                    );
                    return this._getDefaultPreferences();
                }

                let changed = false;

                // Version migration
                if (!preferences.version || preferences.version < this.PREFERENCES_VERSION) {
                    if (preferences.version < 14) {
                        // v14: 舊版預設「全開」(13+ 項) 為設計失誤，一次性重置為新預設(≤5)，
                        // 移除殘留的次要市場項目。使用者之後可在設定自行調整。
                        preferences.enabledItems = NAV_ITEMS
                            .filter((i) => i.defaultEnabled)
                            .map((i) => i.id);
                    } else {
                        NAV_ITEMS.filter((i) => i.defaultEnabled).forEach((item) => {
                            if (!preferences.enabledItems.includes(item.id)) {
                                preferences.enabledItems.push(item.id);
                            }
                        });
                    }
                    preferences.version = this.PREFERENCES_VERSION;
                    changed = true;
                }

                // 已暫停或尚未推出的項目不可殘留在舊版使用者偏好中。
                const visibleItemIds = new Set(
                    NAV_ITEMS.filter((item) => !item.hidden).map((item) => item.id)
                );
                const visibleEnabledItems = preferences.enabledItems.filter((id) =>
                    visibleItemIds.has(id)
                );
                if (visibleEnabledItems.length !== preferences.enabledItems.length) {
                    preferences.enabledItems = visibleEnabledItems;
                    changed = true;
                }

                // Ensure locked items are always included
                NAV_ITEMS.filter((i) => i.locked).forEach((item) => {
                    if (!preferences.enabledItems.includes(item.id)) {
                        preferences.enabledItems.push(item.id);
                        changed = true;
                    }
                });

                if (changed) {
                    this.savePreferences(preferences);
                }

                this._cache = preferences;
                return preferences;
            }
        } catch (error) {
            console.error('Error loading navigation preferences:', error);
        }

        const defaults = this._getDefaultPreferences();
        this._cache = defaults;
        return defaults;
    },

    /**
     * Save preferences to localStorage
     * @param {Object} preferences - Preferences to save
     * @returns {boolean} Success status
     */
    savePreferences(preferences) {
        const validation = this.validate(preferences);
        if (!validation.valid) {
            console.error('Invalid preferences:', validation.errors);
            return false;
        }

        try {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(preferences));
            this._cache = preferences; // 更新 cache，避免下次重新解析
            return true;
        } catch (error) {
            console.error('Error saving navigation preferences:', error);
            return false;
        }
    },

    /**
     * Export preferences for backup/transfer
     * @returns {string} JSON string of preferences
     */
    exportPreferences() {
        const preferences = this.loadPreferences();
        return JSON.stringify(preferences, null, 2);
    },

    /**
     * Import preferences from JSON string
     * @param {string} jsonString - JSON string to import
     * @returns {boolean} Success status
     */
    importPreferences(jsonString) {
        try {
            const preferences = JSON.parse(jsonString);
            const validation = this.validate(preferences);

            if (!validation.valid) {
                console.error('Invalid preferences to import:', validation.errors);
                return false;
            }

            this.savePreferences(preferences);
            return true;
        } catch (error) {
            console.error('Error importing navigation preferences:', error);
            return false;
        }
    },

    /**
     * Get default preferences
     * @returns {Object} Default preferences object
     * @private
     */
    _getDefaultPreferences() {
        return {
            version: this.PREFERENCES_VERSION,
            enabledItems: NAV_ITEMS.filter((item) => item.defaultEnabled).map((item) => item.id),
        };
    },
};

// Make available on window for cross-script access
window.NAV_ITEMS = NAV_ITEMS;
window.NavPreferences = NavPreferences;

export { NAV_ITEMS, NavPreferences };
