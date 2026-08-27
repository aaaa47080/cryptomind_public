// click-delegator.js — CSP-compliant delegated event handler
// Replaces all inline click attributes with data-click + delegated listener.
// This allows strict CSP (no 'unsafe-inline') while preserving identical behavior.

function decodeDataValue(value) {
    if (value == null) return value;
    try {
        return decodeURIComponent(value);
    } catch (_error) {
        return value;
    }
}

function getDelegatedArgs(el, event) {
    var encodedArgs = el.getAttribute('data-click-args');
    var args = [];
    if (encodedArgs) {
        try {
            args = JSON.parse(decodeDataValue(encodedArgs));
        } catch (_error) {
            return null;
        }
        if (!Array.isArray(args)) return null;
    } else if (el.hasAttribute('data-click-arg')) {
        args = [decodeDataValue(el.getAttribute('data-click-arg'))];
    }
    if (el.hasAttribute('data-click-event-first')) args.unshift(event);
    if (el.hasAttribute('data-click-value')) args.push(el.value);
    if (el.hasAttribute('data-click-element')) args.push(el);
    if (el.hasAttribute('data-click-event')) args.push(event);
    return args;
}

function invokeDelegatedObjectAction(action, el, event) {
    var allowedRoots = new Set([
        'AdminPanel', 'AdminStatsManager', 'AStockTab', 'CommodityTab', 'CryptoTab',
        'DiscoverTab', 'StudioTab', 'FeatureMenu', 'ForexTab', 'FriendsUI', 'GlobalNav', 'HKStockTab',
        'AIStudioTab', 'INStockTab', 'JPStockTab', 'KRStockTab', 'SocialHub',
        'TWStockTab', 'TelegramLinkApp', 'USStockTab', 'WalletApp', 'WalletMonitorTab',
        'Journal',
    ]);
    var parts = action.split('.');
    if (parts.length < 2 || !allowedRoots.has(parts[0])) return false;
    if (!parts.every(function (part) { return /^[A-Za-z_$][\w$]*$/.test(part); })) return false;

    var owner = window;
    for (var i = 0; i < parts.length - 1; i += 1) {
        owner = owner && owner[parts[i]];
    }
    var fn = owner && owner[parts[parts.length - 1]];
    if (typeof fn !== 'function') return true;

    var args = getDelegatedArgs(el, event);
    if (args === null) return true;
    fn.apply(owner, args);
    var afterMethod = el.getAttribute('data-click-after');
    if (afterMethod && /^[A-Za-z_$][\w$]*$/.test(afterMethod)) {
        var afterFn = owner && owner[afterMethod];
        if (typeof afterFn === 'function') afterFn.call(owner);
    }
    return true;
}

function invokeDelegatedGlobalAction(action, el, event) {
    var allowedActions = new Set([
        'applyGlobalFilter', 'cancelToolPreferences', 'closeAlertModal', 'closeChart',
        'closeFeedbackModal', 'closeFundingHistory', 'closeLegalModal', 'closeToolSettingsModal',
        'confirmScamVerdict', 'copyScamTrackerText', 'createNewChat', 'deleteSelectedSessions',
        'deleteSession', 'deleteToolKey', 'deleteUserAlert', 'enterEditMode', 'executePlan',
        'exitEditMode', 'fetchPulseForSymbol', 'fetchSymbols', 'handleLogout',
        'handleUpgradeToPremium', 'initToolSettings', 'llmActivateProvider', 'llmUnbindProvider',
        'multiConsentAll', 'multiConsentSubmit', 'multiConsentToggle',
        'openFeedbackModal', 'openGlobalFilter', 'openToolSettingsModal', 'quickAsk',
        'continueAsGuest', 'safeTelegramLogin', 'saveAllToolPreferences', 'saveDisplayName', 'saveLLMKey',
        'saveToolKey', 'sendMessage', 'showFundingHistory', 'showNewsList',
        'smoothNavigate', 'submitAlert', 'submitFeedbackMessage', 'submitHITLAnswer',
        'submitConsent', 'submitPreResearch', 'submitSkillConsent', 'submitMemoryConsent',
        'submitJournalConsent', 'toggleJournalEdit', 'testLLMKey', 'testToolKey',
        'toggleAutoRefresh', 'toggleEditDisplayName', 'toggleOptions', 'togglePlanCustomize',
        'toggleProcessState', 'toggleSelectAll', 'toggleSidebar', 'toggleStarredSection',
        'toggleStarSession', 'toggleToolCategory', 'triggerDeepAnalysis', 'voteOnReport',
    ]);
    if (!allowedActions.has(action)) return false;
    var fn = window[action];
    if (typeof fn !== 'function') return true;
    var args = getDelegatedArgs(el, event);
    if (args !== null) fn.apply(window, args);
    return true;
}

