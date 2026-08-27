// ========================================
// ton-auth.js — TON Connect 初始化與錢包登入
// 取代 pi-auth.js（Web DApp 形態）。沿用 AuthManager 的 session 機制。
// 依賴：window.TON_CONNECT_UI（index.html 以 <script> 載入）
// ========================================

const TON_LOGIN_FLAG = '_tonLoginInProgress';
window[TON_LOGIN_FLAG] = false;

// ---- 工具：raw "0:hex" -> user-friendly 地址（UQ/0Q）----
function _crc16(data) {
    let crc = 0;
    for (const b of data) {
        crc ^= b << 8;
        for (let i = 0; i < 8; i++) {
            crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
        }
    }
    return crc;
}

function rawToFriendly(raw, testnet, bounceable = false) {
    // raw = "0:<64 hex>"
    const [wcStr, hashHex] = raw.split(':');
    const wc = parseInt(wcStr, 10) & 0xff;
    let tag = bounceable ? 0x11 : 0x51;
    if (testnet) tag |= 0x80;
    const hash = hashHex.match(/.{2}/g).map((h) => parseInt(h, 16));
    const body = [tag, wc, ...hash];
    const crc = _crc16(body);
    const full = [...body, (crc >> 8) & 0xff, crc & 0xff];
    let bin = '';
    for (const b of full) bin += String.fromCharCode(b);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_');
}

// ---- TON Connect 單例 ----
let _tonConnectUI = null;

function getTonConnectUI() {
    if (_tonConnectUI) return _tonConnectUI;
    if (typeof window.TON_CONNECT_UI === 'undefined') {
        console.error('[ton-auth] TON_CONNECT_UI not loaded');
        return null;
    }
    _tonConnectUI = new window.TON_CONNECT_UI.TonConnectUI({
        manifestUrl: `${window.location.origin}/tonconnect-manifest.json`,
        // Inside a Telegram Mini App, return the user back INTO Telegram after a
        // wallet action instead of bouncing to an external browser. Only applies
        // in TMA mode; ignored in a normal browser. Set in telegram-webapp.js.
        ...(window.TWA_RETURN_URL
            ? { actionsConfiguration: { twaReturnUrl: window.TWA_RETURN_URL } }
            : {}),
        // 排除 bridge 已失效的錢包：SDK 啟動時會對每個錢包的 SSE bridge 建長輪詢，
        // bridge 死掉會在每個使用者瀏覽器 console 噴 ERR_NAME_NOT_RESOLVED。
        // - stower（STOWER Wallet）：bridge.stower.money 已 NXDOMAIN（域名失效）
        //   官方 registry（wallets-v2.json）仍列著但服務已停。
        // - nicegram / dewallet：2026-08-14 觀察 tc.nicegram.app 與
        //   bridge.dewallet.pro 亦已 NXDOMAIN（各重試 3 次＝每頁 9 個 error）。
        //   app_name 以官方 registry（wallets-v2.json）為準：
        //   nicegram 的 app_name 是 "nicegramWallet"（非 "nicegram"）。
        walletsListConfiguration: {
            excludeWallets: ['stower', 'nicegramWallet', 'dewallet'],
        },
    });
    window.tonConnectUI = _tonConnectUI; // 供 premium 付款共用
    // 在「建立單例的當下」就掛上 onStatusChange,確保不會漏接 TMA 從錢包返回
    // (頁面重載)後 SDK 處理回傳所觸發的、帶 ton_proof 的連線事件。
    _attachResumeLoginListener(_tonConnectUI);
    return _tonConnectUI;
}

// 供論壇子頁（未載 main.js）lazy 建立同一個單例
window.getTonConnectUI = getTonConnectUI;

