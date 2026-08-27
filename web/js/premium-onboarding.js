/**
 * Premium 付款後 onboarding 精靈（design §7.3）
 *
 * 付款成功後立即引導使用者完成第一個受保護設定，讓「保護」在 3 分鐘內真正啟用，
 * 而不是付款後回到首頁、要自己找到錢包監測頁面（design §2.3）。
 *
 * 三步驟，全部使用既有 wallet-monitor / premium API：
 *   1. 確認第一個受保護錢包（POST /api/wallet-monitor/wallets）
 *   2. 選擇監測事件 + 大額門檻（PUT /api/wallet-monitor/settings）
 *   3. 顯示「保護已啟用」摘要（GET /api/premium/status）
 *
 * Telegram 綁定走既有 /api/user/telegram-login 流程（非本精靈內聯），
 * 故 step 3 僅顯示通知管道狀態與綁定入口連結。
 */

const t = (key, fallback, opts) => {
    // premium.onboarding.* 命名空間前綴（2026-08-24 i18n 稽查：此前漏前綴，
    // 30 個 key 永遠查不到 → 全語言都只顯示中文 fallback）
    const fullKey = 'premium.onboarding.' + key;
    if (window.I18n && typeof window.I18n.t === 'function') {
        const v = window.I18n.t(fullKey, opts);
        if (v && v !== fullKey) return v;
    }
    return fallback;
};

class OnboardingWizard {
    constructor() {
        this.settings = null;
        this.walletAdded = false;
        this.choices = {
            scam: true,
            outgoing: true,
            largeOut: true,
            largeOutThreshold: 500,
        };
    }

    /**
     * 啟動精靈。由 premium.js 在付款升級成功後呼叫（取代直接 reload）。
     */
    async start() {
        const user = window.AuthManager?.currentUser;
        if (!user) return; // 未登入則不啟動（理論上不會，付款必已登入）

        // 預設錢包 = 登入錢包（本平台 user_id 即 TON 錢包地址）
        this.defaultWallet = (user.user_id || user.uid || '').trim();
        this._render();
        document.getElementById('onboarding-modal')?.classList.remove('hidden');
        AppUtils?.refreshIcons?.();
    }

    _t(key, fallback, opts) {
        return t(`premium.onboarding.${key}`, fallback, opts);
    }

    _render() {
        // 移除既有實例，避免重複
        document.getElementById('onboarding-modal')?.remove();
        const modal = document.createElement('div');
        modal.id = 'onboarding-modal';
        modal.className =
            'fixed inset-0 bg-background/80 backdrop-blur-sm z-[100] hidden flex items-center justify-center p-4';
        modal.innerHTML = `
            <div class="bg-surface w-full max-w-md max-h-[80dvh] flex flex-col rounded-3xl border border-borderLight shadow-2xl overflow-hidden">
                <div class="px-6 pt-6 pb-3 border-b border-borderSubtle">
                    <div class="flex items-center gap-2 text-primary">
                        <i data-lucide="shield-check" class="w-5 h-5"></i>
                        <span class="font-bold text-secondary" id="onb-title">${this._t('setupProtection', 'Set up your protection')}</span>
                    </div>
                    <div class="mt-3 flex gap-1.5" id="onb-progress">
                        <span class="h-1 flex-1 rounded-full bg-primary"></span>
                        <span class="h-1 flex-1 rounded-full bg-surfaceHighlight"></span>
                        <span class="h-1 flex-1 rounded-full bg-surfaceHighlight"></span>
                    </div>
                </div>
                <div id="onb-body" class="px-6 py-5 min-h-0 overflow-y-auto custom-scrollbar flex-1"></div>
                <div id="onb-footer" class="px-6 pb-6"></div>
            </div>`;
        document.body.appendChild(modal);
        this._renderStep1();
    }

    // ----- Step 1: 錢包 -----
    _renderStep1() {
        this._setProgress(1);
        document.getElementById('onb-title').textContent = this._t('step1Title', 'Step 1 of 3 · Protected wallet');
        document.getElementById('onb-body').innerHTML = `
            <p class="text-sm text-textMuted mb-4">${this._t('step1Desc', 'Confirm the wallet to monitor. We will alert you on suspicious activity.')}</p>
            <label class="block text-xs text-textMuted mb-1">${this._t('walletAddress', 'Wallet address')}</label>
            <input id="onb-wallet" type="text" value="${this.defaultWallet}"
                class="w-full px-3 py-2.5 rounded-xl bg-background border border-borderSubtle text-textMain text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary" />
            <p class="text-xs text-textMuted mt-2">${this._t('walletHint', 'Defaults to your connected wallet. You can monitor up to 5 wallets in Wallet Monitor.')}</p>`;
        document.getElementById('onb-footer').innerHTML = this._footerButtons({
            next: true,
            nextLabel: this._t('next', 'Next'),
            onNext: () => this._saveWallet(),
        });
        AppUtils?.refreshIcons?.();
    }