/* 手機觸控第一次點擊就生效，不等 click。

   行動裝置上原生 click 有個先天失準：手指碰到按鈕的瞬間，若焦點還在輸入框
   上（虛擬鍬盤開著），系統會先派發 blur 把鍵盤收起 —— 鍵盤收起造成 viewport
   高度劇變，固定定位的輸入框連同按鈕往下掉數百像素，等 click 真正派發時
   做 hit-test 已經落在手指觸碰的舊位置之外，於是 click 落空或不派發。
   表現成「第一次點只讓鍵盤消失，要再點一次才送出」。

   解法：觸控（pointerType === 'touch'）時在 pointerdown 階段就立即派發動作，
   並 preventDefault 阻止瀏覽器把焦點從輸入框轉給按鈕（這正是收鍵盤連鎖的
   第一張骨牌）。滑鼠 / 手寫筆維持原本 click 行為，桌機體感不變。

   派發過的元素蓋上 data-click-fired，隨後的原生 click 事件看到旗標會跳過、
   並清掉旗標，避免動作被觸發兩次。 */
document.addEventListener('pointerdown', function (e) {
    // 只處理觸控；滑鼠與手寫筆走原本的 click 路徑，桌機行為不變
    if (e.pointerType && e.pointerType !== 'touch') return;
    // 按右鍵 / 中鍵不處理
    if (e.button !== 0) return;

    var el = e.target && e.target.closest ? e.target.closest('[data-click]') : null;
    if (!el) return;

    // 阻止瀏覽器把焦點從輸入框轉給按鈕 —— 這會啟動「blur → 收鍵盤 → viewport
    // 劇變 → click 失準」的連鎖。preventDefault 在 pointerdown 階段對焦點轉移
    // 有效（規範明訂）；不可在 click 階段才做，那時焦點已轉、鍵盤已收。
    e.preventDefault();

    // 蓋章：隨後到的原生 click 看到旗標就跳過。用 setTimeout 清除是為了只擋
    // 「這一次互動」產生的 click，下次點擊不受影響（DOM 上的 dataset 不會自動清）。
    // Bug 1 修正（2026-08-21 DANNY 回報「面板快速彈出又收回」）：
    // 原本 500ms 不夠——觸控的 pointerup→原生 click 間隔可到 ~400ms，
    // 但面板在 pointerdown 合成 click 時就打開了，原生 click 落在面板
    // 「外部」→ 被 click-outside 偵測器關掉。改 700ms 確保涵蓋。
    el.dataset.clickFired = '1';
    setTimeout(function () { delete el.dataset.clickFired; }, 700);

    // Bug 1 加強：全域 flag 讓 click-outside 偵測器在「合成 click 剛觸發面板打開」
    // 的短時間內忽略所有 click——面板剛打開時的 pointerup click 是同一個觸控
    // 手勢的一部分，不是「點外部」。面板開啟後的新觸控（~700ms 後）不受影響。
    window.__suppressClickOutside = Date.now() + 700;

    // Bug 2（2026-08-22 DANNY 回報「點一下放手立刻縮回去」）：面板在
    // pointerdown 打開後，放手原生 click 的 hit-test 落點可能已經變了——
    // 例如側欄抽屜：漢堡在 header z-40，開抽屜後 z-55 的遮罩蓋過它，
    // click 落在遮罩的 data-click=toggleSidebar → 抽屜立刻關掉。
    // per-element 的 clickFired 印章只攔「同一元素」，攔不到跨元素落點。
    // 手勢級吞點：本手勢隨後的原生 click 無論落在哪個元素，一律不委派。
    window.__touchGestureClickUntil = Date.now() + 700;

    // 合成一個 click 派發給元素本身，讓它冒泡到 document 的 click 委派 ——
    // 等於「提前在 pointerdown 階段把 click 跑掉」。合成 event 不會觸發瀏覽器
    // 的焦點/選取預設行為，所以上面的 preventDefault 仍然有效。
    // 旗標 _fromPointerdown 讓 click handler 識別「這是 pointerdown 提前派發的」，
    // 直接執行而不檢查 clickFired（否則會被自己設的旗標擋掉）。
    var synthetic = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        composed: true,
    });
    synthetic._fromPointerdown = true;
    el.dispatchEvent(synthetic);
}, true);