// ---- 將驗證過的 TON 用戶寫入 AuthManager session ----
function _applyTonSession(syncResult, friendly) {
    const A = window.AuthManager;
    if (!A) return false;
    A.currentUser = {
        uid: syncResult.user.user_id,
        user_id: syncResult.user.user_id,
        username: syncResult.user.username,
        accessTokenExpiry: Date.now() + (A.TOKEN_EXPIRY_MS || 86400000),
        authMethod: syncResult.user.auth_method || 'ton_wallet',
        role: syncResult.user.role || 'user',
        membership_tier: syncResult.user.membership_tier || 'free',
        has_wallet: true,
        wallet_address: friendly,
    };
    A._saveUserSession();
    if (typeof A.markRecentLoginSuccess === 'function') A.markRecentLoginSuccess();
    if (typeof A.startTokenRefreshTimer === 'function') A.startTokenRefreshTimer();
    window.dispatchEvent(new Event('auth-success'));
    return true;
}

// ---- Telegram 原生登入（Mini App initData）----
// 在 Telegram Mini App 內,Telegram 已驗證使用者身分(initData),不需錢包簽章
// 即可登入。這是 Mini App 最可靠的登入方式:免 modal、免錢包、免重載。
function _applyTelegramSession(syncResult) {
    const A = window.AuthManager;
    if (!A || !syncResult || !syncResult.user) return;
    A.currentUser = {
        uid: syncResult.user.user_id,
        user_id: syncResult.user.user_id,
        username: syncResult.user.username,
        accessTokenExpiry: Date.now() + (A.TOKEN_EXPIRY_MS || 86400000),
        authMethod: syncResult.user.auth_method || 'telegram',
        role: syncResult.user.role || 'user',
        membership_tier: syncResult.user.membership_tier || 'free',
        has_wallet: syncResult.user.has_wallet === true,
        wallet_address: null,
    };
    A._saveUserSession();
    if (typeof A.markRecentLoginSuccess === 'function') A.markRecentLoginSuccess();
    if (typeof A.startTokenRefreshTimer === 'function') A.startTokenRefreshTimer();
    window.dispatchEvent(new Event('auth-success'));
}

async function handleTelegramLogin() {
    const WebApp = window.Telegram && window.Telegram.WebApp;
    const initData = WebApp && WebApp.initData;
    if (!initData) {
        return { success: false, reason: 'no-initdata' };
    }
    try {
        const res = await AppAPI.post('/api/user/telegram-login', { init_data: initData });
        if (res && res.success) {
            _applyTelegramSession(res);
            return { success: true, user: window.AuthManager.currentUser };
        }
        return { success: false, reason: (res && res.detail) || 'failed' };
    } catch (e) {
        return { success: false, reason: (e && e.message) || 'error' };
    }
}
window.handleTelegramLogin = handleTelegramLogin;

// ---- 登入狀態小工具 ----
function _isLoggedIn() {
    const A = window.AuthManager;
    return !!(A && typeof A.isLoggedIn === 'function' && A.isLoggedIn());
}

// 等待登入完成（由背景 onStatusChange 流程補完）。優先用 auth-success 事件，
// 逾時則回退檢查當下狀態。回傳是否已登入。
function _waitForLogin(ms) {
    if (_isLoggedIn()) return Promise.resolve(true);
    return new Promise((resolve) => {
        let done = false;
        const finish = (v) => {
            if (done) return;
            done = true;
            window.removeEventListener('auth-success', onOk);
            clearTimeout(timer);
            resolve(v);
        };
        const onOk = () => finish(true);
        window.addEventListener('auth-success', onOk);
        const timer = setTimeout(() => finish(_isLoggedIn()), ms);
    });
}

// ---- 統一登入收尾：拿到帶 ton_proof 的 wallet 後送後端驗證並建立 session ----
// 互動式(handleTonLogin)與背景還原(resume listener)兩條路共用此函式；用
// _loginInFlight 去重，避免同一次連線被兩條路重複送出（後端本身 idempotent，
// 重複也安全，但去重可免掉雙重 toast）。
let _loginInFlight = false;

