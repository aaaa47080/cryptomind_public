// ========================================
// ton-pay.js — 論壇共用的 TON Connect 付款流程
// 鏡像 premium.js 的 TON 付款邏輯：建立訂單 → 錢包簽章 → 後端驗證。
// 依賴：window.tonConnectUI（ton-auth.js 建立）、window.TonWeb（HTML 載入）
// ========================================

/**
 * 建立 TON 訂單並讓錢包簽章送出款項。
 * @param {string} orderUrl - 建立訂單的後端 endpoint（如 '/api/forum/posts/ton-order'）
 * @param {object} [extraPayload] - 額外 POST body 欄位
 * @returns {Promise<object>} { order, tx_hash } - 訂單與鏈上 tx hash（comment）
 */
/**
 * 論壇子頁沒有 main.js，tonConnectUI 可能尚未建立；
 * 用 ton-auth.js 的單例 getter 現場建立，並等 SDK 從 localStorage 還原連線。
 */
async function _ensureForumWallet() {
    if (window.tonConnectUI) return window.tonConnectUI;
    if (typeof window.getTonConnectUI !== 'function') return null;
    try {
        const ui = window.getTonConnectUI();
        if (!ui) return null; // CDN script 未載入時 getter 回 null（ton-auth.js）
        if (ui.connectionRestored && typeof ui.connectionRestored.then === 'function') {
            // SDK 官方還原訊號：無儲存連線時「立即」resolve(false)——不盲等，
            // 未連錢包的使用者按下付款立刻跳出連接視窗；有連線時等到還原完成。
            // 3 秒保險上限，避免 promise 異常卡死付款流程。
            await Promise.race([
                ui.connectionRestored,
                new Promise((r) => setTimeout(r, 3000)),
            ]);
        } else {
            for (let i = 0; i < 20 && !ui.wallet; i++) {
                await new Promise((r) => setTimeout(r, 150));
            }
        }
        return window.tonConnectUI;
    } catch (e) {
        console.error('[ton-pay] TonConnectUI init failed:', e);
        return null;
    }
}

async function executeForumTonPayment(orderUrl, extraPayload = {}) {
    const ui = await _ensureForumWallet();
    if (!ui) throw new Error(window.I18n ? window.I18n.t('wallet.walletNotReady') : 'Wallet component not ready, please login first');
    if (typeof window.TonWeb === 'undefined') throw new Error(window.I18n ? window.I18n.t('wallet.tonwebNotLoaded') : 'TonWeb not loaded');
    if (!window.AuthManager?.currentUser) throw new Error(window.I18n ? window.I18n.t('wallet.loginRequired') : 'Please login first');

    // 1. 建立訂單（後端回傳 amount_ton / comment / receiving_address / order_token）
    const order = await AppAPI.post(orderUrl, extraPayload);

    // 2. 建構 comment cell（32-bit 0 opcode + UTF-8 comment）並 base64 編碼
    const cell = new window.TonWeb.boc.Cell();
    cell.bits.writeUint(0, 32);
    cell.bits.writeString(order.comment);
    const payloadB64 = window.TonWeb.utils.bytesToBase64(await cell.toBoc(false));

    const amountNano = Math.round(Number(order.amount_ton) * 1e9).toString();

    // 3. 錢包簽章送出
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

    return { order, tx_hash: order.comment };
}

/**
 * 輪詢後端直到鏈上交易被確認（最多 ~36 秒）。
 * @param {string} verifyUrl - 驗證 endpoint（如 '/api/forum/posts'）
 * @param {object} baseBody - 基本請求 body
 * @param {object} order - executeForumTonPayment 回傳的 order
 * @returns {Promise<object>} 後端回應
 */
async function pollForumTonVerify(verifyUrl, baseBody, order) {
    let lastErr = null;
    for (let i = 0; i < 12; i++) {
        try {
            const res = await AppAPI.post(verifyUrl, {
                ...baseBody,
                order_token: order.order_token,
                comment: order.comment,
            });
            if (res && res.success) return res;
            lastErr = res;
        } catch (e) {
            lastErr = e;
            const m = e.message || '';
            // 確定性錯誤 → 立即停止
            if (/amount|already been used|expired|mismatch|belong|not a/i.test(m)) throw e;
            // 否則（交易尚未上鏈）→ 繼續重試
        }
        await new Promise((r) => setTimeout(r, 3000)); // 3 秒退避
    }
    throw lastErr || new Error(window.I18n ? window.I18n.t('wallet.paymentTimeout') : 'Payment verification timed out. Please check the records later.');
}

window.executeForumTonPayment = executeForumTonPayment;
window.pollForumTonVerify = pollForumTonVerify;

export { executeForumTonPayment, pollForumTonVerify };
