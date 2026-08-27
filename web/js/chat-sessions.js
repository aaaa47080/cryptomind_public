// ========================================
// chat-sessions.js - Session 管理
// 職責：Session 列表載入、創建、刪除、收藏、編輯模式
// 依賴：chat-state.js
// ========================================


// ========================================
// Session Management
// ========================================

// 用於記住收藏區的展開狀態
let starredSectionOpen = true;

/* 手機版切換對話後把側邊欄收起來。
   一定要走 chat-state.js 的 closeSidebar()，它會連 #sidebar-backdrop 一起收；
   只加 -translate-x-full 會讓滿版遮罩留在畫面上蓋住聊天記錄。 */
function closeSidebarOnMobile() {
    if (window.innerWidth >= 768) {
        return;
    }
    const sidebar = document.getElementById('chat-sidebar');
    if (!sidebar || sidebar.classList.contains('-translate-x-full')) {
        return;
    }
    if (typeof window.closeSidebar === 'function') {
        window.closeSidebar();
    }
}

async function loadSessions() {
    // 🔒 安全檢查：未登入時不載入 session 列表
    const isLoggedIn = window.AuthManager?.isLoggedIn();
    if (!isLoggedIn) {
        const list = document.getElementById('chat-session-list');
        if (list) {
            list.innerHTML =
                `<div class="text-center text-xs text-textMuted/40 py-4">${window.I18n?.t('chatSessions.loginFirst') || 'Please login first'}</div>`;
        }
        return;
    }

    try {
        // 使用 AuthManager 獲取用戶 ID
        const isLoggedIn = window.AuthManager?.isLoggedIn();
        if (!isLoggedIn) return; // Should be handled by top check, but safe to keep

        const userId = AuthManager.currentUser.user_id || AuthManager.currentUser.uid;

        if (!userId) {
            list.innerHTML =
                `<div class="text-center text-xs text-textMuted/40 py-4">${window.I18n?.t('chatSessions.loginFirst') || 'Please login first'}</div>`;
            return [];
        }

        const data = await AppAPI.get(`/api/chat/sessions?user_id=${encodeURIComponent(userId)}`);
        const list = document.getElementById('chat-session-list');
        if (!list) {
            // 非 SPA 頁（如論壇多頁）沒有側欄清單容器——資料照返回、渲染跳過
            console.warn('[chat-sessions] #chat-session-list not found — skip sidebar render');
            return data.sessions || [];
        }
        list.innerHTML = '';

        if (data.sessions && data.sessions.length > 0) {
            // 分離收藏和普通對話
            const starredSessions = data.sessions.filter((s) => s.is_pinned);
            const regularSessions = data.sessions.filter((s) => !s.is_pinned);
            const allSessions = data.sessions;

            // 編輯模式工具栏
            const toolbar = document.createElement('div');
            toolbar.className = 'edit-toolbar flex items-center gap-2 px-3 py-2 mb-2';

            if (window.isEditMode) {
                const allSelected =
                    allSessions.length > 0 && window.selectedSessions.size === allSessions.length;
                toolbar.innerHTML = `
                    <button data-click="toggleSelectAll" class="flex items-center gap-1.5 text-xs ${allSelected ? 'text-primary' : 'text-textMuted hover:text-secondary'} transition">
                        <i data-lucide="${allSelected ? 'check-square' : 'square'}" class="w-3.5 h-3.5"></i>
                        <span>${allSelected ? window.I18n.t('chatSessions.deselectAll') : window.I18n.t('chatSessions.selectAll')}</span>
                    </button>
                    <div class="flex-1"></div>
                    <span class="text-[10px] text-textMuted/50">${window.I18n.t('chatSessions.selectedCount', { n: window.selectedSessions.size })}</span>
                    <button data-click="deleteSelectedSessions" data-click-element class="p-1.5 ${window.selectedSessions.size > 0 ? 'text-danger hover:bg-danger/10' : 'text-textMuted/30 cursor-not-allowed'} rounded-lg transition" ${window.selectedSessions.size === 0 ? 'disabled' : ''} title="${window.I18n.t('chatSessions.deleteSelected')}">
                        <i data-lucide="trash-2" class="w-4 h-4"></i>
                    </button>
                    <button data-click="exitEditMode" class="p-1.5 text-textMuted hover:text-secondary hover:bg-surfaceHighlight rounded-lg transition" title="${window.I18n.t('common.done')}">
                        <i data-lucide="check" class="w-4 h-4"></i>
                    </button>
                `;
            } else {
                toolbar.innerHTML = `
                    <div class="flex-1"></div>
                    <button data-click="enterEditMode" class="p-1.5 text-textMuted/50 hover:text-textMuted hover:bg-surfaceHighlight rounded-lg transition" title="${window.I18n.t('chatSessions.manage')}">
                        <i data-lucide="list-checks" class="w-4 h-4"></i>
                    </button>
                `;
            }
            list.appendChild(toolbar);

            // 渲染收藏區（如果有收藏的對話）
            if (starredSessions.length > 0) {
                const starredSection = document.createElement('div');
                starredSection.className = 'mb-3';
                starredSection.innerHTML = `
                    <details class="starred-section" ${starredSectionOpen ? 'open' : ''}>
                        <summary class="flex items-center gap-2 px-3 py-2 text-xs font-medium text-textMuted/60 hover:text-textMuted cursor-pointer select-none" data-click="toggleStarredSection" data-click-element>
                            <i data-lucide="chevron-right" class="w-3 h-3 transition-transform starred-chevron"></i>
                            <i data-lucide="star" class="w-3 h-3 text-yellow-500"></i>
                            <span>${window.I18n ? window.I18n.t('chat.starred') : 'Starred'}</span>
                            <span class="ml-auto text-[10px] opacity-50">${starredSessions.length}</span>
                        </summary>
                        <div class="starred-list mt-1 ml-2 pl-2 border-l border-borderSubtle"></div>
                    </details>
                `;
                list.appendChild(starredSection);

                const starredList = starredSection.querySelector('.starred-list');
                starredSessions.forEach((session) => {
                    starredList.appendChild(createSessionItem(session));
                });
            }

            // 渲染普通對話區
            if (regularSessions.length > 0) {
                // 如果有收藏區，加一個小標題
                if (starredSessions.length > 0) {
                    const recentLabel = document.createElement('div');
                    recentLabel.className =
                        'flex items-center gap-2 px-3 py-2 text-xs font-medium text-textMuted/60';
                    recentLabel.innerHTML = `
                        <i data-lucide="clock" class="w-3 h-3"></i>
                        <span>${window.I18n ? window.I18n.t('chat.recent') : 'Recent'}</span>
                    `;
                    list.appendChild(recentLabel);
                }

                regularSessions.forEach((session) => {
                    list.appendChild(createSessionItem(session));
                });
            }

            // 都沒有的話顯示空狀態
            if (starredSessions.length === 0 && regularSessions.length === 0) {
                list.innerHTML =
                    '<div class="text-center text-xs text-textMuted/40 py-4">No history</div>';
            }

            // 儲存所有 session ID 供全選使用
            AppStore.set('allSessionIds', allSessions.map((s) => s.id));
            window._allSessionIds = AppStore.get('allSessionIds');
        } else {
            list.innerHTML =
                '<div class="text-center text-xs text-textMuted/40 py-4">No history</div>';
            // 退出編輯模式（沒有對話了）
            if (window.isEditMode) exitEditMode();
        }
        createIconsIn(document.getElementById('chat-session-list'));

        // 更新收藏區的 chevron 樣式
        updateStarredChevron();
        return data.sessions || [];
    } catch (e) {
        console.error('Failed to load sessions:', e);
        return [];
    }
}
window.loadSessions = loadSessions;