// ton-auth.js is intentionally imported before auth.js.  A wallet SDK restore can
// emit ton_proof immediately, while AuthManager is still being evaluated.  Do not
// create a valid backend cookie session until the frontend session coordinator is
// ready, otherwise the proof is consumed but the UI remains a guest.
function _waitForAuthManager(ms = 5000) {
    if (window.AuthManager) return Promise.resolve(window.AuthManager);
    return new Promise((resolve) => {
        const startedAt = Date.now();
        const timer = setInterval(() => {
            if (window.AuthManager) {
                clearInterval(timer);
                resolve(window.AuthManager);
                return;
            }
            if (Date.now() - startedAt >= ms) {
                clearInterval(timer);
                resolve(null);
            }
        }, 25);
    });
}

async function _completeLoginFromWallet(w) {
    if (_isLoggedIn()) return { success: true, user: window.AuthManager.currentUser };
    const proofItem = w && w.connectItems && w.connectItems.tonProof;
    if (!proofItem || !('proof' in proofItem)) {
        return { success: false, reason: 'no-proof' };
    }
    if (_loginInFlight) {
        const ok = await _waitForLogin(8000);
        return { success: ok, user: window.AuthManager && window.AuthManager.currentUser };
    }
    _loginInFlight = true;
    try {
        const authManager = await _waitForAuthManager();
        if (!authManager) {
            return { success: false, reason: 'auth-not-ready' };
        }
        const account = w.account;
        const testnet = String(account.chain) === '-3';
        const friendly = rawToFriendly(account.address, testnet, false);
        const syncResult = await AppAPI.post('/api/user/ton-login', {
            address: friendly,
            raw_address: account.address,
            public_key: account.publicKey,
            network: testnet ? 'testnet' : 'mainnet',
            proof: proofItem.proof,
        });
        if (syncResult && syncResult.success) {
            if (!_applyTonSession(syncResult, friendly)) {
                return { success: false, reason: 'auth-not-ready' };
            }
            return { success: true, user: window.AuthManager.currentUser };
        }
        return { success: false, reason: (syncResult && syncResult.detail) || 'verify-failed' };
    } finally {
        _loginInFlight = false;
    }
}

