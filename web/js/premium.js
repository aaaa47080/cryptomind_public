/**
 * window.I18n.t('premium.premiumMemberLabel') || 'Premium Member'功能模組
 * 處理升級到 window.I18n.t('premium.premiumMemberLabel') || 'Premium Member'的支付和狀態管理
 */

// Import loadPiPrices from forum-config.js (must come before any usage)
import { loadPiPrices } from './forum-config.js';
import { startOnboardingWizard } from './premium-onboarding.js';

class PremiumManager {
    constructor() {
        this.premiumPrice = null; // initialized to null, entirely dependent on backend
        this.selectedPlan = 'premium_monthly'; // 'premium_monthly' | 'premium_yearly'
        this.initEventListeners();
    }

    /**
     * 取得指定方案的 TON 顯示價（來自後端 /pricing，非 client 宣告）。
     */
    _priceForPlan(plan) {
        if (plan === 'premium_yearly') return window.TonPrices?.premium_yearly ?? null;
        return window.TonPrices?.premium ?? null;
    }

    /**
     * 月／年方案切換（design §8：月 30 天 / 年 365 天使用權）。
     */
    initPlanToggle() {
        const toggles = document.querySelectorAll('[data-plan-toggle]');
        if (!toggles.length) return;
        toggles.forEach((btn) => {
            btn.addEventListener('click', () => {
                this.selectedPlan = btn.dataset.planToggle || 'premium_monthly';
                toggles.forEach((b) => {
                    const active = b === btn;
                    b.setAttribute('aria-pressed', active ? 'true' : 'false');
                    b.classList.toggle('ring-2', active);
                    b.classList.toggle('ring-primary', active);
                    b.classList.toggle('text-primary', active);
                    b.classList.toggle('bg-primary/10', active);
                    b.classList.toggle('text-textMuted', !active);
                });
                this.updatePriceDisplay();
            });
        });
    }

    /**
     * 發送 log 到後端服務器
     */
    async serverLog(level, message, data = null) {
        try {
            await AppAPI.post('/api/client/log', {
                source: 'premium',
                level: level,
                message: message,
                data: data,
            });
        } catch (e) {
            console.warn(window.I18n.t('premium.sendLogFailed') || '[Premium] 發送 log 到後端失敗:', e);
        }
    }

    /**
     * 初始化事件監聽器
     */
    initEventListeners() {
        // 監聽 DOMContentLoaded
        document.addEventListener('DOMContentLoaded', () => {
            // 嘗試從全局變數獲取（如果已經載入）
            if (window.TonPrices?.premium) {
                this.premiumPrice = window.TonPrices.premium;
            }
            this.updatePriceDisplay();
            this.initUpgradeButtons();
            this.initPlanToggle();

            // 如果價格仍未載入，嘗試手動載入
            if (this.premiumPrice === null && typeof loadPiPrices === 'function') {
                // 如果正在載入中，等待 ton-prices-updated 事伯
                if (window.TonPrices?.loading) {
                    const waitForPrice = () => {
                        if (window.TonPrices?.premium) {
                            this.premiumPrice = window.TonPrices.premium;
                            this.updatePriceDisplay();
                        }
                        this.initUpgradeButtons();
                    };
                    document.addEventListener('ton-prices-updated', waitForPrice, { once: true });
                } else {
                    loadPiPrices();
                }
            }
        });

        // 監聽價格更新事件 (由 forum.js 觸發)
        document.addEventListener('ton-prices-updated', () => {
            if (window.TonPrices?.premium) {
                this.premiumPrice = window.TonPrices.premium;
                this.updatePriceDisplay();
            }
        });
    }

