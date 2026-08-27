// ========================================
// chat-history.js - 對話歷史管理
// 職責：loadChatHistory、loadMoreHistory、滾動偵測
// 依賴：chat-state.js
// ========================================

// ── 對話歷史動態載入狀態 ──────────────────────────────────────────────────────
let _historyOldestTimestamp = null; // 目前可見訊息中最舊的時間戳
let _historyHasMore = false; // 是否還有更舊的訊息
let _historyLoading = false; // 防止重複載入
let _historySessionId = null; // 目前載入的 session

/**
 * 將單條歷史訊息渲染為 DOM 節點（不 append，只 create）。
 *
 * ⚠️ 必須與 live streaming（chat-state.js::appendMessage）用相同的 DOM 結構，
 * 否則 history 載入後排版會跑掉。共用 window.buildMessageRow() 保證一致。
 */
function _buildHistoryMsgEl(msg) {
    const role = msg.role === 'assistant' ? 'bot' : 'user';

    // 用與 live 同一個 builder（chat-row + chat-content-ai prose）
    const { row, content: div } = window.buildMessageRow(role);

    if (role === 'bot') {
        const savedState = AppStore.get('lastProcessOpenState');
        AppStore.set('lastProcessOpenState', false);
        div.innerHTML = renderStoredBotMessage(msg.content);
        AppStore.set('lastProcessOpenState', savedState);

        // Trustworthy AI HITL：歷史還原詐騙判定證據卡片（共用 renderResponseMetadata）
        if (msg.metadata && msg.metadata.scam_evidence && window.renderResponseMetadata) {
            div.insertAdjacentHTML('beforeend', window.renderResponseMetadata(msg.metadata));
        }
    } else {
        div.textContent = msg.content;
    }

    if (msg.timestamp) {
        const footer = document.createElement('div');
        footer.className = 'mt-2 text-[10px] text-textMuted/30 font-mono';
        const date = new Date(msg.timestamp + 'Z');
        footer.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        div.appendChild(footer);
    }
    return row;  // ⚠️ 注意：回傳 row（外層），不是 div（內層）
}

/** 載入更舊的訊息（向上捲動觸發）。 */
async function loadMoreHistory() {
    if (_historyLoading || !_historyHasMore || !_historyOldestTimestamp) return;
    _historyLoading = true;

    const container = document.getElementById('chat-messages');

    // 顯示頂部 loading 指示器
    const loader = document.createElement('div');
    loader.id = 'history-loader';
    loader.className = 'text-center text-xs text-textMuted/40 py-2';
    loader.textContent = window.I18n.t('chat.loadMore');
    container.prepend(loader);

    try {
        const url = `/api/chat/history?session_id=${encodeURIComponent(_historySessionId)}&before_timestamp=${encodeURIComponent(_historyOldestTimestamp)}`;
        const data = await AppAPI.get(url);

        loader.remove();

        if (data.history && data.history.length > 0) {
            // 記錄捲動位置，prepend 後還原（避免畫面跳動）
            const oldScrollHeight = container.scrollHeight;

            const frag = document.createDocumentFragment();
            data.history.forEach((msg) => frag.appendChild(_buildHistoryMsgEl(msg)));
            container.prepend(frag);
            createIconsIn(container);

            // 還原捲動位置
            container.scrollTop = container.scrollHeight - oldScrollHeight;

            // 更新狀態
            _historyOldestTimestamp = data.history[0].timestamp;
            _historyHasMore = data.has_more;
        } else {
            _historyHasMore = false;
        }
    } catch (e) {
        loader.remove();
        console.error('[history] loadMoreHistory error:', e);
        if (typeof showToast === 'function') showToast(window.I18n ? window.I18n.t('chat.loadMoreHistoryFailed') : 'Failed to load more history', 'error');
    } finally {
        _historyLoading = false;
    }
}

async function loadChatHistory(sessionId = 'default') {
    // 🔒 安全檢查：未登入時不載入聊天歷史
    const isLoggedIn = window.AuthManager?.isLoggedIn();
    if (!isLoggedIn) {
        showWelcomeScreen();
        return;
    }

    // 重置動態載入狀態
    _historyOldestTimestamp = null;
    _historyHasMore = false;
    _historyLoading = false;
    _historySessionId = sessionId;

    const container = document.getElementById('chat-messages');

    // 先給載入中的回饋再發請求。這支 API 實測要數秒，若等回應才清畫面，
    // 使用者點了新對話卻還盯著上一段對話的內容，會以為沒切成功。
    container.innerHTML = `
        <div class="flex items-center justify-center py-16 text-textMuted/60">
            <i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i>
        </div>`;
    createIconsIn(container);

    try {
        const data = await AppAPI.get(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}`);

        // 期間可能又切到別的對話，這次的回應已經過期就別蓋掉畫面
        if (_historySessionId !== sessionId) {
            return;
        }

        container.innerHTML = '';

        if (data.history && data.history.length > 0) {
            data.history.forEach((msg) => container.appendChild(_buildHistoryMsgEl(msg)));
            createIconsIn(container);

            // 更新動態載入狀態
            _historyOldestTimestamp = data.history[0].timestamp;
            _historyHasMore = data.has_more;

            // 初始捲到底
            setTimeout(() => {
                container.scrollTop = container.scrollHeight;
            }, 100);

            // 掛載捲動偵測（只掛一次）
            _attachHistoryScrollListener(container);
        } else {
            // Welcome message for empty session
            container.innerHTML = `
                <div class="bot-message opacity-0 animate-fade-in-up" style="animation-delay: 0.1s; animation-fill-mode: forwards;">
                    <div class="flex flex-col items-center justify-center mb-8">
                        <h1 class="font-serif text-3xl md:text-4xl leading-tight text-center">
                            <span class="text-secondary">Welcome to</span><br>
                            <span class="text-transparent bg-clip-text bg-gradient-to-r from-primary to-accent">CryptoMind</span>
                        </h1>
                    </div>
                    <p class="text-textMuted text-lg font-light leading-relaxed text-center">
                        AI-powered crypto analysis. Start a new conversation.
                    </p>
                    <div class="flex flex-wrap gap-3 mt-8 justify-center">
                         <button data-click="quickAsk" data-click-arg="Analyze%20BTC%20trend" class="px-5 py-2.5 rounded-full bg-surface hover:bg-surfaceHighlight border border-borderSubtle text-sm text-textMuted hover:text-primary transition shadow-sm">
                            Bitcoin Trend
                        </button>
                    </div>
                </div>`;
            createIconsIn(container);
        }
    } catch (e) {
        console.error('Failed to load history:', e);
        // 別把載入中的轉圈留在畫面上
        if (_historySessionId === sessionId) {
            container.innerHTML = `
                <div class="text-center text-sm text-textMuted/70 py-16">
                    ${window.I18n ? window.I18n.t('chat.historyLoadFailed') : 'Could not load this conversation. Please try again.'}
                </div>`;
        }
    }
}

// 暴露到全域供其他模組使用
window.loadChatHistory = loadChatHistory;
window.loadMoreHistory = loadMoreHistory;

/** 捲動偵測：接近頂部 80px 時觸發 loadMoreHistory。只掛一個 listener。 */
let _scrollListenerAttached = false;
function _attachHistoryScrollListener(container) {
    if (_scrollListenerAttached) return;
    _scrollListenerAttached = true;
    container.addEventListener(
        'scroll',
        () => {
            if (container.scrollTop < 80 && _historyHasMore && !_historyLoading) {
                loadMoreHistory();
            }
        },
        { passive: true }
    );
}

export { loadChatHistory, loadMoreHistory };