// ---- 登入主流程 ----
async function handleTonLogin() {
    const ui = getTonConnectUI();
    if (!ui) {
        if (typeof showToast === 'function') showToast(window.I18n ? window.I18n.t('tonAuth.walletLoading') : 'Wallet loading, please try again', 'warning');
        return { success: false };
    }

    // 可能背景的 onStatusChange 流程剛從錢包返回(TMA 重載)補完登入。
    if (_isLoggedIn()) return { success: true, user: window.AuthManager.currentUser };

    // 已有連線：可能是剛從錢包返回、正帶著 ton_proof 等背景 listener 收尾，
    // 也可能是上一段舊 session 的純還原(無 proof)。先給背景流程一點時間完成
    // 登入,「不要」立刻 disconnect——否則會把剛返回、帶 proof 的連線斷掉,
    // 使用者就會被踢回錢包選單(這正是先前一直登不進去的迴圈)。
    if (ui.connected) {
        if (await _waitForLogin(3000)) {
            return { success: true, user: window.AuthManager.currentUser };
        }
        // 等不到 → 視為無 proof 的舊還原,斷線以便重新連線取得新的 ton_proof。
        try { await ui.disconnect(); } catch (e) { console.debug('[ton-auth] disconnect skipped', e); }
    }

    // 1. 取得後端 nonce 並設定 ton_proof 請求
    ui.setConnectRequestParameters({ state: 'loading' });
    let payload;
    try {
        const r = await fetch('/api/user/ton-proof-payload');
        payload = (await r.json()).payload;
    } catch (e) {
        ui.setConnectRequestParameters(null);
        throw new Error(window.I18n ? window.I18n.t('tonAuth.challengeFailed') : 'Failed to get login challenge');
    }
    ui.setConnectRequestParameters({ state: 'ready', value: { tonProof: payload } });

    // 2. 等待錢包連線 + 簽章
    const wallet = await new Promise((resolve, reject) => {
        let settled = false;

        const cleanup = () => {
            clearTimeout(timer);
            unsub();
            if (modalStateUnsub) modalStateUnsub();
        };

        const timer = setTimeout(() => {
            if (settled) return;
            settled = true;
            cleanup();
            reject(new Error(window.I18n ? window.I18n.t('tonAuth.connectionTimeout') : 'Connection timed out'));
        }, 120000);

        const unsub = ui.onStatusChange((w) => {
            if (w) {
                if (settled) return;
                settled = true;
                cleanup();
                resolve(w);
            }
        });

        let modalStateUnsub = null;
        if (ui.modal && typeof ui.modal.onStateChange === 'function') {
            modalStateUnsub = ui.modal.onStateChange((s) => {
                if (settled) return;
                if (s.status === 'closed') {
                    settled = true;
                    cleanup();
                    reject(new Error('cancel'));
                }
            });
        }

        ui.openModal().catch((e) => {
            if (settled) return;
            settled = true;
            cleanup();
            reject(e);
        });
    });

    // 3. 取出 ton_proof
    // SDK 不會自動關閉 modal，連線成功後必須明確呼叫 closeModal()
    // 否則 TonConnectUI modal 會蓋住後續的登入成功 UI
    try {
        ui.closeModal();
    } catch (e) {
        console.debug('[ton-auth] closeModal skipped', e);
    }
    const proofItem = wallet.connectItems && wallet.connectItems.tonProof;
    if (!proofItem || !('proof' in proofItem)) {
        throw new Error(window.I18n ? window.I18n.t('tonAuth.noTonProof') : 'Wallet did not provide ton_proof');
    }

    // 4. 送後端驗證（與背景 resume 流程共用同一收尾函式）
    const res = await _completeLoginFromWallet(wallet);
    if (!res.success) {
        throw new Error(res.reason || (window.I18n ? window.I18n.t('tonAuth.verificationFailed') : 'TON login verification failed'));
    }
    return { success: true, user: window.AuthManager.currentUser };
}
window.handleTonLogin = handleTonLogin;

// ---- 登入成功後的共用 UI（按鈕流程與「重載後接回」流程共用）----
let _lastLoginSuccessToastAt = 0;
function _onTonLoginSuccessUI() {
    const modal = document.getElementById('login-modal');
    if (modal) modal.classList.add('hidden');
    if (window.AppStore) AppStore.set('forceGuestLandingTab', false);
    if (window.AuthManager && typeof AuthManager._updateUI === 'function') {
        AuthManager._updateUI(true);
    }
    const now = Date.now();
    if (now - _lastLoginSuccessToastAt > 3000) {
        _lastLoginSuccessToastAt = now;
        if (typeof showToast === 'function')
            showToast(window.I18n ? window.I18n.t('tonAuth.loginSuccess') : '✅ Login successful!', 'success');
    }
}

// ---- 帶 loading UI 與防重複點擊的包裝（對應 index.html 按鈕）----
window.safeTonLogin = async function () {
    if (window[TON_LOGIN_FLAG]) return;
    const btn = document.getElementById('ton-login-btn');
    const original = btn ? btn.innerHTML : '';
    try {
        window[TON_LOGIN_FLAG] = true;
        if (btn) {
            btn.disabled = true;
            btn.classList.add('opacity-70', 'cursor-not-allowed');
            btn.innerHTML =
                '<svg class="animate-spin w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> ' + (window.I18n ? window.I18n.t('tonAuth.connectingShort') : 'Connecting...');
        }
        const res = await handleTonLogin();
        if (res && res.success) {
            _onTonLoginSuccessUI();
        }
    } catch (e) {
        console.error('[ton-auth] login failed', e);
        const msg = /cancel|closed|dismiss|abort|reject/i.test(e.message || '')
            ? (window.I18n ? window.I18n.t('tonAuth.loginCancelledShort') : 'Login cancelled')
            : (e.message || (window.I18n ? window.I18n.t('tonAuth.loginFailedShort') : 'TON login failed, please retry'));
        if (typeof showToast === 'function') showToast(msg, 'error');
    } finally {
        window[TON_LOGIN_FLAG] = false;
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('opacity-70', 'cursor-not-allowed');
            btn.innerHTML = original;
        }
    }
};

