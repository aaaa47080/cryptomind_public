/**
 * chat-preset.js — 聊天輸入列的 Preset 選擇器（逐次套用，2026-08-16）
 *
 * - 後端就緒：/api/analyze 的 QueryRequest.preset_id（僅縮小工具池）
 * - 選擇存在 sessionStorage（chatPresetId），跨對話保持到關分頁
 * - Free 使用者只見「官方預設」（presets 為 Premium 功能，403 時靜默降級）
 * - ChatPreset.getSelectedId() 供送出時帶入 preset_id
 */

var ChatPreset = {
    _presets: [],
    _selectedId: null, // null = 官方預設
    _open: false,

    init() {
        if (this._initialized) return;
        this._initialized = true;
        this._selectedId = sessionStorage.getItem('chatPresetId') || null;
        var pill = document.getElementById('chat-preset-pill');
        if (pill) {
            pill.addEventListener('click', (e) => { e.stopPropagation(); this.toggle(); });
        }
        document.addEventListener('click', () => this.close());
        this._load();
    },

    _t(key, fallback) {
        if (window.I18n && typeof window.I18n.t === 'function') {
            var v = window.I18n.t('chatPreset.' + key);
            if (v && v !== 'chatPreset.' + key) return v;
        }
        return fallback;
    },

    async _load() {
        try {
            var data = await AppAPI.get('/api/agent-presets');
            this._presets = data.presets || [];
        } catch (err) {
            this._presets = []; // Free / flag off：靜默降級為僅官方預設
        }
        this._renderPill();
    },

    _selectedName() {
        if (!this._selectedId) return this._t('official', '官方預設');
        var p = this._presets.find((x) => x.preset_id === this._selectedId);
        return p ? p.name : this._t('official', '官方預設');
    },

    _renderPill() {
        var pill = document.getElementById('chat-preset-pill');
        if (!pill) return;
        pill.querySelector('span') && (pill.querySelector('span').textContent = this._selectedName());
    },

    toggle() {
        if (this._open) { this.close(); return; }
        this._open = true;
        var menu = document.getElementById('chat-preset-menu');
        if (!menu) return;
        var items = [
            { id: null, name: this._t('official', '官方預設'), desc: this._t('officialDesc', '一般研究（預設）') },
        ].concat(this._presets.map((p) => ({
            id: p.preset_id,
            name: p.name,
            desc: (p.agent_ids || []).join(', '),
        })));
        menu.innerHTML = items.map((it) => {
            var active = (it.id || null) === (this._selectedId || null);
            return (
                '<button data-preset-id="' + (it.id || '') + '" class="w-full text-left px-3 py-2 rounded-lg ' +
                (active ? 'bg-surfaceHighlight' : 'hover:bg-surfaceHighlight/60') + ' transition">' +
                '<span class="block text-sm ' + (active ? 'text-primary font-medium' : 'text-secondary') + '">' +
                this._esc(it.name) + '</span>' +
                (it.desc ? '<span class="block text-[10px] text-textMuted mt-0.5 truncate">' + this._esc(it.desc) + '</span>' : '') +
                '</button>'
            );
        }).join('');
        menu.classList.remove('hidden');
        menu.querySelectorAll('[data-preset-id]').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.select(btn.getAttribute('data-preset-id') || null);
            });
        });
    },

    close() {
        this._open = false;
        document.getElementById('chat-preset-menu')?.classList.add('hidden');
    },

    select(presetId) {
        this._selectedId = presetId || null;
        if (this._selectedId) sessionStorage.setItem('chatPresetId', this._selectedId);
        else sessionStorage.removeItem('chatPresetId');
        this._renderPill();
        this.close();
        if (typeof window.showToast === 'function') {
            window.showToast(
                this._t('applied', '已套用') + '：' + this._selectedName(),
                'success'
            );
        }
    },

    getSelectedId() {
        return this._selectedId || null;
    },

    _esc(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
};

window.ChatPreset = ChatPreset;

// Auto-init（DOM ready；chat 輸入列是首屏靜態標記）
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ChatPreset.init());
} else {
    ChatPreset.init();
}