document.addEventListener('click', function (e) {
    // 手勢級吞點（Bug 2）：觸控 pointerdown 已合成派發過動作後，同一手勢的
    // 原生 click 無論 hit-test 落點在哪（原按鈕／剛彈出的遮罩／popover 項目）
    // 都不再委派——否則「開抽屜→click 落遮罩→立刻關」。
    // 注意：不能在非吞北路徑重置旗標——pointerdown 的合成 click（_fromPointerdown）
    // 會先走這裡，重置會把剛設的 700ms 窗清掉（等於沒防）。一律靠時間窗過期。
    if (
        !e._fromPointerdown &&
        window.__touchGestureClickUntil &&
        Date.now() < window.__touchGestureClickUntil
    ) {
        return;
    }

    var el = e.target.closest('[data-click]');
    if (!el) return;

    // pointerdown 已派發過的「原生 click」跳過（避免雙重觸發）。
    // 合成 click（_fromPointerdown=true）不受此限，直接執行。
    if (!e._fromPointerdown && el.dataset.clickFired === '1') {
        return;
    }

    var action = el.getAttribute('data-click');
    var arg = el.getAttribute('data-click-arg');

    if (el.hasAttribute('data-click-stop')) e.stopPropagation();
    if (el.hasAttribute('data-click-prevent')) e.preventDefault();

    // Simple no-arg functions
    var noArgFns = {
        'toggleSidebar': typeof toggleSidebar === 'function' ? toggleSidebar : null,
        'createNewChat': typeof createNewChat === 'function' ? createNewChat : null,
        'toggleOptions': typeof toggleOptions === 'function' ? toggleOptions : null,
        'sendMessage': typeof sendMessage === 'function' ? sendMessage : null,
        'closeChart': typeof closeChart === 'function' ? closeChart : null,
        'toggleAutoRefresh': typeof toggleAutoRefresh === 'function' ? toggleAutoRefresh : null,
        'closeAlertModal': typeof closeAlertModal === 'function' ? closeAlertModal : null,
        'closeFeedbackModal': typeof closeFeedbackModal === 'function' ? closeFeedbackModal : null,
        'closeLegalModal': typeof closeLegalModal === 'function' ? closeLegalModal : null,
        'closeToolSettingsModal': typeof closeToolSettingsModal === 'function' ? closeToolSettingsModal : null,
        'submitAlert': typeof submitAlert === 'function' ? submitAlert : null,
        'submitFeedbackMessage': typeof submitFeedbackMessage === 'function' ? submitFeedbackMessage : null,
        'applyGlobalFilter': typeof applyGlobalFilter === 'function' ? applyGlobalFilter : null,
        'safeTonLogin': typeof safeTonLogin === 'function' ? safeTonLogin : null,
        'safeTelegramLogin': typeof safeTelegramLogin === 'function' ? safeTelegramLogin : null,
        'saveAllToolPreferences': typeof saveAllToolPreferences === 'function' ? saveAllToolPreferences : null,
        'cancelToolPreferences': typeof cancelToolPreferences === 'function' ? cancelToolPreferences : null,
        'openFeedbackModal': typeof openFeedbackModal === 'function' ? openFeedbackModal : null,
        // Settings tab (migrated from inline onclick — blocked by strict prod CSP)
        'handleLogout': typeof handleLogout === 'function' ? handleLogout : null,
        'saveLLMKey': typeof saveLLMKey === 'function' ? saveLLMKey : null,
        'saveDisplayName': typeof saveDisplayName === 'function' ? saveDisplayName : null,
        'toggleEditDisplayName': typeof toggleEditDisplayName === 'function' ? toggleEditDisplayName : null,
        'testLLMKey': typeof testLLMKey === 'function' ? testLLMKey : null,
        'openToolSettingsModal': typeof openToolSettingsModal === 'function' ? openToolSettingsModal : null,
        'handleUpgradeToPremium': typeof handleUpgradeToPremium === 'function' ? handleUpgradeToPremium : null,
        'initToolSettings': typeof initToolSettings === 'function' ? initToolSettings : null,
        'closeFundingHistory': typeof closeFundingHistory === 'function' ? closeFundingHistory : null,
        'toggleSelectAll': typeof toggleSelectAll === 'function' ? toggleSelectAll : null,
        'exitEditMode': typeof exitEditMode === 'function' ? exitEditMode : null,
        'enterEditMode': typeof enterEditMode === 'function' ? enterEditMode : null,
        'submitPreResearch': typeof submitPreResearch === 'function' ? submitPreResearch : null,
        'openGlobalFilter': typeof openGlobalFilter === 'function' ? openGlobalFilter : null,
        'togglePlanCustomize': typeof togglePlanCustomize === 'function' ? togglePlanCustomize : null,
    };

    // Switch tab
    if (action === 'switchTab') { if (typeof switchTab === 'function') switchTab(arg); return; }

    // Legal pages
    if (action === 'showLegalPage') { if (typeof showLegalPage === 'function') showLegalPage(arg); return; }

    // Chart interval
    if (action === 'changeChartInterval') { if (typeof changeChartInterval === 'function') changeChartInterval(arg); return; }

    // TW/US stock chart
    if (action === 'twChangeChartInterval') { if (window.TWStockTab) window.TWStockTab.changeChartInterval(arg); return; }
    if (action === 'usChangeChartInterval') { if (window.USStockTab) window.USStockTab.changeChartInterval(arg); return; }
    if (action === 'twCloseChart') { if (window.TWStockTab) window.TWStockTab.closeTwChart(); return; }
    if (action === 'usCloseChart') { if (window.USStockTab) window.USStockTab.closeChart(); return; }

    // Nav toggle
    if (action === 'toggleNav') { if (window.GlobalNav) window.GlobalNav.toggleCollapse(); return; }

    // Wallet
    if (action === 'walletLoad') { if (window.WalletApp) window.WalletApp.loadData(); return; }

    // Mock login
    if (action === 'mockLogin') {
        if (window.AuthManager) AuthManager.loginAsMockUser().then(function (r) { if (r.success) window.location.reload(); });
        return;
    }

    // Existing add-stock controls pass an input element id rather than a literal value.
    if (el.hasAttribute('data-click-input')) {
        var input = document.getElementById(el.getAttribute('data-click-input'));
        if (input) {
            el.setAttribute('data-click-arg', encodeURIComponent(input.value));
        }
    }

    // Forum
    if (action === 'forumCloseReport') { if (window.ForumApp) window.ForumApp.closeReportModal(); return; }
    if (action === 'forumSubmitReport') { if (window.ForumApp) window.ForumApp.submitReport(); return; }

    // HITL submit
    if (action === 'submitHITL') {
        if (typeof window.submitHITLAnswer === 'function') {
            var input = document.getElementById('hitl-custom-input');
            if (input) window.submitHITLAnswer(input.value);
        }
        return;
    }


    // Forum multi-page handlers
    if (action === 'safeTonLogin') { if (typeof safeTonLogin === 'function') safeTonLogin(); return; }
    if (action === 'toggleScamLanguage') { if (typeof toggleScamLanguage === 'function') toggleScamLanguage(); return; }
    if (action === 'handleProfileBack') { if (typeof handleProfileBack === 'function') handleProfileBack(); return; }
    if (action === 'handleRemoveFriend') { if (typeof handleRemoveFriend === 'function') handleRemoveFriend(); return; }
    if (action === 'handleCancelRequest') { if (typeof handleCancelRequest === 'function') handleCancelRequest(); return; }
    if (action === 'handleAcceptRequest') { if (typeof handleAcceptRequest === 'function') handleAcceptRequest(); return; }
    if (action === 'handleRejectRequest') { if (typeof handleRejectRequest === 'function') handleRejectRequest(); return; }
    if (action === 'handleUnblock') { if (typeof handleUnblock === 'function') handleUnblock(); return; }
    if (action === 'handleAddFriend') { if (typeof handleAddFriend === 'function') handleAddFriend(); return; }
    if (action === 'msgToggleSearch') { if (window.MessagesPage) window.MessagesPage.toggleSearch(); return; }
    if (action === 'switchTabReport') { if (typeof switchTab === 'function') switchTab('report'); return; }

    // Close modal by ID (generic)
    if (action === 'closeModal') {
        if (arg) { var m = document.getElementById(arg); if (m) m.classList.add('hidden'); }
        return;
    }

    // Home / language
    if (action === 'goHome') { window.location.href = '/static/index.html'; return; }
    if (action === 'toggleLanguage') { if (typeof toggleLanguage === 'function') toggleLanguage(); return; }

    // Settings tab (migrated from inline onclick — blocked by strict prod CSP)
    if (action === 'handleDevSwitchUser') { if (typeof handleDevSwitchUser === 'function') handleDevSwitchUser(arg); return; }
    if (action === 'handleSwitchTestTier') { if (typeof handleSwitchTestTier === 'function') handleSwitchTestTier(arg); return; }
    if (action === 'featureMenuOpen') {
        if (window.FeatureMenu) {
            // open() 是 async（動態載入 tab-safety）；不 await 但要 catch，
            // 避免 import 失敗時 Promise rejection 被靜默吞掉（點了無反應）。
            const p = window.FeatureMenu.open();
            if (p && typeof p.catch === 'function') {
                p.catch((e) => console.error('[FeatureMenu] open failed:', e));
            }
        }
        return;
    }

    // FriendsUI 好友操作按鈕（動態模板）：data-click="FriendsUI.handleX" + data-click-arg="<encoded userId>"
    var fuMatch = action.match(/^FriendsUI\.(\w+)$/);
    if (fuMatch) {
        e.stopPropagation();
        e.preventDefault();
        if (window.FriendsUI && typeof FriendsUI[fuMatch[1]] === 'function') FriendsUI[fuMatch[1]](arg);
        return;
    }

    // 好友清單開聊天 / 返回標記（動態模板）
    if (action === 'friendsOpenChat') {
        e.stopPropagation();
        if (window.FriendsUI) FriendsUI.openChat(el.getAttribute('data-user-id'), el.getAttribute('data-username'));
        return;
    }
    if (action === 'setReturnTabFriends') { sessionStorage.setItem('returnToTab', 'friends'); return; }

    if (action === 'removeElement') { el.remove(); return; }
    if (action === 'removeClosest') {
        var closest = el.closest(arg);
        if (closest) closest.remove();
        return;
    }
    if (action === 'removeById') {
        var removable = document.getElementById(arg);
        if (removable) removable.remove();
        return;
    }
    if (action === 'reloadPage') { window.location.reload(); return; }
    if (action === 'navigateTo') { window.location.href = decodeDataValue(arg); return; }
    if (action === 'stopPropagation') { e.stopPropagation(); return; }

    if (action === 'fillChatExample') {
        var chatInput = document.getElementById('user-input');
        if (chatInput) {
            chatInput.value = window.I18n ? window.I18n.t(arg) : el.getAttribute('data-fallback') || '';
            chatInput.focus();
        }
        return;
    }

    if (action === 'copyElementText') {
        var source = document.getElementById(arg);
        if (source && navigator.clipboard) navigator.clipboard.writeText(source.textContent || '');
        return;
    }

    if (action === 'copyClipboardWithToast') {
        var clipboardValue = decodeDataValue(el.getAttribute('data-clipboard')) || '';
        if (navigator.clipboard) navigator.clipboard.writeText(clipboardValue);
        var copiedText = window.I18n ? window.I18n.t('common.copied') : 'Copied!';
        if (typeof window.showToast === 'function') {
            window.showToast(copiedText, 'success');
        }
        return;
    }

    if (action === 'openAlert') {
        var alertArgs = getDelegatedArgs(el, e);
        if (typeof openAlertModal === 'function' && alertArgs) openAlertModal.apply(window, alertArgs);
        return;
    }

    if (action === 'refreshScreenerForce') {
        if (typeof window.refreshScreener === 'function') window.refreshScreener(true, true);
        return;
    }

    if (action === 'pulseQuickAsk') {
        if (typeof switchTab === 'function') switchTab('chat');
        if (typeof quickAsk === 'function') quickAsk(decodeDataValue(arg));
        return;
    }

    if (action === 'clearCacheAndInvoke') {
        var cacheKey = decodeDataValue(el.getAttribute('data-cache-key'));
        if (window.AppCache && cacheKey) AppCache.clear(cacheKey);
        var targetAction = el.getAttribute('data-target-action');
        if (targetAction) invokeDelegatedObjectAction(targetAction, el, e);
        return;
    }

    if (action === 'marketPulseRetry') {
        var targetInput = document.getElementById(el.getAttribute('data-input-id'));
        var symbol = decodeDataValue(el.getAttribute('data-symbol'));
        var retryAction = el.getAttribute('data-target-action');
        if (targetInput) targetInput.value = symbol;
        if (window.AppCache) AppCache.clear(el.getAttribute('data-cache-prefix') + symbol);
        if (retryAction) invokeDelegatedObjectAction(retryAction, el, e);
        return;
    }

    if (invokeDelegatedObjectAction(action, el, e)) return;
    if (invokeDelegatedGlobalAction(action, el, e)) return;

    // SocialHub（好友分頁桌面版聊天，動態模板 — migrated from inline onclick）
    if (action === 'socialSwitchSubTab') { if (window.SocialHub) SocialHub.switchSubTab(arg || 'friends'); return; }
    if (action === 'socialOpenConversation') {
        if (window.SocialHub) SocialHub.openConversation(el.getAttribute('data-user-id'), el.getAttribute('data-username'));
        return;
    }
    if (action === 'socialDeleteConversation') {
        e.stopPropagation();
        if (window.SocialHub) SocialHub.deleteConversation(Number(el.getAttribute('data-conv-id')), el);
        return;
    }
    if (action === 'socialRecallMessage') {
        e.stopPropagation();
        if (window.SocialHub) SocialHub.recallMessage(Number(el.getAttribute('data-msg-id')), el);
        return;
    }
    if (action === 'socialHideMessage') {
        e.stopPropagation();
        if (window.SocialHub) SocialHub.hideMessage(Number(el.getAttribute('data-msg-id')), el);
        return;
    }

    // Simple no-arg dispatch
    if (noArgFns[action]) { noArgFns[action](); return; }
});