// 創建單個 session 項目
function createSessionItem(session) {
    const isActive = session.id === window.currentSessionId;
    const isSelected = window.selectedSessions.has(session.id);
    const div = document.createElement('div');
    div.dataset.sessionId = session.id;
    div.className = `group flex items-center gap-2 p-3 rounded-xl cursor-pointer transition text-sm mb-1 ${isActive ? 'bg-surfaceHighlight text-primary' : 'hover:bg-surfaceHighlight text-textMuted hover:text-secondary'} ${isSelected ? 'bg-primary/10 border border-primary/20' : ''}`;

    if (window.isEditMode) {
        // 編輯模式：點擊切換選中狀態
        div.onclick = () => toggleSessionSelection(session.id);
        div.innerHTML = `
            <div class="w-5 h-5 rounded border ${isSelected ? 'bg-primary border-primary' : 'border-borderLight'} flex items-center justify-center transition">
                ${isSelected ? '<i data-lucide="check" class="w-3 h-3 text-white"></i>' : ''}
            </div>
            <i data-lucide="message-square" class="w-4 h-4 opacity-70"></i>
            <div class="flex-1 truncate">${session.title || 'New Chat'}</div>
            ${session.is_pinned ? '<i data-lucide="star" class="w-3 h-3 fill-yellow-500 text-yellow-500"></i>' : ''}
        `;
    } else {
        // 正常模式
        div.onclick = () => switchSession(session.id);
        div.innerHTML = `
            <i data-lucide="message-square" class="w-4 h-4 opacity-70"></i>
            <div class="flex-1 truncate">${session.title || 'New Chat'}</div>
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition">
                <button data-click="toggleStarSession" data-click-args="${encodeURIComponent(JSON.stringify([session.id, !session.is_pinned]))}" data-click-event-first class="p-1 hover:text-yellow-500 transition" title="${session.is_pinned ? (window.I18n ? window.I18n.t('chat.unstar') : 'Unstar') : (window.I18n ? window.I18n.t('chat.star') : 'Starred')}">
                    <i data-lucide="star" class="w-3.5 h-3.5 ${session.is_pinned ? 'fill-yellow-500 text-yellow-500' : ''}"></i>
                </button>
                <button data-click="deleteSession" data-click-arg="${encodeURIComponent(session.id)}" data-click-event-first class="p-1 hover:text-danger transition" title="${window.I18n ? window.I18n.t('chat.deleteChat') : 'Delete Chat'}">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
            </div>
        `;

        // 如果是收藏的，強制顯示星星按鈕
        if (session.is_pinned) {
            const btnGroup = div.querySelector('.opacity-0');
            if (btnGroup) btnGroup.classList.remove('opacity-0');
        }
    }

    // 如果是當前 session，滾動到可見區域
    if (isActive && !window.isEditMode) {
        setTimeout(() => {
            div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 100);
    }

    return div;
}
window.createSessionItem = createSessionItem;

// 切換收藏區展開/收合狀態
function toggleStarredSection(summaryElement) {
    setTimeout(() => {
        const details = summaryElement.parentElement;
        starredSectionOpen = details.open;
        updateStarredChevron();
    }, 0);
}
window.toggleStarredSection = toggleStarredSection;

// 更新收藏區 chevron 的旋轉狀態
function updateStarredChevron() {
    const chevron = document.querySelector('.starred-chevron');
    if (chevron) {
        if (starredSectionOpen) {
            chevron.style.transform = 'rotate(90deg)';
        } else {
            chevron.style.transform = 'rotate(0deg)';
        }
    }
}
window.updateStarredChevron = updateStarredChevron;

// ========================================
// 編輯模式（批量刪除）
// ========================================

function enterEditMode() {
    window.isEditMode = true;
    window.selectedSessions.clear();
    loadSessions();
}
window.enterEditMode = enterEditMode;

function exitEditMode() {
    window.isEditMode = false;
    window.selectedSessions.clear();
    loadSessions();
}
window.exitEditMode = exitEditMode;

function toggleSessionSelection(sessionId) {
    if (window.selectedSessions.has(sessionId)) {
        window.selectedSessions.delete(sessionId);
    } else {
        window.selectedSessions.add(sessionId);
    }
    loadSessions();
}
window.toggleSessionSelection = toggleSessionSelection;

function toggleSelectAll() {
    const allIds = AppStore.get('allSessionIds') || [];
    if (window.selectedSessions.size === allIds.length) {
        // 已全選，取消全選
        window.selectedSessions.clear();
    } else {
        // 全選
        window.selectedSessions = new Set(allIds);
    }
    loadSessions();
}
window.toggleSelectAll = toggleSelectAll;

async function deleteSelectedSessions(btnElement) {
    if (window.selectedSessions.size === 0) return;

    const count = window.selectedSessions.size;
const confirmed = await showConfirm({
        title: window.I18n ? window.I18n.t('chat.batchDelete') : 'Batch delete',
        message: window.I18n
            ? window.I18n.t('chat.batchDeleteConfirm', { count })
            : (window.I18n ? window.I18n.t('chat.deleteSessionsConfirm', { count }) : `Are you sure you want to delete ${count} chat(s)? This action cannot be undone.`),
        confirmText: window.I18n ? window.I18n.t('chat.delete') : 'Delete',
        cancelText: window.I18n ? window.I18n.t('chat.cancel') : 'Cancel',
    });

    if (!confirmed) return;

    if (btnElement) {
        btnElement.disabled = true;
        btnElement.classList.add('opacity-50', 'cursor-not-allowed');
    }

    // ── Optimistic UI: remove all selected items + toolbar immediately ───────
    const toDelete = Array.from(window.selectedSessions);
    toDelete.forEach((sid) => {
        const div = document.querySelector(`[data-session-id="${sid}"]`);
        if (div) div.remove();
    });
    // Remove edit toolbar immediately so the count/buttons don't linger
    document.querySelector('#chat-session-list .edit-toolbar')?.remove();

    // 如果當前 session 被刪除了，清空聊天區域
    if (window.selectedSessions.has(window.currentSessionId)) {
        window.currentSessionId = null;
        AppStore.set('currentSessionId', null);
        showWelcomeScreen();
    }

    // Clear any HITL context for deleted sessions
    if (_hitlContext?.sessionId && window.selectedSessions.has(_hitlContext.sessionId)) {
        _hitlContext = null;
    }

    // 清空選中並退出編輯模式
    window.selectedSessions.clear();
    window.isEditMode = false;

    try {
        await Promise.all(
            toDelete.map((sessionId) =>
                AppAPI.delete(`/api/chat/sessions/${sessionId}`)
            )
        );
        // Rebuild sidebar (clears edit toolbar and syncs with server)
        await loadSessions();
    } catch (e) {
        console.error('Failed to delete sessions:', e);
        if (btnElement) {
            btnElement.disabled = false;
            btnElement.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    }
}
window.deleteSelectedSessions = deleteSelectedSessions;

async function toggleStarSession(event, sessionId, newStatus) {
    event.stopPropagation();
    // Decode sessionId that was encoded for XSS protection
    sessionId = decodeURIComponent(sessionId);
    try {
        await AppAPI.put(`/api/chat/sessions/${sessionId}/pin?is_pinned=${newStatus}`);
        await loadSessions();
    } catch (e) {
        console.error('Failed to toggle star:', e);
        if (typeof showToast === 'function') showToast(window.I18n ? window.I18n.t('chat.starOperationFailed') : 'Star operation failed, please try again later', 'error');
    }
}
window.toggleStarSession = toggleStarSession;

async function createNewChat() {
    try {
        // 先切換到 Chat tab（確保用戶能看到效果）
        if (typeof switchTab === 'function') {
            await switchTab('chat');
        }

        // 如果當前已經是新對話狀態 (currentSessionId 為 null)，直接返回
        if (window.currentSessionId === null) {
            showWelcomeScreen();
            return;
        }

        // 切換到"新對話"狀態，不立即建立 session
        // 不再 abort 舊 session 的分析 — 讓它在背景繼續跑（per-session controller）
        window.currentSessionId = null;
        AppStore.set('currentSessionId', null);
        try { localStorage.removeItem('chat_last_session_id'); } catch (_) {}

        // 顯示歡迎畫面
        showWelcomeScreen();

        // 重新載入列表（這會移除當前選中的高亮狀態）
        await loadSessions();

        if (typeof syncChatUIForCurrentSession === 'function') {
            syncChatUIForCurrentSession();
        }

        // Close sidebar on mobile（連同背景遮罩，別只動 -translate-x-full）
        closeSidebarOnMobile();
    } catch (e) {
        console.error('Failed to prepare new chat:', e);
    }
}
window.createNewChat = createNewChat;

async function showWelcomeScreen() {
    const container = document.getElementById('chat-messages');
    if (!container) {
        // 非 SPA 頁守門（2026-08-24 事故）：容器不存在時整個歡迎畫面跳過，
        // 不讓後續 innerHTML 寫入炸掉整條 init 鏈
        console.warn('[chat-sessions] #chat-messages not found — skip welcome screen');
        return;
    }

    // 檢查是否已設定 API Key，決定是否顯示 onboarding banner
    let hasKey = false;
    try {
        if (window.APIKeyManager && window.AuthManager?.isLoggedIn()) {
            hasKey = await window.APIKeyManager.hasAnyKey();
        }
    } catch (_) {}

    const onboardingBanner = !hasKey ? `
    <div id="api-key-onboarding-banner" class="mt-6 rounded-2xl border border-primary/20 bg-primary/5 px-5 py-4 text-sm opacity-0 animate-fade-in-up" style="animation-delay: 0.3s; animation-fill-mode: forwards;">
        <div class="flex items-start gap-3">
            <span class="text-xl">🔑</span>
            <div>
                <p class="font-bold text-primary mb-1">${window.I18n ? window.I18n.t('chat.setupApiKeyTitle') : 'Set up API Key to start using'}</p>
                <p class="text-textMuted text-xs leading-relaxed">
                    ${window.I18n ? window.I18n.t('chat.setupApiKeyDesc') : 'An OpenAI, Google Gemini, or OpenRouter API Key is required to enable AI analysis features.<br>Key is encrypted and stored on the server, and will be automatically restored after logging in on a new device.'}
                </p>
                <button data-click="switchTab" data-click-arg="settings"
                    class="mt-3 inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-primary text-background text-xs font-bold hover:opacity-90 transition">
                    <i data-lucide="settings-2" class="w-3 h-3"></i>&nbsp;${window.I18n ? window.I18n.t('chat.goToSettings') : 'Go to Settings'}
                </button>
            </div>
        </div>
    </div>` : '';

    container.innerHTML = `
    <div class="market-workspace bot-message flex flex-col items-center justify-center min-h-[72dvh] px-4 text-center gap-4">
        <div class="flex flex-col items-center gap-2">
            <div class="relative w-20 h-20 welcome-icon">
                <div class="absolute inset-0 rounded-2xl blur-2xl opacity-30" style="background: linear-gradient(135deg, #0098EA, #2A9DF4);"></div>
                <div class="relative w-full h-full rounded-2xl overflow-hidden border border-white/10">
                    <img src="/static/img/title_icon.png" alt="CryptoMind Logo" class="w-full h-full object-cover">
                </div>
            </div>
            <p class="brand-mark welcome-title h2 text-secondary/90">CryptoMind</p>
            <!-- 個人化 LLM 招呼（Trustworthy AI — Principal：Agent 主動表明身份） -->
            <p id="welcome-greeting" class="welcome-greeting text-sm text-secondary/60 max-w-md min-h-[1.5em] opacity-0 animate-fade-in-up" style="animation-delay: 0.4s; animation-fill-mode: forwards;"></p>
            <p class="welcome-sub text-sm text-textMuted/40 max-w-xs">${_t('chat.subtitle') || 'AI-powered crypto analysis across Crypto, US Stocks, and TW Stocks'}</p>
        </div>
        <div class="welcome-actions flex flex-wrap items-center justify-center gap-2 mt-2 opacity-0 animate-fade-in-up" style="animation-delay: 0.6s; animation-fill-mode: forwards;">
            <button data-click="fillChatExample" data-click-arg="chat.examplePromptBtc" data-fallback="BTC technical analysis" class="px-3 py-1.5 rounded-full bg-surfaceHighlight/60 hover:bg-surfaceHighlight text-xs text-textMuted hover:text-secondary transition border border-borderSubtle">
                ${window.I18n ? window.I18n.t('chat.quickBTCAnalysis') : 'BTC Analysis'}
            </button>
            <button data-click="fillChatExample" data-click-arg="chat.examplePromptTsmc" data-fallback="TSMC latest trend" class="px-3 py-1.5 rounded-full bg-surfaceHighlight/60 hover:bg-surfaceHighlight text-xs text-textMuted hover:text-secondary transition border border-borderSubtle">
                ${window.I18n ? window.I18n.t('chat.quickTSMCAnalysis') : 'TSMC Trend'}
            </button>
            <button data-click="fillChatExample" data-click-arg="chat.examplePromptEthSol" data-fallback="ETH vs SOL comparison" class="px-3 py-1.5 rounded-full bg-surfaceHighlight/60 hover:bg-surfaceHighlight text-xs text-textMuted hover:text-secondary transition border border-borderSubtle">
                ${window.I18n ? window.I18n.t('chat.quickETHSOLAnalysis') : 'ETH vs SOL'}
            </button>
        </div>
        ${onboardingBanner}
    </div>`;
    createIconsIn(document.getElementById('chat-messages'));
    createIconsIn(document.getElementById('chat-session-list'));

    // 個人化 LLM 招呼：登入使用者才拉（訪客保留靜態標題）
    _loadWelcomeGreeting();
}
window.showWelcomeScreen = showWelcomeScreen;

// 載入個人化 LLM 招呼（Trustworthy AI — Principal 支柱）
//
// 顯示策略(避免新聊天視窗空白):
// 1. 立即顯示本地 fallback 招呼(基於 AuthManager.currentUser 的名稱),不等待 API。
//    訪客也看得到(用 guest 版),不再因未登入而整行空白。
// 2. 登入使用者再非同步拉 /api/chat/greeting(走 AppAPI 自動 refresh token),
//    成功則替換成 LLM 個人化版;失敗則保留本地 fallback(不再靜默吞掉)。
async function _loadWelcomeGreeting() {
    const greetingEl = document.getElementById('welcome-greeting');
    if (!greetingEl) return;

    // 1. 立即顯示本地 fallback(登入用名稱版,訪客用 guest 版)
    const showLocalGreeting = () => {
        const isLoggedIn = window.AuthManager?.isLoggedIn();
        const name = window.AuthManager?.currentUser?.display_name
            || window.AuthManager?.currentUser?.username;
        let text;
        if (isLoggedIn && name) {
            text = window.I18n?.t('chat.welcomeGreeting', { name }) || `您好 ${name}，我是 CryptoMind 小幫手，今天有什麼需要協助的嗎？`;
        } else {
            text = window.I18n?.t('chat.welcomeGreetingGuest') || '您好，我是 CryptoMind 小幫手，今天有什麼需要協助的嗎？';
        }
        greetingEl.textContent = text;
        greetingEl.classList.remove('opacity-0');
    };

    showLocalGreeting();

    // 2. 訪客不拉 API(會 401),保留本地招呼即可
    if (!window.AuthManager?.isLoggedIn()) return;

    const lang = (window.I18n?.language) || 'zh-TW';
    // session_id：優先現有 session，否則用 'welcome'（讓快取 key 穩定，避免每次都重生成）
    const sessionId = (window.currentSessionId) || 'welcome';

    try {
        // 走 AppAPI.post 以獲得自動 token refresh(避免 cookie 過期吃 401 靜默失敗)。
        // AppAPI 已在 chat-sessions.js 頂部 import。
        const res = await AppAPI.post('/api/chat/greeting', {
            session_id: sessionId,
            language: lang,
        });
        if (!res || !res.ok) return; // 保留本地 fallback
        const data = await res.json();
        if (data?.success && data.greeting) {
            greetingEl.textContent = data.greeting;
            greetingEl.classList.remove('opacity-0');
            // fallback 招呼（非 LLM 生成）淡化顯示，提示使用者這不是動態的
            if (data.fallback) {
                greetingEl.classList.add('text-textMuted/40');
                greetingEl.classList.remove('text-secondary/60');
            }
        }
    } catch (err) {
        // 靜默失敗：本地 fallback 已顯示,使用者不會看到空白
        console.debug('[welcome greeting] API failed, using local fallback:', err);
    }
}
window._loadWelcomeGreeting = _loadWelcomeGreeting;

// 語言切換時，chat 分頁有數個以 JS 動態產生、無 data-i18n 屬性的內容需重新套用語言
// （chat 被排除在 spa.js 的全域分頁重渲染之外，避免干擾進行中的對話，故在此各別處理）。
// 同一次切換會派發兩次 languageChanged（i18next + 手動），以語言去重避免重複呼叫 API。
let _chatLastLang = null;
window.addEventListener('languageChanged', (e) => {
    const lang = e?.detail?.language;
    if (lang && lang === _chatLastLang) return;
    _chatLastLang = lang;

    // 1) 歡迎畫面（標題/副標題/快捷按鈕）——只在沒有任何對話訊息時才重渲染，避免覆蓋進行中的對話。
    const messages = document.getElementById('chat-messages');
    const hasChatMessages = messages && messages.querySelector('.chat-row-user, .chat-row-ai');
    if (!hasChatMessages && messages && messages.querySelector('.welcome-title')) {
        showWelcomeScreen();
    }
    // 2) 側邊欄 session 列表（訪客「請先登入」或已登入清單）。
    if (typeof loadSessions === 'function') {
        Promise.resolve(loadSessions()).catch(() => {});
    }
    // 3) 輸入框 placeholder / 發送鍵狀態（chat.placeholderReady / systemLocked）。
    if (typeof window.checkApiKeyStatus === 'function') {
        Promise.resolve(window.checkApiKeyStatus()).catch(() => {});
    }
});

// 當 API Key 設定完成（llmSettings.js dispatch）時，隱藏 welcome screen 上的 onboarding banner。
// showWelcomeScreen 的 banner 判斷繞過了 checkApiKeyStatus 更新鏈，需獨立監聽事件同步狀態。
window.addEventListener('apiKeyUpdated', () => {
    const banner = document.getElementById('api-key-onboarding-banner');
    if (banner) {
        banner.remove();
    }
});

// 直接更新側邊欄的 active 高亮，不重新拉取 sessions
function updateSessionActiveState(newSessionId) {
    document.querySelectorAll('[data-session-id]').forEach((el) => {
        const isActive = el.dataset.sessionId === newSessionId;
        if (isActive) {
            el.classList.add('bg-surfaceHighlight', 'text-primary');
            el.classList.remove('hover:bg-surfaceHighlight', 'text-textMuted', 'hover:text-secondary');
        } else {
            el.classList.remove('bg-surfaceHighlight', 'text-primary');
            el.classList.add('hover:bg-surfaceHighlight', 'text-textMuted', 'hover:text-secondary');
        }
    });
}
window.updateSessionActiveState = updateSessionActiveState;

async function switchSession(sessionId) {
    if (sessionId === window.currentSessionId) return;

    // 不再 abort 舊 session 的分析 — 讓它在背景繼續跑（per-session controller）
    window.currentSessionId = sessionId;
    AppStore.set('currentSessionId', sessionId);
    // 永久記錄：跨 browser 重啟也能還原
    try { localStorage.setItem('chat_last_session_id', sessionId); } catch (_) {}
    // 跨平台共用：寫回伺服器「當前對話」指標 → Telegram 端隨之接續同一對話。
    // fire-and-forget，失敗不影響切換。
    try {
        AppAPI.post('/api/chat/current-session', { session_id: sessionId }).catch(() => {});
    } catch (_) {}

    // 自動切換到 Chat 標籤頁（確保等待完成再載入歷史）
    if (typeof switchTab === 'function') {
        await switchTab('chat');
    }

    // 直接更新 DOM active 狀態，省掉一次 GET /api/chat/sessions
    updateSessionActiveState(sessionId);

    // 先收側邊欄再載入歷史：收合純粹是 UI 回饋，不該等 GET /api/chat/history。
    // 那支 API 實測要數秒，排在它後面會讓使用者點完之後好幾秒沒有任何反應。
    closeSidebarOnMobile();

    // Load history
    await loadChatHistory(sessionId);

    if (typeof syncChatUIForCurrentSession === 'function') {
        syncChatUIForCurrentSession();
    }
}
window.switchSession = switchSession;

async function deleteSession(event, sessionId) {
    event.stopPropagation();
    // Decode sessionId that was encoded for XSS protection
    sessionId = decodeURIComponent(sessionId);
    const btnElement = event.currentTarget;

    const confirmed = await showConfirm({
        title: window.I18n ? window.I18n.t('chat.deleteSession') : 'Delete conversation',
        message: window.I18n ? window.I18n.t('chat.deleteSessionConfirm') : 'Are you sure you want to delete this conversation? This action cannot be undone.',
        confirmText: window.I18n ? window.I18n.t('chat.delete') : 'Delete',
        cancelText: window.I18n ? window.I18n.t('chat.cancel') : 'Cancel',
        type: 'danger',
    });

    if (!confirmed) return;

    if (btnElement) {
        btnElement.disabled = true;
        btnElement.classList.add('opacity-50', 'cursor-not-allowed');
    }

    // ── Step 1: Optimistic UI — remove immediately, find next session ──────────
    const sessionDiv = event.target.closest('[data-session-id]');
    let nextSessionId = null;

    if (sessionDiv) {
        const allItems = [...document.querySelectorAll('[data-session-id]')];
        const idx = allItems.indexOf(sessionDiv);
        const sibling = allItems[idx + 1] || allItems[idx - 1];
        if (sibling) nextSessionId = sibling.dataset.sessionId;
        sessionDiv.remove();
    }

    const wasActive = window.currentSessionId === sessionId;
    if (wasActive) {
        const container = document.getElementById('chat-messages');
        if (container) container.innerHTML = '';
        window.currentSessionId = nextSessionId || null;
        AppStore.set('currentSessionId', window.currentSessionId);
        if (!nextSessionId) showWelcomeScreen();
    }

    // Clear any lingering HITL context for this session to prevent ghost re-creation
    if (_hitlContext?.sessionId === sessionId) _hitlContext = null;

    // ── Step 2: Fire DELETE + load next session history in parallel ───────────
    // No need to call loadSessions() — optimistic UI already removed the item
    try {
        await Promise.all([
            AppAPI.delete(`/api/chat/sessions/${sessionId}`),
            wasActive && nextSessionId ? loadChatHistory(nextSessionId) : Promise.resolve(),
        ]);
    } catch (e) {
        console.error('Failed to delete session:', e);
        if (btnElement) {
            btnElement.disabled = false;
            btnElement.classList.remove('opacity-50', 'cursor-not-allowed');
        }
        // Restore sidebar on failure
        await loadSessions();
    }
}
window.deleteSession = deleteSession;

export {
    loadSessions,
    createSessionItem,
    toggleStarredSection,
    updateStarredChevron,
    enterEditMode,
    exitEditMode,
    toggleSessionSelection,
    toggleSelectAll,
    deleteSelectedSessions,
    toggleStarSession,
    createNewChat,
    showWelcomeScreen,
    updateSessionActiveState,
    switchSession,
    deleteSession,
};