// ---- 顯示登入按鈕（TON 不需特定瀏覽器）----
(function showTonLoginButton() {
    // 訪客模式（2026-08-19 設計）：未登入不再自動彈全屏登入 modal——
    // 改由 chat 頂部 guest banner 引導。modal 只在三個入口出現：
    // 1) guest banner 的 Connect 按鈕 2) guest 升級卡 CTA
    // 3) 切換到受保護 tab 時（spa.js switchTab 守門）
    const show = () => {
        const stored = localStorage.getItem('ton_user');
        if (stored) return; // 已登入則不顯示（保留相容）
        // 訪客：不顯示 modal，顯示 banner（auth.js _updateUI 負責）
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', show, { once: true });
    } else {
        show();
    }
})();

// ---- 重載後接回登入（Telegram Mini App 關鍵修正）----
// TMA 連錢包後，錢包透過 twaReturnUrl 跳回會讓 Mini App「整個重新載入」，
// handleTonLogin 那條互動式 Promise 與其 onStatusChange 會隨頁面消失。重載後
// TonConnect 雖自動還原連線並帶回 ton_proof，但沒有任何監聽去完成後端登入，
// 使用者就卡在登入畫面。這裡在開機註冊一個全域監聽補完這一步。
let _resumeListenerAttached = false;
function _attachResumeLoginListener(ui) {
    if (!ui || _resumeListenerAttached) return;
    _resumeListenerAttached = true;
    ui.onStatusChange(async (w) => {
        const proofItem0 = w && w.connectItems && w.connectItems.tonProof;
        if (!w) return;
        if (_isLoggedIn()) return;
        // 只有帶 ton_proof 的「剛連線/剛返回」事件才能完成登入；純還原(無 proof)略過。
        if (!proofItem0 || !('proof' in proofItem0)) {
            return;
        }
        try {
            const res = await _completeLoginFromWallet(w);
            if (res.success) {
                _onTonLoginSuccessUI();
            } else if (res.reason !== 'no-proof' && typeof showToast === 'function') {
                showToast(res.reason || (window.I18n ? window.I18n.t('tonAuth.verificationFailed') : 'TON login verification failed'), 'error');
            }
        } catch (e) {
            console.error('[ton-auth] resume login failed', e);
            if (typeof showToast === 'function')
                showToast(window.I18n ? window.I18n.t('tonAuth.loginFailedShort') : 'TON login failed, please retry', 'error');
        }
    });
}

// ---- 開機初始化 TonConnect：還原先前已連線的錢包 ----
// TonConnectUI 在 new 的當下會自動還原 localStorage 中的錢包連線。
// 若不在啟動時建立單例，重整後 window.tonConnectUI 為 undefined，
// 會導致升級會員 / 論壇 TON 付款卡在「錢包未就緒」，直到使用者再按一次登入。
(function initTonConnectOnStartup() {
    let tries = 0;
    const tryInit = () => {
        if (typeof window.TON_CONNECT_UI !== 'undefined') {
            try {
                const ui = getTonConnectUI(); // 建立單例 + 自動還原連線（設定 window.tonConnectUI）
                _attachResumeLoginListener(ui);
            } catch (e) {
                console.debug('[ton-auth] startup init skipped', e);
            }
            return;
        }
        if (tries++ < 20) setTimeout(tryInit, 250); // 等 CDN script 載入（最多 ~5s）
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', tryInit, { once: true });
    } else {
        tryInit();
    }
})();