// ══ Delegated non-click events ═══════════════════════════════════════════
// submit / keydown / input / change / blur 的 inline 版本同樣被 prod 嚴格 CSP
// 擋掉，且上面的 click 委派管不到它們。與 data-click 相同精神：HTML 標
// data-* 屬性，事件在 document 層級統一分發（動態注入的元件模板也適用）。

// Enter 送出（單行輸入框）：data-enter="Obj.method"（帶 input value）或特例
// SocialHub 聊天輸入框需要完整 keydown 事件（自行處理 Shift+Enter 換行）：data-keydown
document.addEventListener('keydown', function (e) {
    var kd = e.target && e.target.closest ? e.target.closest('[data-keydown]') : null;
    if (kd) {
        if (kd.getAttribute('data-keydown') === 'socialInputKeydown' && window.SocialHub) {
            SocialHub.handleInputKeydown(e);
        }
        return;
    }

    if (e.key !== 'Enter' || e.isComposing) return;
    var el = e.target && e.target.closest ? e.target.closest('[data-enter]') : null;
    if (!el) return;
    e.preventDefault();
    var action = el.getAttribute('data-enter');

    if (action === 'submitHITL') { if (typeof window.submitHITLAnswer === 'function') window.submitHITLAnswer(el.value); return; }

    // 通用 "物件.方法" 形式（HKStockTab.addStock、JPStockTab.handleSearch ...），帶 input value
    var m = action.match(/^(\w+)\.(\w+)$/);
    if (m) {
        var obj = window[m[1]];
        if (obj && typeof obj[m[2]] === 'function') obj[m[2]](el.value);
        return;
    }
});

