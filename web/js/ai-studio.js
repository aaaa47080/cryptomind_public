/**
 * AIStudioTab — Agents / Presets 管理中心（Phase 1 骨架 + Phase 2 preset UI）
 *
 * 規格：design.md §7（AI Studio 資訊架構）、§8（UI 元件規格）
 * - 總覽：官方 Agent 數 / Preset 數 / 行動政策 / catalog 版本
 * - Agents：官方 Profile catalog 卡片（唯讀；tier、capability、資料來源標示）
 * - Presets：列出/建立/啟用/刪除（Premium；server 端驗證 agent_ids）
 * - Memory/Skill/Tool 完整管理器仍在 Settings（Phase 1 相容期）
 */

var AIStudioTab = {
    _initialized: false,
    _profiles: [],
    _presets: [],
    _quota: { max: 10, used: 0 },

    init() {
        if (this._initialized) return;
        this._initialized = true;
        // 初始分頁高亮（template 預設全部非作用中）
        this.showSection('overview');
        // Memory／Skill 管理器與 Tool 設定（自 Settings 搬入；綁定 ID 不變，
        // 邏輯完全不動——僅改由 AI Studio 進入時初始化）
        if (window.MemoryManager && typeof window.MemoryManager.init === 'function') {
            Promise.resolve(window.MemoryManager.init()).catch((e) => console.warn('MemoryManager init failed:', e));
        }
        if (window.SkillManager && typeof window.SkillManager.init === 'function') {
            Promise.resolve(window.SkillManager.init()).catch((e) => console.warn('SkillManager init failed:', e));
        }
        if (typeof window.initToolSettings === 'function') {
            Promise.resolve(window.initToolSettings()).catch((e) => console.warn('ToolSettings init failed:', e));
        }
        this.refresh();
    },

    _t(key, fallback) {
        if (window.I18n && typeof window.I18n.t === 'function') return window.I18n.t(key, fallback);
        return fallback;
    },

    _escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    },

    async refresh() {
        await Promise.all([this.loadProfiles(), this.loadPresets()]);
        this.renderOverview();
        this.renderProfiles();
        this.renderPresets();
    },

    async loadProfiles() {
        try {
            var data = await AppAPI.get('/api/agent-profiles');
            this._profiles = data.profiles || [];
            this._configVersion = data.config_version || '';
        } catch (err) {
            this._profiles = [];
            if (err && err.status === 404) {
                this._flagOff = true;
            }
        }
    },

    async loadPresets() {
        try {
            var data = await AppAPI.get('/api/agent-presets');
            this._presets = data.presets || [];
            this._quota = data.quota || { max: 10, used: this._presets.length };
            this._officialDefault = data.official_default || null;
        } catch (err) {
            this._presets = [];
        }
    },

    renderOverview() {
        document.getElementById('ai-studio-count-profiles').textContent = this._flagOff ? '–' : String(this._profiles.length);
        document.getElementById('ai-studio-count-presets').textContent = String(this._quota.used || 0);
        var policy = 'read_only';
        var active = this._presets.find((p) => p.is_default);
        if (active) policy = active.action_policy;
        else if (this._officialDefault) policy = this._officialDefault.action_policy;
        document.getElementById('ai-studio-current-policy').textContent =
            policy === 'confirm_actions' ? this._t('aiStudio.confirmActions', '可行動') : this._t('aiStudio.readOnly', '唯讀');
        document.getElementById('ai-studio-config-version').textContent = this._escapeHTML(this._configVersion || '–');
    },

    renderProfiles() {
        var el = document.getElementById('ai-studio-profiles');
        if (!el) return;
        if (this._flagOff) {
            el.innerHTML = '<p class="text-sm text-textMuted col-span-2">' + this._t('aiStudio.flagOff', 'Agent Presets 功能未開放') + '</p>';
            return;
        }
        el.innerHTML = this._profiles
            .map((p) => {
                var caps = (p.capabilities || []).map((c) => '<span class="text-xs px-2 py-0.5 rounded-full bg-surfaceHighlight">' + this._escapeHTML(c) + '</span>').join(' ');
                return (
                    '<div class="rounded-xl border border-borderSubtle/10 bg-surface p-4">' +
                    '<div class="flex items-center justify-between mb-1">' +
                    '<h4 class="font-medium text-secondary">' + this._escapeHTML(p.display_name) + '</h4>' +
                    '<span class="text-xs px-2 py-0.5 rounded-full ' + (p.tier === 'premium' ? 'bg-primary/15 text-primary' : 'bg-surfaceHighlight') + '">' + this._escapeHTML(p.tier) + '</span>' +
                    '</div>' +
                    '<p class="text-sm text-textMuted mb-2">' + this._escapeHTML(p.description) + '</p>' +
                    '<div class="flex flex-wrap gap-1.5">' + caps + '</div>' +
                    '</div>'
                );
            })
            .join('');
    },

    // preset mode / action_policy 的 enum → 各語言標籤（未知的 enum 值原樣顯示）
    _modeLabel(mode) {
        var labels = {
            single: this._t('aiStudio.modeSingle', '單一 Agent'),
            auto: this._t('aiStudio.modeAuto', '自動調度'),
            team: this._t('aiStudio.modeTeam', '團隊協作'),
        };
        return labels[mode] || mode;
    },

    _policyLabel(policy) {
        var labels = {
            read_only: this._t('aiStudio.readOnly', '唯讀'),
            confirm_actions: this._t('aiStudio.confirmActions', '可行動（需確認）'),
        };
        return labels[policy] || policy;
    },

    renderPresets() {
        var list = document.getElementById('ai-studio-preset-list');
        var quota = document.getElementById('ai-studio-preset-quota');
        if (!list) return;
        quota.textContent = (this._quota.used || 0) + ' / ' + (this._quota.max || 10);
        if (!this._presets.length) {
            var official = this._officialDefault;
            list.innerHTML =
                '<div class="rounded-xl border border-dashed border-borderSubtle/10 p-4 text-sm text-textMuted">' +
                this._t('aiStudio.noPresets', '尚無自訂 Preset。') +
                (official ? ' ' + this._t('aiStudio.usingOfficial', '目前使用官方預設') + ' · ' + this._escapeHTML(official.agent_ids.join(', ')) : '') +
                '</div>';
            return;
        }
        list.innerHTML = this._presets
            .map((p) => {
                var agents = (p.agent_ids || []).map(this._escapeHTML).join(', ');
                return (
                    '<div class="rounded-xl border border-borderSubtle/10 bg-surface p-4 flex items-center justify-between gap-3">' +
                    '<div class="min-w-0">' +
                    '<div class="flex items-center gap-2">' +
                    '<h4 class="font-medium text-secondary truncate">' + this._escapeHTML(p.name) + '</h4>' +
                    (p.is_default ? '<span class="text-xs px-2 py-0.5 rounded-full bg-primary/15 text-primary">' + this._t('aiStudio.active', '使用中') + '</span>' : '') +
                    '</div>' +
                    '<p class="text-xs text-textMuted mt-1">' + this._escapeHTML(agents) + ' · ' + this._escapeHTML(this._modeLabel(p.mode)) + ' · ' + this._escapeHTML(this._policyLabel(p.action_policy)) + '</p>' +
                    '</div>' +
                    '<div class="flex gap-2 shrink-0">' +
                    (p.is_default ? '' : '<button data-click="AIStudioTab.activatePreset" data-click-arg="' + encodeURIComponent(p.preset_id) + '" class="px-3 py-1.5 rounded-lg bg-primary text-background text-xs">' + this._t('aiStudio.activate', '啟用') + '</button>') +
                    '<button data-click="AIStudioTab.deletePreset" data-click-arg="' + encodeURIComponent(p.preset_id) + '" class="px-3 py-1.5 rounded-lg bg-surfaceHighlight text-xs">' + this._t('aiStudio.delete', '刪除') + '</button>' +
                    '</div></div>'
                );
            })
            .join('');
    },

    // 返回：回到進入 AI Studio 前的分頁（spa.js 記錄），沒有紀錄就回 chat
    goBack() {
        const returnTab = (window.AppStore && AppStore.get('aiStudioReturnTab')) || 'chat';
        if (typeof window.switchTab === 'function') window.switchTab(returnTab);
    },

    // 極簡主題切換（light↔dark）：與主站共用 selectedTheme，
    // 行為對齊 ThemeSwitcher.applyTheme（class + localStorage + themeChanged 事件）
    toggleTheme() {
        const root = document.documentElement;
        const toDark = !root.classList.contains('dark');
        root.classList.toggle('dark', toDark);
        try {
            localStorage.setItem('selectedTheme', toDark ? 'dark' : 'light');
        } catch (err) { /* localStorage 不可用時只切當前頁 */ }
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', toDark ? '#14161F' : '#FFFDF9');
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: toDark ? 'dark' : 'light', effective: toDark ? 'dark' : 'light' } }));
    },

    showSection(section) {
        ['overview', 'agents', 'presets', 'skills', 'memory', 'tools'].forEach((name) => {
            document.getElementById('ai-studio-' + name)?.classList.toggle('hidden', name !== section);
        });
        // segmented control：作用中鈕 = surface 底浮起；非作用中 = muted 文字
        document.querySelectorAll('.ai-studio-nav').forEach((btn) => {
            var isActive = btn.getAttribute('data-click-arg') === section;
            btn.classList.toggle('bg-surface', isActive);
            btn.classList.toggle('text-secondary', isActive);
            btn.classList.toggle('shadow-sm', isActive);
            btn.classList.toggle('text-textMuted', !isActive);
        });
    },

    openCreatePreset() {
        var form = document.getElementById('ai-studio-preset-form');
        if (!form) return;
        var boxes = document.getElementById('ai-studio-preset-agent-checkboxes');
        boxes.innerHTML = this._profiles
            .map(
                (p) =>
                    '<label class="flex items-center gap-2 text-sm"><input type="checkbox" class="ai-studio-agent-cb" value="' +
                    this._escapeHTML(p.id) + '"> ' + this._escapeHTML(p.display_name) + '</label>'
            )
            .join('');
        form.classList.remove('hidden');
    },

    closeCreatePreset() {
        document.getElementById('ai-studio-preset-form')?.classList.add('hidden');
    },

    async submitCreatePreset() {
        var name = document.getElementById('ai-studio-preset-name')?.value?.trim();
        var agentIds = Array.from(document.querySelectorAll('.ai-studio-agent-cb:checked')).map((cb) => cb.value);
        var mode = document.getElementById('ai-studio-preset-mode')?.value || 'single';
        var policy = document.getElementById('ai-studio-preset-policy')?.value || 'read_only';
        if (!name || !agentIds.length) {
            window.showInfoDialog({
                title: this._t('aiStudio.formInvalid', '請填寫名稱並選擇至少一個 Agent'),
                tone: 'warning',
            });
            return;
        }
        try {
            await AppAPI.post('/api/agent-presets', {
                name: name,
                agent_ids: agentIds,
                mode: mode,
                analysis_mode: 'quick',
                action_policy: policy,
                capability_overrides: {},
                is_default: false,
            });
            this.closeCreatePreset();
            await this.refresh();
        } catch (err) {
            window.showInfoDialog({
                title: this._t('aiStudio.createFailed', '建立失敗'),
                message: (err && err.message) || '',
                tone: 'error',
            });
        }
    },

    async activatePreset(presetId) {
        try {
            await AppAPI.post('/api/agent-presets/' + encodeURIComponent(presetId) + '/activate');
            await this.refresh();
        } catch (err) {
            window.showInfoDialog({
                title: this._t('aiStudio.activateFailed', '啟用失敗'),
                message: (err && err.message) || '',
                tone: 'error',
            });
        }
    },

    async deletePreset(presetId) {
        const ok = await window.showConfirmDialog({
            title: this._t('aiStudio.delete', '刪除'),
            message: this._t('aiStudio.confirmDelete', '確定刪除此 Preset？'),
            danger: true,
        });
        if (!ok) return;
        try {
            await AppAPI.delete('/api/agent-presets/' + encodeURIComponent(presetId));
            if (typeof window.showToast === 'function') {
                window.showToast(this._t('aiStudio.deleteDone', '已刪除'), 'success');
            }
            await this.refresh();
        } catch (err) {
            window.showInfoDialog({
                title: this._t('aiStudio.deleteFailed', '刪除失敗'),
                message: (err && err.message) || '',
                tone: 'error',
            });
        }
    },
};

window.AIStudioTab = AIStudioTab;