    async _saveWallet() {
        const addr = (document.getElementById('onb-wallet')?.value || '').trim();
        if (!addr) {
            showToast(this._t('walletRequired', 'Please enter a wallet address'), 'warning');
            return;
        }
        this._setBusy(true);
        try {
            // 取現有設定（後續 step 2 要整包 PUT）
            const cur = await AppAPI.get('/api/wallet-monitor/settings');
            this.settings = (cur && cur.settings) || null;

            // 新增監測錢包（已存在則後端回 already_monitored，視為成功）。
            // 重要：採用 response.settings（含剛加入的 monitored_wallets）作為後續
            // PUT 的底，否則用第一步的舊 settings 整包 PUT 會把新錢包覆蓋掉。
            const res = await AppAPI.post('/api/wallet-monitor/wallets', { address: addr, label: '' });
            if (res && res.settings) {
                this.settings = res.settings;
            }
            this.walletAdded = true;
            this._renderStep2();
        } catch (e) {
            showToast(this._t('saveWalletFailed', 'Failed to save wallet', { msg: e.message }), 'error');
        } finally {
            this._setBusy(false);
        }
    }

    // ----- Step 2: 監測事件 -----
    _renderStep2() {
        this._setProgress(2);
        document.getElementById('onb-title').textContent = this._t('step2Title', 'Step 2 of 3 · What to watch');
        document.getElementById('onb-body').innerHTML = `
            <p class="text-sm text-textMuted mb-4">${this._t('step2Desc', 'Choose the activity you want alerts for.')}</p>
            <div class="space-y-3">
                ${this._toggleRow('onb-scam', this._t('scamContact', 'Scam-address contact'), this.choices.scam)}
                ${this._toggleRow('onb-outgoing', this._t('outgoingTransfer', 'Outgoing transfers'), this.choices.outgoing)}
                <div class="flex items-center justify-between gap-3 p-3 rounded-xl bg-background/50 border border-borderSubtle">
                    <label class="flex items-center gap-2 text-sm text-textMain cursor-pointer">
                        <input id="onb-largeout" type="checkbox" ${this.choices.largeOut ? 'checked' : ''} class="w-4 h-4 accent-[var(--primary)]" />
                        ${this._t('largeOutflow', 'Large outflow alert')}
                    </label>
                    <span class="flex items-center gap-1 text-xs text-textMuted">
                        ≥<input id="onb-threshold" type="number" min="1" value="${this.choices.largeOutThreshold}"
                            class="w-20 px-2 py-1 rounded-lg bg-background border border-borderSubtle text-textMain text-xs" /> TON
                    </span>
                </div>
            </div>
            <p class="text-xs text-textMuted mt-4">${this._t('step2Hint', 'You can adjust these anytime in Wallet Monitor settings.')}</p>`;
        document.getElementById('onb-footer').innerHTML = this._footerButtons({
            back: true,
            next: true,
            nextLabel: this._t('activate', 'Activate protection'),
            onBack: () => this._renderStep1(),
            onNext: () => this._saveSettings(),
        });
        AppUtils?.refreshIcons?.();
    }

    _toggleRow(id, label, checked) {
        return `
            <label class="flex items-center gap-2 p-3 rounded-xl bg-background/50 border border-borderSubtle text-sm text-textMain cursor-pointer">
                <input id="${id}" type="checkbox" ${checked ? 'checked' : ''} class="w-4 h-4 accent-[var(--primary)]" />
                ${label}
            </label>`;
    }

    async _saveSettings() {
        this.choices.scam = document.getElementById('onb-scam')?.checked ?? true;
        this.choices.outgoing = document.getElementById('onb-outgoing')?.checked ?? true;
        this.choices.largeOut = document.getElementById('onb-largeout')?.checked ?? true;
        this.choices.largeOutThreshold = Math.max(1, Number(document.getElementById('onb-threshold')?.value) || 500);

        // 整包覆蓋（design §9.4：PUT settings 接受完整結構）。以現有 settings 為底，
        // 套用使用者選擇，保留 monitored_wallets / channels。
        const base = this.settings && typeof this.settings === 'object'
            ? JSON.parse(JSON.stringify(this.settings))
            : { monitored_wallets: [], alerts: {}, channels: { in_app: true, telegram: true } };
        base.alerts = base.alerts || {};
        base.alerts.scam = { enabled: this.choices.scam };
        base.alerts.outgoing = { enabled: this.choices.outgoing, min_amount_ton: base.alerts.outgoing?.min_amount_ton ?? 10 };
        base.alerts.large_out = { enabled: this.choices.largeOut, threshold_ton: this.choices.largeOutThreshold };
        base.channels = base.channels || { in_app: true, telegram: true };

        this._setBusy(true);
        try {
            await AppAPI.put('/api/wallet-monitor/settings', { settings: base });
            this.settings = base;
            await this._renderStep3();
        } catch (e) {
            showToast(this._t('saveSettingsFailed', 'Failed to save settings', { msg: e.message }), 'error');
        } finally {
            this._setBusy(false);
        }
    }