// 表單送出：data-submit="<action>"
document.addEventListener('submit', function (e) {
    var form = e.target && e.target.closest ? e.target.closest('[data-submit]') : null;
    if (!form) return;
    var action = form.getAttribute('data-submit');
    if (action === 'socialSendMessage') {
        e.preventDefault();
        if (window.SocialHub) SocialHub.sendMessage(e);
        return;
    }
});

// 輸入事件：data-uppercase（自動轉大寫）/ data-input-action="<action>"
document.addEventListener('input', function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
    var filter = el.getAttribute('data-input-filter');
    if (filter === 'alphanumeric') el.value = el.value.replace(/[^0-9A-Za-z]/g, '');
    if (filter === 'ticker') el.value = el.value.replace(/[^A-Za-z.^]/g, '');
    if (el.hasAttribute('data-uppercase')) el.value = el.value.toUpperCase();
    var action = el.getAttribute('data-input-action');
    if (!action) return;
    if (action === 'systemPrompt') { if (typeof onSystemPromptInput === 'function') onSystemPromptInput(el); return; }
    if (action === 'renderSymbolList') {
        if (typeof renderSymbolList === 'function' && typeof allMarketSymbols !== 'undefined') renderSymbolList(allMarketSymbols);
        return;
    }
    if (action === 'friendSearch') { if (typeof handleFriendSearch === 'function') handleFriendSearch(el.value); return; }
    if (action === 'socialAutoResize') {
        if (window.SocialHub) { SocialHub.autoResizeInput(el); SocialHub.updateCharCount(); }
        return;
    }
});