// ---- Telegram Mini App 自動登入 ----
// 在 Mini App 內,只要 Telegram 提供了 initData 且使用者尚未登入,就用 Telegram
// 身分自動登入——不開錢包、不彈 modal。這也讓「重載後被登出」能自我修復:任何
// 一次 AuthManager 判定未登入,都會立刻用 initData 重新登入。錢包只在付款時才連。
// 手動 Telegram 登入按鈕(自動登入失敗時的後備),含 loading 狀態。
window.safeTelegramLogin = async function () {
    const btn = document.getElementById('tg-login-btn');
    const original = btn ? btn.innerHTML : '';
    try {
        if (btn) {
            btn.disabled = true;
            btn.classList.add('opacity-70', 'cursor-not-allowed');
        }
        const res = await handleTelegramLogin();
        if (res && res.success) {
            _onTonLoginSuccessUI();
        } else if (typeof showToast === 'function') {
            showToast(
                window.I18n ? window.I18n.t('tonAuth.loginFailedShort') : 'Login failed, please retry',
                'error'
            );
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('opacity-70', 'cursor-not-allowed');
            btn.innerHTML = original;
        }
    }
};

// 在 Mini App 內顯示「用 Telegram 登入」按鈕(一般瀏覽器維持只有錢包登入)。
function _revealTelegramLoginButton() {
    const WebApp = window.Telegram && window.Telegram.WebApp;
    const inMiniApp = !!(WebApp && WebApp.platform && WebApp.platform !== 'unknown' && WebApp.initData);
    if (!inMiniApp) return;
    const btn = document.getElementById('tg-login-btn');
    if (btn) btn.style.display = '';
}

let _tgAutoLoginTried = false;
async function _tryTelegramAutoLogin(reason) {
    if (_isLoggedIn()) return;
    const WebApp = window.Telegram && window.Telegram.WebApp;
    const inMiniApp = !!(
        WebApp && WebApp.platform && WebApp.platform !== 'unknown' && WebApp.initData
    );
    if (!inMiniApp) return; // 一般瀏覽器 → 維持錢包登入
    if (window[TON_LOGIN_FLAG]) return; // 互動式錢包登入進行中,別插手
    const res = await handleTelegramLogin();
    if (res.success) {
        _onTonLoginSuccessUI();
    } else if (!_tgAutoLoginTried && res.reason && res.reason !== 'no-initdata') {
        _tgAutoLoginTried = true;
        if (typeof showToast === 'function') {
            showToast(
                window.I18n ? window.I18n.t('tonAuth.loginFailedShort') : 'Login failed, please retry',
                'error'
            );
        }
    }
}
// AuthManager init 完成後若仍未登入 → 試 Telegram 自動登入(含重載後被登出的自我修復)。
window.addEventListener('auth:initialized', (e) => {
    if (e && e.detail && e.detail.isLoggedIn) return;
    _tryTelegramAutoLogin('auth:initialized');
});
// 後備:若 auth:initialized 在監聽掛上前就觸發過,開機時也試一次。
(function bootTelegramAutoLogin() {
    const run = () => {
        _revealTelegramLoginButton();
        // 已有本地 session 就交給 AuthManager 還原;它若失敗登出會再觸發上面的事件。
        if (localStorage.getItem('ton_user')) return;
        _tryTelegramAutoLogin('boot');
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run, { once: true });
    } else {
        run();
    }
})();

// 向後相容：舊按鈕呼叫 safePiLogin() → 改走 TON Connect 登入
window.safePiLogin = window.safeTonLogin;

// 測試模式區塊（沿用）— 改用共用 getAppConfig()，避免首頁載入時重複 fetch /api/config
if (typeof AppAPI !== 'undefined' && AppAPI.getAppConfig) {
    AppAPI.getAppConfig()
        .then((cfg) => {
            if (cfg && cfg.test_mode) {
                const devArea = document.getElementById('dev-login-area');
                if (devArea) devArea.style.display = 'block';
            }
        })
        .catch(() => {});
}

export {};