    // ----- Step 3: 摘要 -----
    async _renderStep3() {
        this._setProgress(3);
        document.getElementById('onb-title').textContent = this._t('step3Title', 'Protection enabled');
        document.getElementById('onb-body').innerHTML =
            `<div class="flex items-center justify-center py-4"><span class="animate-pulse text-textMuted text-sm">${this._t('loading', 'Loading...')}</span></div>`;
        document.getElementById('onb-footer').innerHTML = '';

        let expiry = '';
        try {
            const status = await AppAPI.get('/api/premium/status');
            expiry = status?.membership?.membership_expires_at || status?.membership?.expires_at || '';
        } catch (_) { /* 非致命 */ }

        const rules = [
            this.choices.scam ? this._t('ruleScam', 'Scam contact') : null,
            this.choices.outgoing ? this._t('ruleOutgoing', 'Outgoing') : null,
            this.choices.largeOut ? this._t('ruleLargeOut', 'Large outflow') : null,
        ].filter(Boolean);

        document.getElementById('onb-body').innerHTML = `
            <div class="text-center mb-4">
                <div class="w-14 h-14 rounded-full bg-success/15 flex items-center justify-center mx-auto mb-3">
                    <i data-lucide="check" class="w-7 h-7 text-success"></i>
                </div>
            </div>
            <div class="space-y-2 text-sm">
                <div class="flex justify-between"><span class="text-textMuted">${this._t('sumWallets', 'Protected wallets')}</span><span class="text-textMain font-bold">${this.settings?.monitored_wallets?.length || 1} / 5</span></div>
                <div class="flex justify-between"><span class="text-textMuted">${this._t('sumRules', 'Active rules')}</span><span class="text-textMain font-bold">${rules.join('、') || '—'}</span></div>
                <div class="flex justify-between"><span class="text-textMuted">${this._t('sumChannels', 'Channels')}</span><span class="text-textMain font-bold">${this._t('inApp', 'In-app')}${this.settings?.channels?.telegram ? ' + Telegram' : ''}</span></div>
                <div class="flex justify-between"><span class="text-textMuted">${this._t('sumNextCheck', 'Next check')}</span><span class="text-textMain font-bold">~10 min</span></div>
                ${expiry ? `<div class="flex justify-between"><span class="text-textMuted">${this._t('sumExpiry', 'Access until')}</span><span class="text-textMain font-bold">${expiry.slice(0, 10)}</span></div>` : ''}
            </div>
            <p class="text-xs text-textMuted mt-4 text-center">${this._t('telegramHint', 'Bind Telegram in Settings to receive push alerts.')}</p>`;
        document.getElementById('onb-footer').innerHTML = `
            <button id="onb-done" class="w-full py-3 bg-primary hover:brightness-110 text-background font-bold rounded-2xl transition">
                ${this._t('done', 'Go to Wallet Monitor')}
            </button>`;
        document.getElementById('onb-done')?.addEventListener('click', () => this._finish());
        AppUtils?.refreshIcons?.();
    }

    _finish() {
        document.getElementById('onboarding-modal')?.remove();
        // premium.html 是獨立頁面，reload 只會回到原頁；直接導向 SPA 的錢包監測分頁。
        window.location.href = '/static/index.html#wallet-monitor';
    }

    // ----- helpers -----
    _setProgress(step) {
        const bars = document.getElementById('onb-progress')?.children;
        if (!bars) return;
        for (let i = 0; i < bars.length; i++) {
            bars[i].className = `h-1 flex-1 rounded-full ${i < step ? 'bg-primary' : 'bg-surfaceHighlight'}`;
        }
    }

    _setBusy(busy) {
        document.querySelectorAll('#onb-footer button').forEach((b) => {
            b.disabled = busy;
            b.classList.toggle('opacity-50', busy);
        });
    }

    _footerButtons({ back, next, backLabel, nextLabel, onBack, onNext }) {
        const backBtn = back
            ? `<button id="onb-back" class="flex-1 py-3 bg-surfaceHighlight hover:brightness-110 text-textMuted font-bold rounded-2xl transition border border-borderSubtle">${backLabel || this._t('back', 'Back')}</button>`
            : '';
        const nextBtn = next
            ? `<button id="onb-next" class="flex-1 py-3 bg-primary hover:brightness-110 text-background font-bold rounded-2xl transition">${nextLabel}</button>`
            : '';
        const html = `<div class="flex gap-3">${backBtn}${nextBtn}</div>`;
        // 綁事件需在插入 DOM 後；用 setTimeout 確保已掛載
        setTimeout(() => {
            if (back) document.getElementById('onb-back')?.addEventListener('click', onBack);
            if (next) document.getElementById('onb-next')?.addEventListener('click', onNext);
        }, 0);
        return html;
    }
}

const onboardingWizard = new OnboardingWizard();
const startOnboardingWizard = () => onboardingWizard.start();
window.OnboardingWizard = onboardingWizard;
window.startOnboardingWizard = startOnboardingWizard;

export { OnboardingWizard, startOnboardingWizard };