// 下拉/日期變更：data-change-action="<action>"
document.addEventListener('change', function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
    var action = el.getAttribute('data-change-action');
    if (!action) return;
    if (action === 'walletApplyFilters') { if (window.WalletApp) WalletApp.applyFilters(); return; }
    if (action === 'walletTimeFilter') { if (window.WalletApp) WalletApp.handleTimeFilterChange(el); return; }
    if (action === 'switchFilterExchange') { if (typeof switchFilterExchange === 'function') switchFilterExchange(el.value); return; }
    if (action === 'llmProviderChange') {
        if (typeof updateLLMKeyInput === 'function') updateLLMKeyInput();
        if (typeof updateAvailableModels === 'function') updateAvailableModels();
        return;
    }
    if (action === 'toolPreference') {
        if (typeof toggleToolPreference === 'function') {
            toggleToolPreference(decodeDataValue(el.getAttribute('data-tool-id')), el.checked, el);
        }
        return;
    }
    if (action === 'adminForumStatus') {
        if (window.AdminPanel && AdminPanel.ForumManager) {
            AdminPanel.ForumManager.filterByStatus(el.value);
        }
        return;
    }
});

// blur 不冒泡，需用 capture 階段委派：data-blur-action="<action>"
document.addEventListener('blur', function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
    var action = el.getAttribute('data-blur-action');
    if (!action) return;
    if (action === 'systemPromptBlur') { if (typeof onSystemPromptBlur === 'function') onSystemPromptBlur(el); return; }
}, true);