    /**
     * 更新價格顯示（依當前選擇的方案 monthly/yearly）
     */
    updatePriceDisplay() {
        const price = this._priceForPlan(this.selectedPlan);
        this.premiumPrice = price; // 同步給確認對話框使用

        let displayHtml;
        if (price !== null && price !== undefined) {
            displayHtml = `${price} TON`;
        } else {
            displayHtml = `<span class="animate-pulse">${window.I18n?.t('common.loading') || 'Loading...'}</span>`;
            // 價格還沒載入——主動觸發一次載入。loadPiPrices 內部有 loading
            // flag 防重複請求，安全可重複呼叫。
            if (typeof loadPiPrices === 'function' && !window.TonPrices?.loading) {
                loadPiPrices();
            }
        }

        // 更新所有顯示價格的元素
        const priceElements = document.querySelectorAll('[data-price="premium"]');
        priceElements.forEach((element) => {
            element.innerHTML = displayHtml;
        });
    }

    /**
     * 初始化升級按鈕
     */
    initUpgradeButtons() {
        // 查找所有升級按鈕並添加事件監聽器
        const upgradeButtons = document.querySelectorAll('.upgrade-premium-btn');
        upgradeButtons.forEach((button) => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleUpgradeClick();
            });
        });
    }

    /**
     * 處理升級按鈕點擊
     */
    async handleUpgradeClick() {
        try {
            // 1. 必須已登入
            if (!window.AuthManager || !window.AuthManager.currentUser) {
                showToast(window.I18n.t('premium.loginRequired'), 'warning');
                return;
            }

            // 2. 錢包元件必須就緒
            const ui = window.tonConnectUI;
            if (!ui) {
                showToast(window.I18n.t('premium.walletComponentLoading') || 'Wallet component loading, please try later', 'warning');
                return;
            }
            if (!ui.connected) {
                showToast(window.I18n.t('premium.connectWalletFirst') || 'Please connect TON wallet first', 'warning');
                return;
            }

            // 3. 建立付款訂單（後端回傳精確金額、收款地址與唯一 comment）
            const plan = this.selectedPlan;
            const order = await AppAPI.post('/api/premium/ton-order', { plan });
            if (!order || !order.success) {
                throw new Error(window.I18n.t('premium.cannotCreateOrder') || 'Cannot create payment order');
            }
            this.premiumPrice = order.amount_ton;
            this.tonNetwork = order.network;

            // 4. 確認
            const confirmed = await this.showUpgradeConfirmation();
            if (!confirmed) return;

            // 5. 付款 + 升級
            await this.startTonUpgrade(order, plan);
        } catch (error) {
            console.error(window.I18n.t('premium.upgradeError') || '[Premium] 升級錯誤:', error);
            showToast(window.I18n.t('premium.upgradeErrorMsg', { msg: error.message }), 'error');
        }
    }

    /**
     * 顯示升級確認對話框
     */
    async showUpgradeConfirmation() {
        return new Promise((resolve) => {
            // 檢查是否有現有的確認對話框
            const existingModal = document.getElementById('confirm-modal');
            if (existingModal) {
                // 設置對話框內容
                document.getElementById('confirm-modal-title').textContent = window.I18n.t('premium.confirmUpgrade');
                document.getElementById('confirm-modal-message').innerHTML =
                    window.I18n.t('premium.confirmMessage', { price: this.premiumPrice });

                // 設置圖標
                const iconEl = document.getElementById('confirm-modal-icon');
                iconEl.className =
                    'w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6 bg-success/20';
                iconEl.innerHTML = '<i data-lucide="star" class="w-8 h-8 text-success"></i>';

                // 設置按鈕
                const cancelBtn = document.getElementById('confirm-modal-cancel');
                const confirmBtn = document.getElementById('confirm-modal-confirm');

                cancelBtn.textContent = window.I18n.t('common.cancel');
                confirmBtn.textContent = window.I18n.t('premium.pay', { price: this.premiumPrice });
                confirmBtn.className =
                    'flex-1 py-3 bg-success hover:brightness-110 text-background font-bold rounded-2xl transition shadow-lg';

                // 設置事件處理器
                const handleCancel = () => {
                    existingModal.classList.add('hidden');
                    resolve(false);
                };

                const handleConfirm = async () => {
                    existingModal.classList.add('hidden');
                    resolve(true);

                    // 移除事件監聽器
                    cancelBtn.removeEventListener('click', handleCancel);
                    confirmBtn.removeEventListener('click', handleConfirm);
                };

                // 添加事件監聽器
                cancelBtn.removeEventListener('click', handleCancel);
                confirmBtn.removeEventListener('click', handleConfirm);
                cancelBtn.addEventListener('click', handleCancel);
                confirmBtn.addEventListener('click', handleConfirm);

                // 顯示對話框
                existingModal.classList.remove('hidden');

                // 更新 Lucide 圖標
                AppUtils.refreshIcons();
            } else {
                // 如果沒有預設對話框，使用瀏覽器確認
                const result = confirm(
                    `${window.I18n.t('premium.confirmUpgradeMessage') || 'Confirm upgrade to Premium? '}${this.premiumPrice} TON ${window.I18n.t('premium.willBeDeducted') || 'will be deducted from your wallet.'}`
                );
                resolve(result);
            }
        });
    }

    /**
     * 開始升級流程
     */
    async startTonUpgrade(order, plan) {
        let loadingToastId = null;
        const clearLoadingToast = () => {
            if (!loadingToastId) return;
            if (window.UIShell && typeof window.UIShell.dismissToast === 'function') {
                window.UIShell.dismissToast(loadingToastId);
            } else if (typeof loadingToastId.remove === 'function') {
                loadingToastId.remove();
            }
            loadingToastId = null;
        };

        try {
            // 1. 透過 TON Connect 送出付款（錢包彈窗簽署）
            this.serverLog('info', 'premium.tonPaymentStarted', { comment: order.comment });
            await this.executeTonPayment(order);

            // 2. 交易需數秒上鏈，顯示處理中並輪詢後端驗證
            loadingToastId = showToast(window.I18n.t('premium.processingUpgrade'), 'info', 0);
            const upgradeResult = await this.requestTonUpgrade(order, plan);
            this.serverLog('info', 'premium.backendUpgradeResult', upgradeResult);

            if (upgradeResult && upgradeResult.success) {
                clearLoadingToast();
                showToast(window.I18n.t('premium.congrats'), 'success', 5000);
                this.updateUserInterface();
                // 付款成功 → 啟動保護設定精靈（design §7.3），取代直接 reload。
                setTimeout(() => {
                    if (typeof startOnboardingWizard === 'function') {
                        startOnboardingWizard();
                    } else {
                        window.location.reload();
                    }
                }, 1500);
            } else {
                clearLoadingToast();
                showToast(
                    window.I18n.t('premium.upgradeFailedMsg', {
                        msg: (upgradeResult && upgradeResult.message) || '',
                    }),
                    'error'
                );
            }
        } catch (error) {
            console.error(window.I18n.t('premium.tonUpgradeFlowError') || '[Premium] TON 升級流程錯誤:', error);
            clearLoadingToast();
            const msg = /cancel|reject|abort|decline|closed/i.test(error.message || '')
                ? window.I18n.t('premium.paymentCanceled') || 'Payment cancelled'
                : error.message;
            showToast(window.I18n.t('premium.upgradeFailedMsg', { msg }), 'error');
        }
    }

    /**
     * 透過 TON Connect 送出付款交易（附帶綁定訂單的 text comment）
     */
    async executeTonPayment(order) {
        const ui = window.tonConnectUI;
        if (!ui) throw new Error(window.I18n.t('premium.walletComponentNotReady') || 'Wallet component not ready');
        if (typeof window.TonWeb === 'undefined') throw new Error(window.I18n.t('premium.tonWebNotLoaded') || 'TonWeb not loaded');

        // text comment cell：32-bit 0 opcode + UTF-8 comment
        const cell = new window.TonWeb.boc.Cell();
        cell.bits.writeUint(0, 32);
        cell.bits.writeString(order.comment);
        const payloadB64 = window.TonWeb.utils.bytesToBase64(await cell.toBoc(false));

        const amountNano = Math.round(Number(order.amount_ton) * 1e9).toString();
        await ui.sendTransaction({
            validUntil: Math.floor(Date.now() / 1000) + 600,
            messages: [
                {
                    address: order.receiving_address,
                    amount: amountNano,
                    payload: payloadB64,
                },
            ],
        });
    }

    /**
     * 輪詢後端驗證鏈上交易並升級（交易上鏈需時間）。
     */
    async requestTonUpgrade(order, plan) {
        let lastErr = null;
        for (let i = 0; i < 12; i++) {
            try {
                const res = await AppAPI.post('/api/premium/upgrade', {
                    plan,
                    months: plan === 'premium_yearly' ? 12 : 1,
                    order_token: order.order_token,
                    comment: order.comment,
                });
                if (res && res.success) return res;
                lastErr = res;
            } catch (e) {
                lastErr = e;
                const m = e.message || '';
                // 確定性錯誤（金額不符 / 已使用 / 過期）→ 立即停止
                if (/amount|already been used|expired|mismatch|belong/i.test(m)) {
                    throw e;
                }
                // 其餘（尚未偵測到交易）→ 繼續重試
            }
            await new Promise((r) => setTimeout(r, 3000));
        }
        throw new Error(
            (lastErr && (lastErr.message || lastErr.detail)) ||
                window.I18n.t('premium.paymentVerifyTimeout') || 'Payment verification timed out. If deducted, please refresh later to confirm membership.'
        );
    }

    /**
     * 更新用戶界面以反映新的會員狀態
     */
    updateUserInterface() {
        // 更新會員狀態顯示
        const membershipBadges = document.querySelectorAll('.membership-badge');
        membershipBadges.forEach((badge) => {
            badge.innerHTML = `
                <i data-lucide="star" class="w-3 h-3"></i>
                window.I18n.t('premium.premiumMemberLabel') || 'Premium Member'
            `;
            badge.className =
                'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-gradient-to-r from-yellow-500 to-orange-500 text-white';
        });

        // 更新用戶頭像（如果適用）
        const avatarElements = document.querySelectorAll('.premium-avatar');
        avatarElements.forEach((avatar) => {
            avatar.classList.add(
                'ring-2',
                'ring-yellow-500',
                'ring-offset-2',
                'ring-offset-background'
            );
        });

        // 更新功能限制提示（如果適用）
        const premiumFeatures = document.querySelectorAll('.premium-feature');
        premiumFeatures.forEach((feature) => {
            feature.classList.remove('hidden');
        });

        // 更新 Lucide 圖標
        AppUtils.refreshIcons();
    }

    /**
     * 檢查用戶當前的會員狀態
     */
    async checkMembershipStatus(userId) {
        try {
            const result = await AppAPI.get('/api/premium/status');

            if (result.success) {
                return result.membership;
            }

            return { tier: 'free', is_premium: false, expires_at: null };
        } catch (error) {
            console.error(window.I18n.t('premium.getMembershipStatusFailed') || '[Premium] 獲取會員狀態失敗:', error);
            return { tier: 'free', is_premium: false, expires_at: null };
        }
    }
}

// 初始化 PremiumManager
const premiumManager = new PremiumManager();
window.PremiumManager = premiumManager;

// 暴露全局函數
const upgradeToPremium = () => premiumManager.handleUpgradeClick();
const checkMembershipStatus = (userId) => premiumManager.checkMembershipStatus(userId);
window.upgradeToPremium = upgradeToPremium;
window.checkMembershipStatus = checkMembershipStatus;

export { PremiumManager, upgradeToPremium, checkMembershipStatus };

console.log('[Premium] module loaded');
