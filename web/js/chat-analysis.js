// ========================================
// chat-analysis.js - 核心分析與訊息發送
// 職責：sendMessage、stopAnalysis、renderStoredBotMessage、流式輸出處理
// 依賴：chat-state.js, chat-sessions.js, chat-hitl.js
// ========================================


// ── Message Language Detection ───────────────────────────────────────────────
// Detect response language from message CONTENT (not UI locale), so an English
// question gets an English answer even when the UI is set to zh-CN / zh-TW / ru.
// For CJK text, respects the current UI locale: zh-CN users get 'zh-CN',
// otherwise 'zh-TW'. Returns 'ru' if Cyrillic is present, otherwise 'en'.
function detectMessageLanguage(text) {
    if (!text) return 'en';
    // CJK Unified Ideographs: U+4E00–U+9FFF ; CJK Ext-A: U+3400–U+4DBF
    if (/[\u4e00-\u9fff\u3400-\u4dbf]/.test(text)) {
        const uiLang = window.I18n?.getLanguage?.() || 'zh-TW';
        return uiLang === 'zh-CN' ? 'zh-CN' : 'zh-TW';
    }
    // Cyrillic: U+0400–U+04FF (Russian + Belarusian + Ukrainian + etc.)
    if (/[\u0400-\u04ff]/.test(text)) return 'ru';
    return 'en';
}
window.detectMessageLanguage = detectMessageLanguage;


// ── Global Helper for Button Cleanup ─────────────────────────────────────────
// ── Global Helper for Button Cleanup ─────────────────────────────────────────
function cleanupStaleButtons() {
    // Target ALL buttons within the chat container to ensure thorough cleanup
    const chatBtns = document.querySelectorAll('#chat-messages button');
    chatBtns.forEach((btn) => {
        // If the button is inside a bordered action bar (common in our cards), remove the bar.
        // Otherwise just remove the button.
        const parent = btn.closest('.flex');
        if (parent && parent.className.includes('border-t')) {
            parent.remove();
        } else {
            btn.remove();
        }
    });
}
window.cleanupStaleButtons = cleanupStaleButtons;

// ── Cross-Tab Navigation ──────────────────────────────────────────────────────
// Maps AI-resolved market names (from responseMetadata) and user keywords to tab IDs.
// label 用 key 延遲翻譯：此 map 在模組載入時求值，當時 i18n 多半尚未 init
// （i18next 未 init 的 t() 回傳原始 key）——先前直接在此求值導致 chip 顯示
// 「Go to tab.crypto tab」原文 key。改存 labelKey，_appendNavChip 渲染時翻譯。
const _MARKET_TAB_MAP = {
    crypto:    { tab: 'crypto',    labelKey: 'tab.crypto',    fallback: 'Crypto',     icon: 'bitcoin' },
    tw_stock:  { tab: 'twstock',   labelKey: 'tab.tw_stock',  fallback: 'TW Stock',   icon: 'trending-up' },
    us_stock:  { tab: 'usstock',   labelKey: 'tab.us_stock',  fallback: 'US Stock',   icon: 'bar-chart-2' },
    commodity: { tab: 'commodity', labelKey: 'tab.commodity', fallback: 'Commodity',  icon: 'package' },
    forex:     { tab: 'forex',     labelKey: 'tab.forex',     fallback: 'Forex',      icon: 'dollar-sign' },
};

// Client-side keyword patterns for instant hint (before AI response)
const _TAB_KEYWORD_RULES = [
    { tab: 'commodity', re: /黃金|貴金屬|silver|gold|xau|xag|原油|石油|oil|crude|天然氣|natural.?gas|銅|copper|大豆|小麥|玉米/i },
    { tab: 'forex',     re: /外匯|匯率|forex|usd\/|eur\/|gbp\/|jpy\/|cny\/|twd\/|美元|歐元|英鎊|日元|日幣|人民幣|澳幣/i },
    { tab: 'twstock',   re: /台股|台灣股|twse|加權指數|大盤|0050|2330|台積電|聯發科/i },
    { tab: 'usstock',   re: /美股|nasdaq|s&p\s*500|道瓊|dow\s*jones|標普|蘋果|apple|tesla|microsoft|nvda|輝達|英偉達/i },
    { tab: 'crypto',    re: /\b(btc|eth|bnb|xrp|sol|doge|usdt)\b|比特幣|以太幣|以太坊|加密貨幣|幣圈/i },
];

function _detectTabFromText(text) {
    for (const rule of _TAB_KEYWORD_RULES) {
        if (rule.re.test(text)) return rule.tab;
    }
    return null;
}

// Append a small navigation chip to a message element
function _appendNavChip(el, tabId, style = 'subtle') {
    const info = Object.values(_MARKET_TAB_MAP).find((m) => m.tab === tabId);
    if (!info || typeof switchTab !== 'function') return;
    // 渲染時翻譯 label（i18n 此時已 init；未 init 退 fallback，不用會回原始 key 的 t()）
    const label = window.I18n && window.I18n.isReady && window.I18n.isReady()
        ? window.I18n.t(info.labelKey)
        : info.fallback;
    const wrap = document.createElement('div');
    wrap.className = 'mt-2 flex items-center';
    if (style === 'prominent') {
        wrap.innerHTML = `<button data-click="switchTab" data-click-arg="${encodeURIComponent(info.tab)}"
            class="inline-flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-full bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 transition">
            <i data-lucide="external-link" class="w-3 h-3"></i>
            ${window.I18n && window.I18n.isReady && window.I18n.isReady() ? window.I18n.t('chat.navChipProminent', { tab: label }) : 'Go to ' + label + ' tab for real-time data'}
        </button>`;
    } else {
        wrap.innerHTML = `<button data-click="switchTab" data-click-arg="${encodeURIComponent(info.tab)}"
            class="inline-flex items-center gap-1.5 text-xs px-3 py-1 rounded-full bg-surfaceHighlight border border-borderLight text-textMuted hover:text-primary hover:border-primary/30 transition">
            <i data-lucide="${info.icon}" class="w-3 h-3"></i>
            ${window.I18n && window.I18n.isReady && window.I18n.isReady() ? window.I18n.t('chat.navChip', { tab: label }) : 'Go to ' + label + ' tab'}
        </button>`;
    }
    el.appendChild(wrap);
    setTimeout(() => createIconsIn(wrap), 0);
}
window._appendNavChip = _appendNavChip;

function getSelectedUserModel(provider) {
    const savedModel = window.APIKeyManager?.getModelForProvider?.(provider);
    if (savedModel) return savedModel;

    const llmSt = window.llmState;
    if (llmSt?.savedKeys?.[provider]?.model) {
        return llmSt.savedKeys[provider].model;
    }

    const modelInput = document.getElementById('llm-model-input');
    const modelSelect = document.getElementById('llm-model-select');

    // free_input provider（openrouter / nvidia / volcengine）從文字框讀，其餘從下拉讀
    if (window.isFreeInputProvider ? window.isFreeInputProvider(provider) : provider === 'openrouter') {
        return modelInput?.value?.trim() || null;
    }

    return modelSelect?.value?.trim() || null;
}

function normalizeChatErrorMessage(message, fallback) {
    if (typeof message !== 'string') {
        return fallback;
    }

    const normalized = message.trim();
    if (!normalized) {
        return fallback;
    }

    if (
        normalized === 'Internal server error. Please try again.' ||
        normalized.toLowerCase() === 'unknown' ||
        normalized.toLowerCase() === 'error'
    ) {
        return fallback;
    }

    return normalized;
}

/* 連線中斷 vs 真正的錯誤。
   手機切換 App、螢幕關閉、Wi-Fi/行動網路切換都會讓進行中的串流連線斷掉，
   瀏覽器丟出的是 TypeError（Chrome「Failed to fetch」、Safari「Load failed」、
   部分 WebView 直接給「network error」）。這類情況伺服器端仍在跑分析，
   不該當成失敗顯示給使用者。 */
function isConnectionLostError(error) {
    if (!error) return false;
    if (error instanceof TypeError) return true;
    const message = String(error.message || '').toLowerCase();
    return (
        message.includes('failed to fetch') ||
        message.includes('network error') ||
        message.includes('networkerror') ||
        message.includes('load failed') ||
        message.includes('connection was lost') ||
        message.includes('network connection')
    );
}

/* 連線斷掉之後，分析仍在伺服器端跑並會寫進對話紀錄。
   輪詢幾次把結果取回來，讓使用者不用自己重整。 */
const BACKGROUND_RESULT_POLL_INTERVAL_MS = 5000;
const BACKGROUND_RESULT_MAX_POLLS = 60;  // 最多盯 5 分鐘

/* 斷線後從斷點續傳。
   認證走 httpOnly cookie，所以 EventSource 可用 —— 它會自動帶 cookie，
   而且自己重連時會帶 Last-Event-ID。首次重連由我們用 ?after= 指定位置。
   EventSource 不可用或建立失敗時，退回輪詢（watchForBackgroundResult）。 */
function resumeAnalysisStream({ sessionId, runId, afterEventId, statusEl, contentSoFar }) {
    if (!runId || typeof window.EventSource !== 'function') {
        watchForBackgroundResult(sessionId, runId, statusEl);
        return;
    }

    let content = contentSoFar || '';
    let source;
    try {
        source = new EventSource(
            `/api/analyze/stream/${encodeURIComponent(runId)}?after=${afterEventId || 0}`
        );
    } catch (_) {
        watchForBackgroundResult(sessionId, runId, statusEl);
        return;
    }

    const finish = async () => {
        try { source.close(); } catch (_) {}
        if (window.currentSessionId === sessionId && typeof window.loadChatHistory === 'function') {
            await window.loadChatHistory(sessionId);
        }
    };

    const render = () => {
        if (!statusEl || window.currentSessionId !== sessionId) return;
        statusEl.innerHTML = window.renderStoredBotMessage
            ? window.renderStoredBotMessage(content)
            : escapeHtml(content);
        if (typeof window.stickChatToBottom === 'function') window.stickChatToBottom();
    };

    source.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (_) {
            return;
        }

        // 緩衝區已經蓋不到斷線位置時，伺服器一次補齊整段內容
        if (data.type === 'resync') {
            // 伺服器還在跑（reasoning 模型思考期 / 工具執行中）會回空 content。
            // 此時不可渲染空框（線上 #特斯拉案例：連線斷後 resume 拿空快照，
            // 空框卡住數分鐘直到背景分析完成）。保留既有 content 或顯示思考提示。
            const resyncContent = data.content;
            if (resyncContent && resyncContent.trim()) {
                content = resyncContent;
                render();
            } else if (!content || !content.trim()) {
                // 沒有任何累積內容 → 顯示「分析進行中」提示，不渲染空框
                if (statusEl && window.currentSessionId === sessionId) {
                    statusEl.innerHTML = `
                        <div class="process-container" style="border-style: dashed; opacity: 0.7;">
                            <div class="flex items-center gap-2 px-4 py-3">
                                <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-primary"></i>
                                <span class="font-medium text-sm text-textMuted">${window.I18n ? window.I18n.t('chat.analysisContinuesInBackground') : 'Analysis in progress, please wait...'}</span>
                            </div>
                        </div>`;
                    if (window.lucide) window.lucide.createIcons({ nodes: [statusEl] });
                }
            }
            return;
        }
        if (data.type === 'token' && data.content) {
            content += data.content;
            render();
            return;
        }
        if (data.type === 'final' && data.content) {
            content = data.content;
            render();
            return;
        }
        if (data.done) {
            finish();
        }
    };

    // EventSource 自己會重試；連線真的建立不起來才退回輪詢
    let errorCount = 0;
    source.onerror = () => {
        errorCount += 1;
        if (errorCount >= 3 || source.readyState === EventSource.CLOSED) {
            try { source.close(); } catch (_) {}
            watchForBackgroundResult(sessionId, runId, statusEl);
        }
    };
}

function watchForBackgroundResult(sessionId, runId, statusEl) {
    if (!sessionId || typeof window.loadChatHistory !== 'function') return;

    let attempts = 0;

    // 有 run_id 時可以拿到當下的部分輸出，讓使用者看到進度而不是乾等
    const showPartial = (content) => {
        if (!statusEl || !content) return;
        if (window.currentSessionId !== sessionId) return;
        statusEl.innerHTML =
            `<span class="text-amber-400 text-xs">${escapeHtml(
                window.I18n
                    ? window.I18n.t('chat.analysisContinuesInBackground')
                    : 'Connection dropped. The analysis is still running.'
            )}</span><div class="mt-2 opacity-70">${escapeHtml(content)}</div>`;
    };

    const poll = async () => {
        attempts += 1;
        // 使用者已經切到別的對話就不要打斷他
        if (window.currentSessionId !== sessionId) return;

        try {
            if (runId) {
                const run = await AppAPI.get(
                    `/api/analyze/status/${encodeURIComponent(runId)}`
                );
                if (run && run.success) {
                    if (run.status === 'completed') {
                        await window.loadChatHistory(sessionId);
                        return;
                    }
                    if (run.status === 'error' || run.status === 'timeout' || run.status === 'cancelled') {
                        // 伺服器端已結束且沒有結果，不用再等
                        await window.loadChatHistory(sessionId);
                        return;
                    }
                    showPartial(run.content);
                }
            } else {
                // 沒拿到 run_id（連線在 run_started 之前就斷了）→ 退回看對話紀錄
                const data = await AppAPI.get(
                    `/api/chat/history?session_id=${encodeURIComponent(sessionId)}`
                );
                const history = (data && data.history) || [];
                const last = history[history.length - 1];
                if (last && last.role === 'assistant') {
                    await window.loadChatHistory(sessionId);
                    return;
                }
            }
        } catch (_) {
            // 網路還沒恢復，或 run 已過期，下一輪再試
        }

        if (attempts < BACKGROUND_RESULT_MAX_POLLS) {
            window.setTimeout(poll, BACKGROUND_RESULT_POLL_INTERVAL_MS);
        }
    };

    window.setTimeout(poll, BACKGROUND_RESULT_POLL_INTERVAL_MS);
}
window.watchForBackgroundResult = watchForBackgroundResult;
window.isConnectionLostError = isConnectionLostError;

function renderResponseMetadata(metadata = {}) {
    // Trustworthy AI HITL 場景 B：詐騙判定證據鏈卡片
    const ev = metadata && metadata.scam_evidence;
    if (!ev || !ev.requires_ack) return '';

    const t = (k, fallback) => (window.I18n ? window.I18n.t(`chat.scamEvidence.${k}`, fallback) : fallback);
    const esc = (s) => (window.escapeHtml ? window.escapeHtml(String(s ?? '')) : String(s ?? ''));

    // verdict → 顏色 + 標籤
    const verdictStyle = {
        high_risk: { color: 'text-danger', border: 'border-danger/40', bg: 'bg-danger/10', label: t('verdictHighRisk', '高風險') },
        trusted_with_permissions: { color: 'text-amber-400', border: 'border-amber-400/40', bg: 'bg-amber-400/10', label: t('verdictTrustedWithPermissions', '可信但有權限風險') },
        warning: { color: 'text-amber-400', border: 'border-amber-400/40', bg: 'bg-amber-400/10', label: t('verdictWarning', '有風險訊號') },
    };
    const vs = verdictStyle[ev.verdict] || verdictStyle.warning;

    // 加權明細
    const breakdownHtml = (ev.breakdown || []).map((b) => {
        const w = b.weight;
        const wClass = w > 0 ? 'text-danger' : 'text-success';
        const wSign = w > 0 ? `+${w}` : `${w}`;
        return `<li class="flex items-start gap-2">
            <span class="${wClass} font-mono font-bold flex-shrink-0">${wSign}</span>
            <span class="text-textMuted">${esc(b.reason)}</span>
        </li>`;
    }).join('');

    // confirm 按鈕：帶 verdict 給 click handler；session_id 由 handler 從全域讀
    const btnArgs = encodeURIComponent(JSON.stringify([ev.verdict]));

    return `
    <div class="mt-4 rounded-2xl border ${vs.border} ${vs.bg} overflow-hidden" data-scam-evidence="${esc(ev.verdict)}">
        <div class="px-5 py-4">
            <div class="flex items-center gap-3 mb-3">
                <i data-lucide="shield-alert" class="w-5 h-5 ${vs.color} flex-shrink-0"></i>
                <h4 class="text-sm font-bold ${vs.color}">${t('title', '詐騙判定證據鏈')}</h4>
            </div>
            <div class="flex items-center gap-4 mb-3 text-xs">
                <div>
                    <span class="text-textMuted">${t('riskLevel', '風險等級')}:</span>
                    <span class="font-bold ${vs.color}">${esc(vs.label)}</span>
                </div>
                <div>
                    <span class="text-textMuted">${t('confidence', '信心分')}:</span>
                    <span class="font-bold font-mono">${esc(ev.confidence)}/100</span>
                </div>
            </div>
            ${breakdownHtml ? `
            <ul class="space-y-1.5 mb-3 text-xs">
                ${breakdownHtml}
            </ul>
            ` : ''}
            <div class="text-xs text-textMuted mb-3 italic">
                ${t('backendEvidenceNote', '⚠️ 以上為後端證據（GoPlus 資料），非投資建議。請自行評估風險。')}
            </div>
            <button data-click="confirmScamVerdict" data-click-args="${btnArgs}"
                class="w-full py-2.5 rounded-xl bg-primary hover:bg-primary/80 text-background font-bold text-sm transition">
                ${t('confirmButton', '我已閱讀風險')}
            </button>
        </div>
    </div>`;
}
window.renderResponseMetadata = renderResponseMetadata;

/**
 * Trustworthy AI HITL 場景 B：使用者確認已閱讀詐騙判定風險。
 * 由證據卡片的「我已閱讀風險」按鈕觸發（data-click-args 帶 [verdict]）。
 * 後端用 session_id 反查最新 scam_evidence 訊息驗證，不信任 client 傳值。
 */
async function confirmScamVerdict(verdict) {
    const sessionId = window.currentSessionId;
    if (!sessionId) return;
    const btn = event && event.currentTarget;
    try {
        if (btn) {
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        }
        const res = await AppAPI.post('/api/chat/scam-confirm', {
            session_id: sessionId,
            verdict: verdict,
        });
        if (res && res.success && window.showToast) {
            const msg = window.I18n
                ? window.I18n.t('chat.scamEvidence.confirmed', '已記錄您的風險確認')
                : '已記錄您的風險確認';
            window.showToast(msg, 'success');
        }
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
        if (window.showToast) window.showToast(String(e.message || e), 'error');
    }
}
window.confirmScamVerdict = confirmScamVerdict;

function normalizeRenderedChatContent(rawContent) {
    if (typeof rawContent !== 'string') {
        return rawContent;
    }

    const trimmed = rawContent.trim();
    if (!trimmed) {
        return rawContent;
    }

    const directPatterns = [
        /["'](?:final_answer|answer|response|content|message|output_text|text)["']\s*:\s*["']([\s\S]*?)["']\s*(?:,|})/,
        /```(?:json)?\s*([\s\S]*?)```/i,
    ];

    for (const pattern of directPatterns) {
        const match = trimmed.match(pattern);
        if (match && match[1]) {
            const candidate = match[1]
                .replace(/\\n/g, '\n')
                .replace(/\\"/g, '"')
                .replace(/\\'/g, "'")
                .trim();
            if (candidate && candidate !== trimmed) {
                return candidate;
            }
        }
    }

    if (
        (trimmed.startsWith('{') || trimmed.startsWith('[')) &&
        (trimmed.includes("'metadata'") ||
            trimmed.includes('"metadata"') ||
            trimmed.includes("'raw'") ||
            trimmed.includes('"raw"'))
    ) {
        return window.I18n
        ? window.I18n.t('chat.unexpectedRawOutput')
        : window.I18n ? window.I18n.t('chat.unexpectedRawOutput') : 'Unexpected raw output. Try again.';
    }

    return rawContent;
}
window.normalizeRenderedChatContent = normalizeRenderedChatContent;


/* ── 訪客模式 ──────────────────────────────────────────────────────────────
   未登入使用者的 AI 體驗：POST /api/guest/analyze（每日限量、平台免費模型）。
   回應直接渲染進現有的 bot 訊息框（botMsgDiv 由 sendMessage 事先建立）。 */
async function sendGuestMessage(text, botMsgDiv) {
    if (!botMsgDiv) return;
    botMsgDiv.innerHTML = `
        <div class="process-container" style="border-style: dashed; opacity: 0.7;">
            <div class="flex items-center gap-2 px-4 py-3">
                <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-primary"></i>
                <span class="font-medium text-sm text-textMuted">${window.I18n ? window.I18n.t('chat.guestThinking') : 'Thinking (guest mode)...'}</span>
            </div>
        </div>`;
    if (window.lucide) window.lucide.createIcons({ nodes: [botMsgDiv] });

    let resp;
    try {
        resp = await fetch('/api/guest/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                message: text,
                language: detectMessageLanguage(text),
            }),
        });
    } catch (err) {
        botMsgDiv.textContent = window.I18n
            ? window.I18n.t('chat.networkError')
            : 'Network error, please retry.';
        return;
    }

    if (resp.status === 429) {
        // 達每日限量 → 升級卡（連錢包解鎖）
        botMsgDiv.innerHTML = window.SECURE_GUEST_CARD
            ? window.SECURE_GUEST_CARD()
            : (window.I18n ? window.I18n.t('chat.guestLimitReached') : 'Guest daily limit reached — connect your TON wallet for unlimited analysis.');
        _appendConnectCta(botMsgDiv);
        return;
    }
    if (resp.status === 503) {
        botMsgDiv.textContent = window.I18n
            ? window.I18n.t('chat.guestUnavailable')
            : 'Guest mode is temporarily unavailable — connect a TON wallet to use your own API key.';
        _appendConnectCta(botMsgDiv);
        return;
    }
    if (!resp.ok) {
        let detail = '';
        try { const j = await resp.json(); detail = j.detail || ''; } catch {}
        botMsgDiv.textContent = detail || (window.I18n ? window.I18n.t('chat.serverError', { status: resp.status }) : `Server error (${resp.status})`);
        return;
    }

    let data;
    try { data = await resp.json(); } catch {
        botMsgDiv.textContent = 'Unexpected response.';
        return;
    }

    // 與主流程同款 markdown 渲染 + XSS 清理。
    // 部分模型回覆會帶 <p>/<br> HTML 標籚，markdown 渲染後會以原文露出 → 先清掉
    const cleanReply = String(data.reply || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/?p>/gi, '');

    // XSS 安全說明：markdown-it 預設 html:false 會把殘留的原始 HTML 逃逸成
    // 文字（模型注入的 <script> 等不會執行），輸出只剩 md 自產的白名單標籤；
    // javascript: 連結也被 md 的 validateLink 預設擋掉。因此不做
    // sanitizeHTML 二次加工 —— 它是全逃逸型，會把 md 的 <p>/<br> 也變成
    // 字面文字（線上實測）。模型夾帶的 <p>/<br> 已在 cleanReply 清除。
    if (typeof md !== 'undefined' && md && typeof md.render === 'function') {
        botMsgDiv.innerHTML = md.render(cleanReply);
    } else {
        botMsgDiv.textContent = cleanReply;
    }

    // 剩餘額度提示（訪客權益可見化）
    if (typeof data.remaining === 'number') {
        const hint = document.createElement('div');
        hint.className = 'mt-3 text-xs text-textMuted flex items-center gap-1.5';
        hint.innerHTML = `<i data-lucide="zap" class="w-3 h-3"></i>
            ${window.I18n ? window.I18n.t('chat.guestQuota', { remaining: data.remaining, limit: data.limit }) : `Guest mode: ${data.remaining}/${data.limit} questions today`}`;
        botMsgDiv.appendChild(hint);
        if (window.lucide) window.lucide.createIcons({ nodes: [hint] });
    }
    if (typeof stickChatToBottom === 'function') window.stickChatToBottom();
}
window.sendGuestMessage = sendGuestMessage;

/* 訪客升級 CTA：一鍵打開登入 modal（沿用既有 #login-modal） */
function _appendConnectCta(el) {
    const cta = document.createElement('div');
    cta.className = 'mt-4';
    cta.innerHTML = `<button type="button"
        class="inline-flex items-center gap-2 text-xs px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 transition">
        <i data-lucide="wallet" class="w-3.5 h-3.5"></i>
        ${window.I18n ? window.I18n.t('chat.guestConnect') : 'Connect TON Wallet to unlock'}
    </button>`;
    cta.querySelector('button').addEventListener('click', () => {
        const modal = document.getElementById('login-modal');
        if (modal) modal.classList.remove('hidden');
    });
    el.appendChild(cta);
    if (window.lucide) window.lucide.createIcons({ nodes: [cta] });
}
window._appendConnectCta = _appendConnectCta;

async function sendMessage() {
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const text = input.value.trim();
    if (!text && !isAnalyzing) return; // Allow empty text if we are just stopping? No, stop is a separate click.

    // 捕獲啟動時的 sessionId，用於 finally 判斷是否還在原 session（避免背景完成時動到新 session 的 DOM）
    const sessionIdAtStart = window.currentSessionId;

    // ── Global Cleanup ──
    // Force remove old buttons on any new interaction
    cleanupStaleButtons();

    // ── Input State Management for "Stop" capability ─────────────────────
    if (isAnalyzing) {
        // If we are in HITL pause (waiting for input), allow typing
        // But isAnalyzing is technically false during HITL pause (set in finally block)
        // Wait, in my previous edit, I set isAnalyzing = false in finally if hitlPaused.
        // So this block only runs if isAnalyzing is TRUE (streaming).
        // So clicking button here means STOP.

        // However, if the user hits ENTER in the input box...
        // If input is enabled (which it shouldn't be during streaming, but IS during HITL pause),
        // we need to check if we are actually in HITL mode.

        // Wait, if isAnalyzing is true, input SHOULD be disabled.
        // If isAnalyzing is false (HITL pause), we fall through to Start Analysis logic below.

        stopAnalysis();
        return;
    }

    // ── HITL Input Routing ───────────────────────────────────────────────
    // If we have a pending HITL context, this input is an answer/negotiation
    if (_hitlContext && _hitlContext.sessionId === window.currentSessionId) {
        const hitlType = _hitlContext.hitlType;

        // Clear input immediately
        input.value = '';

        // If it's a plan confirmation or pre_research, send the user's raw text
        // and let the backend's LLM determine if it's a question, modification, or confirmation.
        if (hitlType === 'confirm_plan' || hitlType === 'pre_research') {
            appendMessage('user', text);
            window.submitHITLAnswer(text);
            return;
        }

        // For other HITL types (e.g. simple clarification), send raw text
        appendMessage('user', text);
        window.submitHITLAnswer(text);
        return;
    }

    if (!text) return;

    // ── 訪客模式短路（2026-08-19 設計）─────────────────────────────────
    // 訪客不經 BYOK 閘門 / lazy session / 主分析流程：直接走 guest 端點
    // （每日限量、平台免費模型）。位置必須在 !userProvider 檢查之前。
    if (!(AuthManager.currentUser?.user_id || AuthManager.currentUser?.uid)) {
        isAnalyzing = true;
        try {
            input.value = '';
            if (document.activeElement === input) input.blur();
            appendMessage('user', text);
            const botDiv = appendMessage('bot', '');
            await sendGuestMessage(text, botDiv);
        } finally {
            resetChatUI();
        }
        return;
    }

    // ── Start Analysis ───────────────────────────────────────────────────
    isAnalyzing = true;

    // Change Send button to Stop button
    sendBtn.classList.remove('bg-primary', 'hover:brightness-110');
    sendBtn.classList.add('bg-red-500', 'hover:bg-red-600', 'text-white');
    sendBtn.innerHTML = '<i data-lucide="square" class="w-4 h-4 fill-current"></i>'; // Stop icon
    if (window.lucide) lucide.createIcons({ nodes: [sendBtn] });

    // Disable Input but keep Button enabled (as Stop)
    input.disabled = true;
    input.classList.add('opacity-50');
    // sendBtn.disabled = true; // Don't disable, we need it for Stop

    // 檢查用戶是否有設置 API key（使用快取，避免每次發送都打後端）
    const userProvider = await getCachedUserProvider();

    if (!userProvider) {
        resetChatUI(); // Helper to reset UI state
        showAlert({
            title: window.I18n ? window.I18n.t('chat.noApiKeyTitle') : 'API Key Not Set',
            message:
                window.I18n
                    ? window.I18n.t('chat.noApiKeyMessage')
                    : 'Please enter your API Key in system settings to use the analysis feature.\n\nYou need an OpenAI, Google Gemini, or OpenRouter API Key.',
            type: 'warning',
            confirmText: window.I18n ? window.I18n.t('chat.goToSettings') : 'Go to Settings',
        }).then(() => {
            if (typeof switchTab === 'function') switchTab('settings');
        });
        return;
    }

    // Enable UI for sending (transition to analysis state)
    sendBtn.disabled = false;
    input.classList.remove('opacity-50');
    sendBtn.classList.remove('opacity-50', 'cursor-not-allowed');

    const _sendIcon = sendBtn.querySelector('i[data-lucide]');
    // Note: We changed icon to Stop square earlier, so we don't want to reset it to arrow-up yet!
    // The previous code block was copy-pasted wrong.
    // We already set it to square icon at the top of function.

    // Remove the redundant error check block that was here.

    // Lazy Creation: 如果沒有 currentSessionId，先建立新的 Session
    // 訪客模式（2026-08-19）：訪客不建 session（無帳號），直接走 guest 流程
    const _isGuestUser = !(
        AuthManager.currentUser?.user_id || AuthManager.currentUser?.uid
    );
    if (!window.currentSessionId && !_isGuestUser) {
        try {
            const userId = AuthManager.currentUser.user_id;

            // 這裡可以傳遞 title (e.g., text.substring(0, 20)) 但後端通常會預設為 New Chat 或由第一條訊息生成
            const createData = await AppAPI.post('/api/chat/sessions', {
                title: text.substring(0, 40),
            });
            window.currentSessionId = createData.session_id;
            AppStore.set('currentSessionId', window.currentSessionId);

            // 刷新列表以顯示新對話
            // loadSessions();
        } catch (e) {
            console.error('Failed to create lazy session:', e);
            appendMessage('bot', '❌ ' + (window.I18n ? window.I18n.t('chat.createSessionFailed') : 'Failed to create session'));
            resetChatUI();
            return;
        }
    }

    const userSelectedModel = getSelectedUserModel(userProvider);
    const needsManualModel = window.isFreeInputProvider
        ? window.isFreeInputProvider(userProvider)
        : userProvider === 'openrouter';
    if (needsManualModel && !userSelectedModel) {
        resetChatUI();
        if (typeof window.showToast === 'function') {
            window.showToast(
                window.I18n?.t('llmSettings.enterModelName') || 'Please enter a model name first.',
                'error'
            );
        }
        return;
    }
    const marketType = 'spot';
    const autoExecute = false;

    input.value = '';
    // 送出後主動收鍵盤：手機上使用者送完訊息就是要看 AI 回覆（Telegram / iMessage 慣例）。
    // blur 會觸發 chat-state.js 的 focusout → 收鍵盤 → 輸入框貼回視窗底部。這個動作
    // 必須在 sendMessage 開始就做，避免鍵盤收起的漸進動畫期間把剛插入的「Thinking...」
    // 進度列擠到輸入框後面（問題 1 的根因之一）。
    // 注意：與 click-delegator.js 的 pointerdown preventDefault 配合 —— preventDefault 擋住
    // 瀏覽器把焦點「轉給按鈕」這條路徑，這裡的 blur 才是真正收鍵盤的觸發；兩者不衝突。
    if (document.activeElement === input) {
        input.blur();
    }
    const userMsgDiv = appendMessage('user', text);

    // Instant cross-tab hint: detect market intent from user's text
    const _detectedTab = _detectTabFromText(text);
    if (_detectedTab) _appendNavChip(userMsgDiv, _detectedTab, 'subtle');

    const botMsgDiv = appendMessage('bot', '');
    const startTime = Date.now();
    let timerInterval;

    // 重置分析過程面板的展開狀態
    AppStore.set('lastProcessOpenState', false);

    // Initial "Proto-Process" UI to match the final analysis UI for seamless transition
    botMsgDiv.innerHTML = `
        <div class="process-container" style="border-style: dashed; opacity: 0.7;">
            <div class="flex items-center gap-2 px-4 py-3">
                <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-primary"></i>
                <span class="font-medium text-sm text-textMuted">${window.I18n ? window.I18n.t('chat.thinking') : 'Thinking...'}</span>
                <span class="ml-auto flex items-center gap-1.5">
                    <span class="elapsed-stage text-xs text-textMuted/60"></span>
                    <span id="loading-timer" class="text-xs font-mono text-textMuted/50">0s</span>
                </span>
            </div>
        </div>
    `;

    // 新的一次分析：使用者理應看著最新內容，回到貼底狀態
    if (typeof window.resetChatStickToBottom === 'function') {
        window.resetChatStickToBottom();
    }

    timerInterval = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        window.ChatStreamUI.updateTimers(botMsgDiv, elapsed);
        // 進度列在分析期間會持續長高，不跟著捲就會滑到固定輸入框底下
        if (typeof window.stickChatToBottom === 'function') {
            window.stickChatToBottom();
        }
    }, 100);

    const ANALYSIS_REQUEST_TIMEOUT_MS = 3600000;  // 1 小時總超時（深度分析 + 多輪 LLM reasoning 可能很久）
    const ANALYSIS_STREAM_IDLE_TIMEOUT_MS = 600000;  // 10 分鐘閒置超時（LLM reflect/synthesize 過程中無 progress 是正常）

    // 伺服器端的執行識別碼，由 run_started 事件帶回；斷線後靠它續傳
    let activeRunId = null;
    // 最後收到的 SSE 事件 id，重連時告訴伺服器從哪裡繼續
    let lastEventId = 0;

    const localAnalysisController = new AbortController();
    if (sessionIdAtStart) {
        setAnalysisController(localAnalysisController, sessionIdAtStart);
    }
    let requestTimeoutId = null;
    let streamIdleTimeoutId = null;

    const clearAnalysisTimeouts = () => {
        if (requestTimeoutId) {
            clearTimeout(requestTimeoutId);
            requestTimeoutId = null;
        }
        if (streamIdleTimeoutId) {
            clearTimeout(streamIdleTimeoutId);
            streamIdleTimeoutId = null;
        }
    };

        const armStreamIdleTimeout = () => {
        if (streamIdleTimeoutId) clearTimeout(streamIdleTimeoutId);
        streamIdleTimeoutId = setTimeout(() => {
            localAnalysisController.abort(new Error('STREAM_IDLE_TIMEOUT'));
        }, ANALYSIS_STREAM_IDLE_TIMEOUT_MS);
    };

    // Pre-build HITL resume context (used if server sends hitl_question)
    const _hitlResumeContext = {
        originalMessage: text,
        sessionId: window.currentSessionId,
        userProvider,
        userSelectedModel,
        botMsgDiv,
        startTime,
    };

    // Declared OUTSIDE try so finally can read it
    let hitlPaused = false;
    // 同理：斷線時 catch 要拿已收到的內容當續傳起點，宣告在 try 內會取不到
    let fullContent = '';

    try {
        const currentUser = AuthManager.currentUser;
        const hasKnownSession = !!(
            currentUser?.user_id ||
            currentUser?.uid
        );
        if (!hasKnownSession) {
            // 理論上訪客已在函式前段短路；防禦：未登入一律導向登入
            if (typeof showToast === 'function') showToast(window.I18n ? window.I18n.t('chat.pleaseLogin') : 'Please log in first', 'warning');
            return;
        }
        requestTimeoutId = setTimeout(() => {
            localAnalysisController.abort(new Error('ANALYSIS_TIMEOUT'));
        }, ANALYSIS_REQUEST_TIMEOUT_MS);

        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: AppAPI.buildHeaders(),
            credentials: 'include',
            body: JSON.stringify({
                message: text,
                market_type: marketType,
                auto_execute: autoExecute,
                user_provider: userProvider,
                user_model: userSelectedModel,
                session_id: window.currentSessionId,
                language: detectMessageLanguage(text),
                system_prompt: (typeof getAnalysisPreferences === 'function')
                    ? (getAnalysisPreferences().system_prompt || null) : null,
                preset_id: (window.ChatPreset && typeof window.ChatPreset.getSelectedId === 'function')
                    ? window.ChatPreset.getSelectedId() : null,
            }),
            signal: localAnalysisController.signal,
        });

        if (!response.ok) {
            let errorMsg = window.I18n
                ? window.I18n.t('chat.serverError', { status: response.status })
                : `Server error (${response.status})`;
            try {
                const responseText = await response.text();
                if (responseText) {
                    try {
                        const errorData = JSON.parse(responseText);
                        if (typeof errorData.detail === 'string' && errorData.detail.trim()) {
                            errorMsg = errorData.detail.trim();
                        } else if (typeof errorData.message === 'string' && errorData.message.trim()) {
                            errorMsg = errorData.message.trim();
                        } else if (typeof errorData.error === 'string' && errorData.error.trim()) {
                            errorMsg = errorData.error.trim();
                        }
                    } catch {
                        errorMsg = responseText.substring(0, 160).trim();
                    }
                }
            } catch {
            }
            throw new Error(
                normalizeChatErrorMessage(
                    errorMsg,
                    window.I18n
                        ? window.I18n.t('chat.sendFailedCheckModel')
                        : window.I18n ? window.I18n.t('chat.sendFailedModel') : 'Send failed.'
                )
            );
        }

        // Backend 已經保存了用戶訊息並更新了標題，立即刷新列表以顯示新標題
        loadSessions().catch(function() {});

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let responseMetadata = null;
        let pendingBuffer = '';

        armStreamIdleTimeout();

        while (true) {
            const { value, done } = await reader.read();
            if (done || hitlPaused) break;

            armStreamIdleTimeout();
            const chunk = decoder.decode(value, { stream: true });
            const parsed = window.ChatStreamUI.consumeChunk(pendingBuffer, chunk);
            const lines = parsed.lines;
            pendingBuffer = parsed.pending;
            const currentElapsed = ((Date.now() - startTime) / 1000).toFixed(1);

            for (const line of lines) {
                // 事件 id：斷線重連時要從這裡之後續傳
                if (line.startsWith('id: ')) {
                    const parsedId = parseInt(line.slice(4).trim(), 10);
                    if (Number.isFinite(parsedId)) lastEventId = parsedId;
                    continue;
                }
                if (line.startsWith('data: ')) {
                    let data;
                    try {
                        data = JSON.parse(line.substring(6));
                    } catch {
                        continue;
                    }

                    // 伺服器端這次執行的識別碼。連線斷掉時用它查詢當下進度，
                    // 不必等分析全部跑完才知道發生什麼事。
                    if (data.type === 'run_started') {
                        activeRunId = data.run_id || null;
                        window._activeRunId = activeRunId;
                        continue;
                    }

                    // ── HITL: server needs user input ──────────────────────
                    if (data.type === 'hitl_question') {
                        clearInterval(timerInterval);
                        clearAnalysisTimeouts();
                        _hitlContext = _hitlResumeContext;
                        const idata = data.data || {};
                        // Store HITL type for sendMessage routing
                        _hitlContext.hitlType = idata.type;

                        if (idata.type === 'pre_research') {
                            renderPreResearchCard(idata, botMsgDiv);
                        } else if (idata.type === 'confirm_plan') {
                            renderPlanCard(idata, botMsgDiv);
                        } else if (idata.type === 'consent_gate') {
                            // Consent Gate（Trustworthy AI Hackathon — Policy Gate）
                            renderConsentCard(idata, botMsgDiv);
                        } else if (idata.type === 'skill_create_consent') {
                            // Skill 建立/修改/刪除同意卡（agent 自主管理 HITL）
                            if (typeof window.renderSkillConsentCard === 'function') {
                                window.renderSkillConsentCard(idata, botMsgDiv);
                            }
                        } else if (idata.type === 'memory_consent') {
                            // Memory 記憶同意卡
                            if (typeof window.renderMemoryConsentCard === 'function') {
                                window.renderMemoryConsentCard(idata, botMsgDiv);
                            }
                        } else if (idata.type === 'multi_consent') {
                            // 多項操作批次同意卡（一輪多提案一次顯示全部）
                            if (typeof window.renderMultiConsentCard === 'function') {
                                window.renderMultiConsentCard(idata, botMsgDiv);
                            }
                        } else if (idata.type === 'journal_consent') {
                            // Journal 記帳確認卡（金流 HITL：核准後才寫入統一帳本）
                            if (typeof window.renderJournalConsentCard === 'function') {
                                window.renderJournalConsentCard(idata, botMsgDiv);
                            }
                        } else {
                            // Render clarification question inline (clear spinner, show question)
                            const question = idata.question || (window.I18n ? window.I18n.t('chat.clarificationQuestion') : 'What specifically would you like to know?');
                            // 存進 _hitlContext，讓 hitlPaused 區塊（1001+）不再用空 fallback 蓋掉
                            _hitlContext.question = question;
                            _hitlContext.clarifyOptions = Array.isArray(idata.options) ? idata.options : [];
                            // 結構化選項（學 Hermes single-select MC）。有 options 時渲染可點選按鈕。
                            const _esc = typeof window.escapeHtml === 'function'
                                ? window.escapeHtml
                                : (s) => String(s).replace(/</g, '&lt;');
                            const options = _hitlContext.clarifyOptions;
                            let optionsHtml = '';
                            if (options.length > 0) {
                                optionsHtml = '<div class="mt-3 flex flex-col gap-2">';
                                options.forEach((opt) => {
                                    const label = typeof opt === 'string' ? opt : (opt.label || '');
                                    const hint = typeof opt === 'string' ? opt : (opt.hint || opt.label || '');
                                    optionsHtml += `<button type="button" data-clarify-answer="${_esc(hint)}" class="clarify-option-btn w-full text-left px-4 py-2.5 rounded-xl bg-background border border-borderSubtle text-secondary text-sm hover:border-primary/50 hover:bg-primary/5 transition">${_esc(label)}</button>`;
                                });
                                optionsHtml += '</div>';
                            }
                            botMsgDiv.innerHTML = `
                                <div class="rounded-2xl border border-borderLight bg-surfaceHighlight overflow-hidden">
                                    <div class="px-5 py-4 flex items-start gap-3">
                                        <i data-lucide="help-circle" class="w-4 h-4 text-primary mt-0.5 flex-shrink-0"></i>
                                        <div class="flex-1">
                                            <p class="text-sm text-secondary">${question}</p>
                                            ${optionsHtml}
                                            <p class="text-xs text-textMuted mt-2">${options.length > 0 ? (window.I18n ? window.I18n.t('chat.clickOrType') : '點選上方選項，或直接輸入你的問題') : (window.I18n ? window.I18n.t('chat.typeYourReply') : '直接輸入你的問題即可')}</p>
                                        </div>
                                    </div>
                                </div>`;
                            if (window.lucide) lucide.createIcons({ nodes: [botMsgDiv] });
                            // 綁定選項按鈕：點了直接送 hint 當答案
                            botMsgDiv.querySelectorAll('.clarify-option-btn').forEach((btn) => {
                                btn.addEventListener('click', () => {
                                    const answer = btn.getAttribute('data-clarify-answer') || '';
                                    if (typeof window.submitHITLAnswer === 'function') {
                                        window.submitHITLAnswer(answer);
                                    }
                                });
                            });
                        }
                    }
                    if (data.waiting) {
                        hitlPaused = true;
                        break;
                    }

                    // ── Meta Update (Codebook ID) ───────────────────────────
                    if (data.type === 'meta') {
                        if (data.codebook_id) {
                            botMsgDiv.dataset.codebookId = data.codebook_id;
                        }
                    }

                    // ── Progress Update (Parallel Execution) ────────────────
                    if (data.type === 'progress') {
                        window.ChatStreamUI.applyProgress(botMsgDiv, data.data || {});
                    }

                    if (data.type === 'response_metadata') {
                        responseMetadata = data.data || null;
                    }

                    // ── Revocation（可信 AI 第 6 要素）──────────────────────
                    // 使用者撤銷授權 → agent 已停止。把已串流的部份內容保留，
                    // 並 append 撤銷提示，讓 done 路徑的 final render 自然顯示。
                    if (data.type === 'revoked') {
                        const revokeNotice = data.message || window.I18n.t('chat.revokedNotice') || '授權已撤銷，Agent 已停止執行。';
                        fullContent +=
                            (fullContent ? '\n\n' : '') +
                            '> ⏹️ **' + revokeNotice + '**';
                        if (window.showToast) {
                            window.showToast(revokeNotice, 'info');
                        }
                    }

                    if (data.content) {
                        // type==='final' 是後端送出的「權威完整回覆」，必須「取代」
                        // 累積內容，否則會和先前串流進來的 token 重複（整段顯示兩次）。
                        // token 串流 / 舊版無 type 的分塊 → 累加。
                        //
                        // 安全性：後端 claw_loop._StreamSanitizer 已對每個 token chunk
                        // 做 tool name sanitize（防 LLM 把 get_crypto_price 等內部工具名
                        // 寫進回應）。final event 再經 _clean_claw_response 完整清洗一次
                        // 並覆蓋累積內容。雙層防護：即使串流中的 sanitize 有遺漏，
                        // final 覆蓋也會清掉。
                        if (data.type === 'final') {
                            fullContent = data.content;
                        } else {
                            fullContent += data.content;
                        }
                        // 實時更新內容，傳入 isStreaming=true 和當前耗時
                        botMsgDiv.innerHTML = renderStoredBotMessage(
                            fullContent,
                            true,
                            currentElapsed
                        );
                        // Smart scroll: only auto-scroll when streaming if user is near bottom
                        if (sessionIdAtStart === window.currentSessionId) {
                            const chatContainer = document.getElementById('chat-messages');
                            if (chatContainer) {
                                const isAtBottom =
                                    chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < 120;
                                if (isAtBottom) {
                                    chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
                                }
                            }
                        }
                    }

                    if (data.done) {
                        clearInterval(timerInterval);
                        clearAnalysisTimeouts();
                        isAnalyzing = false;
                        const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);

                        // Final render，傳入 isStreaming=false
                        botMsgDiv.innerHTML = renderStoredBotMessage(fullContent, false, totalTime);
                        if (responseMetadata) {
                            botMsgDiv.insertAdjacentHTML('beforeend', renderResponseMetadata(responseMetadata));
                        }

                        const timeBadge = document.createElement('div');
                        timeBadge.className =
                            'mt-4 flex items-center justify-between text-xs text-textMuted/60 font-mono';
                        timeBadge.innerHTML = `<span>${window.I18n.t('chat.elapsed', { time: totalTime })}</span>`;
                        botMsgDiv.appendChild(timeBadge);
                        if (window.lucide) {
                            lucide.createIcons({ nodes: [botMsgDiv] });
                        }

                        // Cross-tab nav: if AI resolved a specific market, show a prominent
                        // "Go to [Tab]" button so user can check live data in one click.
                        const _resolvedTab = responseMetadata?.resolved_market
                            ? (_MARKET_TAB_MAP[responseMetadata.resolved_market]?.tab || null)
                            : null;
                        // Also fall back to client-side detection if backend didn't resolve one
                        const _navTab = _resolvedTab || _detectTabFromText(text);
                        if (_navTab) _appendNavChip(botMsgDiv, _navTab, 'prominent');

                        // Refresh sessions list (to update title if it was new)
                        loadSessions().catch(function() {});

                        if (sessionIdAtStart === window.currentSessionId) {
                            const chatContainerDone = document.getElementById('chat-messages');
                            if (chatContainerDone) {
                                chatContainerDone.scrollTop = chatContainerDone.scrollHeight;
                            }
                        }
                    }

                    if (data.error) {
                        clearInterval(timerInterval);
                        clearAnalysisTimeouts();
                        botMsgDiv.innerHTML = `<span class="text-red-400">${escapeHtml(
                            normalizeChatErrorMessage(
                                data.error,
                                window.I18n
                                    ? window.I18n.t('chat.analysisFailedGeneric')
                                    : window.I18n ? window.I18n.t('chat.analysisFailed') : 'Analysis failed.'
                            )
                        )}</span>`;
                        isAnalyzing = false;
                        // 立即恢復輸入框與送出鈕：不能等串流關閉才 reset —
                        // 部分 proxy（如 Zeabur）在 error 事件後仍掛著 SSE 連線，
                        // finally 不會馬上跑，送出鈕會卡在紅色中止圖案
                        setSessionAnalyzing(false, sessionIdAtStart);
                        if (sessionIdAtStart === window.currentSessionId) {
                            resetChatUI();
                        }
                    }
                }
            }
        }
    } catch (err) {
        if (err.name === 'AbortError') {
            const abortReason = localAnalysisController.signal.reason;
            if (abortReason instanceof Error && abortReason.message === 'ANALYSIS_TIMEOUT') {
                botMsgDiv.innerHTML =
                    '<span class="text-red-400">' + (window.I18n ? window.I18n.t('chat.analysisTimeout') : 'Analysis timeout. Please narrow down your question and try again.') + '</span>';
            } else if (
                abortReason instanceof Error &&
                abortReason.message === 'STREAM_IDLE_TIMEOUT'
            ) {
                botMsgDiv.innerHTML =
                    '<span class="text-red-400">' + (window.I18n ? window.I18n.t('chat.streamIdleTimeout') : 'Analysis flow idle for too long, automatically stopped. Please retry.') + '</span>';
            } else {
                console.log('Analysis aborted by user');
                botMsgDiv.innerHTML = '<span class="text-orange-400">' + (window.I18n ? window.I18n.t('chat.analysisCancelled') : 'Analysis cancelled.') + '</span>';
            }
        } else if (isConnectionLostError(err)) {
            // 手機切到別的 App、螢幕關閉、網路切換都會讓串流連線中斷。
            // 伺服器端不會取消分析（見 analysis.py 的 detach_analysis），
            // 結果會照常寫進對話紀錄，所以這裡不該報錯嚇人，改成告知並自動取回。
            console.warn('Stream connection lost, analysis continues on server:', err);
            botMsgDiv.innerHTML = `<span class="text-amber-400">${escapeHtml(
                window.I18n
                    ? window.I18n.t('chat.analysisContinuesInBackground')
                    : 'Connection dropped. The analysis is still running and the result will appear here shortly.'
            )}</span>`;
            resumeAnalysisStream({
                sessionId: sessionIdAtStart,
                runId: activeRunId,
                afterEventId: lastEventId,
                statusEl: botMsgDiv,
                contentSoFar: fullContent,
            });
        } else {
            console.error(err);
            botMsgDiv.innerHTML = `<span class="text-red-400">${escapeHtml(
                normalizeChatErrorMessage(
                    err?.message,
                    window.I18n
                        ? window.I18n.t('chat.sendFailedCheckModel')
                        : window.I18n ? window.I18n.t('chat.sendFailedModel') : 'Send failed.'
                )
            )}</span>`;
        }
        clearInterval(timerInterval);
        clearAnalysisTimeouts();
        setSessionAnalyzing(false, sessionIdAtStart);
        resetChatUI();
    } finally {
        clearInterval(timerInterval);
        clearAnalysisTimeouts();

        clearAnalysisController(sessionIdAtStart);
        setSessionAnalyzing(false, sessionIdAtStart);

        // 背景完成保護：若使用者已切到別的 session，不要動當前可見的 DOM，
        // 否則會把新 session 的輸入框/發送鈕狀態污染成舊 session 的樣子
        const isStillActiveSession = sessionIdAtStart === window.currentSessionId;

        if (!isStillActiveSession) {
            resetChatUI();
            return;
        }

        if (hitlPaused) {
            // HITL paused: Unlock input so user can type negotiation/answer
            const input = document.getElementById('user-input');
            const sendBtn = document.getElementById('send-btn');

            // P2-2: Update botMsgDiv to show waiting-for-input state
            // (botMsgDiv still has spinner from Proto-Process if _hitlContext.question wasn't set yet)
            if (botMsgDiv) {
                const hitlType = _hitlContext?.hitlType;
                const question = _hitlContext?.question || (window.I18n ? window.I18n.t('chat.replyPrompt') : 'Please type your response below...');

                if (hitlType === 'pre_research' || hitlType === 'confirm_plan' || hitlType === 'consent_gate') {
                    // These have their own full-card rendering; just clear any leftover spinner.
                    // 注意：不可用 botMsgDiv.innerHTML = botMsgDiv.innerHTML（會把 DOM 重新序列化，
                    // 殺掉所有 JS 事件 handler，包含 consent 卡片的 data-click 委派也會失效）。
                    // 卡片已由 renderConsentCard/renderPlanCard append 完成，這裡只移除 spinner。
                    const spinner = botMsgDiv.querySelector('.typing-indicator, .animate-pulse, [data-spinner]');
                    if (spinner) spinner.remove();
                } else {
                    // clarify 卡片：若第一次渲染（802+）已經畫好含 options 的卡片，
                    // 不要用空 fallback 蓋掉它（會殺掉按鈕 + 顯示「Please type your response」）。
                    // 只在卡片還沒渲染（還是 spinner）時才 fallback。
                    const alreadyRendered = botMsgDiv.querySelector('.clarify-option-btn, .text-secondary');
                    if (!alreadyRendered) {
                        botMsgDiv.innerHTML = `
                            <div class="rounded-2xl border border-borderLight bg-surfaceHighlight overflow-hidden">
                                <div class="px-5 py-4 flex items-start gap-3">
                                    <i data-lucide="help-circle" class="w-4 h-4 text-primary mt-0.5 flex-shrink-0"></i>
                                    <div>
                                        <p class="text-sm text-secondary">${question}</p>
                                        <p class="text-xs text-textMuted mt-1.5">${window.I18n ? window.I18n.t('chat.replyInInputBelow') : 'Please reply in the input box below'}</p>
                                    </div>
                                </div>
                            </div>`;
                        if (window.lucide) lucide.createIcons({ nodes: [botMsgDiv] });
                    } else {
                        // 卡片已渲染，只清殘留 spinner
                        const spinner = botMsgDiv.querySelector('.typing-indicator, .animate-pulse, [data-spinner]');
                        if (spinner) spinner.remove();
                    }
                }
            }

            if (input) {
                input.disabled = false;
                input.classList.remove('opacity-50');
                input.focus();
                input.placeholder = window.I18n.t('chat.hitlPlaceholder');
            }
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.classList.remove(
                    'opacity-50',
                    'cursor-not-allowed',
                    'bg-red-500',
                    'hover:bg-red-600',
                    'text-white'
                );
                sendBtn.classList.add('bg-primary', 'hover:brightness-110');
                sendBtn.innerHTML = '<i data-lucide="arrow-up" class="w-5 h-5"></i>';
                if (window.lucide) lucide.createIcons({ nodes: [sendBtn] });
            }
        } else {
            // Normal finish or Abort
            resetChatUI();

            // 防禦性兜底（2026-08-23）：串流「正常結束」但 botMsgDiv 仍空或只剩
            // spinner＝事件全丟失的 edge case（頁面長開/多輪切換後觀察過兩次：
            // worker 已完成寫 DB、前端卻停在舊畫面）。結果必已在對話紀錄——
            // 直接從 DB 刷新救回。正常路徑（內容已串流渲染）不會觸發。
            const bubbleEmptyOrSpinnerOnly =
                botMsgDiv &&
                sessionIdAtStart === window.currentSessionId &&
                (
                    (botMsgDiv.innerText || '').trim() === '' ||
                    botMsgDiv.querySelector('.typing-indicator, [data-spinner], .animate-pulse')
                ) &&
                typeof window.loadChatHistory === 'function';

            // 防禦性兜底二（2026-08-25）：串流結束但初始進度卡（div.process-container）
            // 從沒被內容取代＝final/done 事件沒送達，泡泡會永遠停在
            // 「正在整理回覆」+ 各工具 spinner 的轉圈狀態（線上回報：回答完成
            // 後仍持續轉圈）。有 run_id 時先查伺服器端狀態：已結束→從 DB 救回；
            // 還在跑→交給背景輪詢接手，不要清掉使用者的畫面。
            // 注意 selector 用 div.process-container：完成路徑渲染的是
            // details.process-container（Analysis Steps 卡），不能誤判。
            const leftoverInitialProgressCard =
                botMsgDiv &&
                sessionIdAtStart === window.currentSessionId &&
                botMsgDiv.querySelector('div.process-container') &&
                typeof window.loadChatHistory === 'function';

            if (bubbleEmptyOrSpinnerOnly) {
                window.loadChatHistory(sessionIdAtStart);
            } else if (leftoverInitialProgressCard) {
                if (!activeRunId) {
                    window.loadChatHistory(sessionIdAtStart);
                } else {
                    AppAPI.get(`/api/analyze/status/${encodeURIComponent(activeRunId)}`)
                        .then((run) => {
                            if (!run || !run.success || window.currentSessionId !== sessionIdAtStart) return;
                            if (run.status === 'running' || run.status === 'detached' || run.status === 'waiting') {
                                watchForBackgroundResult(sessionIdAtStart, activeRunId, botMsgDiv);
                            } else {
                                window.loadChatHistory(sessionIdAtStart);
                            }
                        })
                        .catch(() => { /* 狀態查詢失敗就保守不動，避免誤清畫面 */ });
                }
            }
        }
    }
}
window.sendMessage = sendMessage;

// CSP-safe 綁定 Enter 送出：取代 index.html 內被 prod 嚴格 CSP 擋掉的
// inline onkeypress（keypress 已棄用，改 keydown；isComposing 防中文輸入法
// 選字時的 Enter 誤送）。ES module 為 deferred，執行時 DOM 已就緒。
(function bindChatInputEnter() {
    const input = document.getElementById('user-input');
    if (!input || input.dataset.boundEnter === '1') return;
    input.dataset.boundEnter = '1';
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => {
        const sendBtn = document.getElementById('send-btn');
        if (!sendBtn) return;
        const hasText = input.value.trim().length > 0;
        const analyzing = window.isSessionAnalyzing && window.isSessionAnalyzing(window.currentSessionId);
        if (hasText && !analyzing) {
            sendBtn.classList.remove('opacity-40', 'cursor-not-allowed');
            sendBtn.disabled = false;
        } else {
            sendBtn.classList.add('opacity-40', 'cursor-not-allowed');
        }
    });
})();

function stopAnalysis() {
    // 可信 AI 第 6 要素（Revocation）：不只是前端斷線，要真正終止後端 agent。
    // 若有 activeRunId，呼叫 revoke endpoint cancel 底層 task（fire-and-forget）。
    const rid = window._activeRunId;
    if (rid) {
        window._activeRunId = null;
        if (window.AppAPI && window.AppAPI.post) {
            window.AppAPI.post(`/api/analyze/${encodeURIComponent(rid)}/revoke`).catch(
                function (e) {
                    console.warn('Revoke request failed (non-blocking):', e);
                }
            );
        }
    }

    if (getAnalysisController()) {
        getAnalysisController().abort();
        clearAnalysisController();
    }

    // IMPORTANT: Clear HITL context so subsequent messages are treated as new queries
    window._hitlContext = null;

    // Append "Stopped" message
    const chatContainer = document.getElementById('chat-messages');
    if (chatContainer) {
        const stopMsg = document.createElement('div');
        stopMsg.className = 'flex justify-center my-4 opacity-0 animate-fade-in-up';
        stopMsg.style.animationFillMode = 'forwards';
        stopMsg.innerHTML =
            '<span class="px-3 py-1 rounded-full bg-red-500/10 text-red-500 text-xs font-mono border border-red-500/20">⛔ ' + (window.I18n ? window.I18n.t('chat.analysisTerminated') : 'Analysis terminated') + '</span>';
        chatContainer.appendChild(stopMsg);
        setTimeout(() => (chatContainer.scrollTop = chatContainer.scrollHeight), 100);
    }

    resetChatUI();
}
window.stopAnalysis = stopAnalysis;

function resetChatUI() {
    isAnalyzing = false;
    window._activeRunId = null; // 清掉 run_id，避免 stopAnalysis 拿到已結束的 run
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    if (input) {
        input.disabled = false;
        input.classList.remove('opacity-50');
        input.focus();
    }
    if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.classList.remove(
            'opacity-50',
            'cursor-not-allowed',
            'bg-red-500',
            'hover:bg-red-600',
            'text-white'
        );
        sendBtn.classList.add('bg-primary', 'hover:brightness-110');
        sendBtn.innerHTML = '<i data-lucide="arrow-up" class="w-5 h-5"></i>';
    }
    if (window.lucide) createIconsIn(sendBtn);
}
window.resetChatUI = resetChatUI;

// Reuse the renderStoredBotMessage function from previous step
function renderStoredBotMessage(fullContent, isStreaming = false, elapsedTime = null) {
    fullContent = normalizeRenderedChatContent(fullContent);

    // ⚠️ 2026-08-10: Swap 整體關閉(design 附錄) — 不再處理 SWAP_QUOTE_READY sentinel。
    // 後端 claw_loop 已停止附加 sentinel;這裡保留 sentinel 清理(防舊訊息殘留),
    // 但不再插入任何執行按鈕。

    let processContent = '';
    let resultContent = '';
    let hasProcessContent = false;

    const contentLines = fullContent.split('\n');
    let currentMode = 'normal';

    for (const cLine of contentLines) {
        if (cLine.includes('[PROCESS_START]')) {
            currentMode = 'process';
            hasProcessContent = true;
            continue;
        }
        if (cLine.includes('[PROCESS_END]')) {
            currentMode = 'normal';
            continue;
        }
        if (cLine.includes('[RESULT]')) {
            currentMode = 'result';
            continue;
        }
        if (cLine.startsWith('[PROCESS]')) {
            processContent += cLine.substring(9) + '\n';
            hasProcessContent = true;
        } else if (currentMode === 'process') {
            processContent += cLine + '\n';
        } else if (currentMode === 'result') {
            resultContent += cLine + '\n';
        } else {
            resultContent += cLine + '\n';
        }
    }

    let html = '';
    if (hasProcessContent && processContent.trim()) {
        const stepCount = (processContent.match(/✅|📊|⚔️|👨‍⚖️|⚖️|🛡️|💰|🚀|🔍|⏳/g) || []).length;
        const processLines = processContent
            .trim()
            .split('\n')
            .filter((l) => l.trim());
        let stepsHtml = '';
        let hasTimeInfo = false;

        processLines.forEach((line, index) => {
            const trimmed = line.trim();
            const isLastLine = index === processLines.length - 1;

            // Determine content
            let lineContent = '';
            if (trimmed.startsWith('---') || trimmed.startsWith('###')) {
                lineContent = `<div class="mt-3 mb-2 text-accent font-semibold text-sm">${md.renderInline(trimmed.replace(/^---\s*/, '').replace(/^###\s*/, ''))}</div>`;
            } else if (
                trimmed.startsWith('**🐂') ||
                trimmed.startsWith('**🐻') ||
                trimmed.startsWith('**⚖️')
            ) {
                lineContent = `<div class="mt-2 font-medium text-secondary">${md.renderInline(trimmed)}</div>`;
            } else if (trimmed.startsWith('>')) {
                lineContent = `<div class="pl-3 border-l-2 border-borderLight text-textMuted text-xs my-1">${md.renderInline(trimmed.substring(1).trim())}</div>`;
            } else if (trimmed.startsWith('→')) {
                lineContent = `<div class="pl-4 text-textMuted/60 text-xs">${trimmed}</div>`;
            } else if (trimmed.includes('⏱️ **分析完成**: 總耗時')) {
                hasTimeInfo = true;
                const timeMatch = trimmed.match(/⏱️ \*\*分析完成\*\*: 總耗時 ([\d.]+) 秒/);
                if (timeMatch) {
                    lineContent = `<div class="mt-2 p-3 rounded-xl bg-surface border border-borderLight flex items-center gap-2">
                                    <span class="text-primary">⏱️</span>
                                    <span class="text-textMuted">${window.I18n ? window.I18n.t('chat.totalTimeLabel') : 'Total time'}: <span class="text-secondary font-mono">${timeMatch[1]} ${window.I18n ? window.I18n.t('chat.secondsUnit') : 'sec'}</span></span>
                                  </div>`;
                }
            } else {
                lineContent = `<div class="process-step-item py-1">${md.renderInline(trimmed)}</div>`;
            }

            // Append Loading Spinner to the last line if streaming
            if (isStreaming && isLastLine && !trimmed.includes('分析完成')) {
                const spinnerSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-2 animate-spin inline-block ml-2 text-primary"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>`;

                // Check if it's a div wrapper (standard lines) or just text
                if (lineContent.includes('<div')) {
                    // Insert before the closing div
                    lineContent = lineContent.replace('</div>', ` ${spinnerSvg}</div>`);
                } else {
                    lineContent += ` ${spinnerSvg}`;
                }
            }
            stepsHtml += lineContent;
        });

        // 工具/分析過程預設「收合」，與 Gemini / ChatGPT / Claude 一致：
        // 摘要列已含 spinner、計時器、步驟數，收合狀態也看得到進度，想看細節再點開。
        // 使用者手動展開後，AppStore 會記住偏好並沿用到後續訊息。
        const isCurrentlyOpen =
            AppStore.get('lastProcessOpenState') !== undefined ? AppStore.get('lastProcessOpenState') : false;

        // 如果在步驟中沒有找到時間信息，則檢查完整內容
        let timeInfo = '';
        let timerHeader = '';

        if (!hasTimeInfo) {
            const timeMatch = fullContent.match(
                /\[PROCESS\]⏱️ \*\*分析完成\*\*: 總耗時 ([\d.]+) 秒/
            );
            if (timeMatch) {
                timeInfo = `<div class="mt-2 p-3 rounded-xl bg-surface border border-borderLight flex items-center gap-2">
                              <span class="text-primary">⏱️</span>
                              <span class="text-textMuted">${window.I18n ? window.I18n.t('chat.totalTimeLabel') : 'Total time'}: <span class="text-secondary font-mono">${timeMatch[1]} ${window.I18n ? window.I18n.t('chat.secondsUnit') : 'sec'}</span></span>
                            </div>`;
            } else if (isStreaming && elapsedTime) {
                // Live Timer in Header - Reuses the ID so the interval keeps updating it
                timerHeader = `<span class="ml-2 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-mono flex items-center gap-1">
                                <i data-lucide="clock" class="w-3 h-3"></i> 
                                <span id="loading-timer">${elapsedTime}s</span>
                               </span>`;
            }
        }

        html += `
            <details class="process-container" ${isCurrentlyOpen ? 'open' : ''}>
                <summary data-click="toggleProcessState" data-click-element>
                    <div class="flex items-center gap-2">
                        <i data-lucide="chevron-right" class="w-4 h-4 chevron"></i>
                        ${isStreaming ? '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader animate-spin text-primary"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>' : '<i data-lucide="check-circle" class="w-4 h-4 text-green-500"></i>'}
                        <span class="font-medium">${window.I18n ? window.I18n.t('chat.analysisSteps') : 'Analysis Steps'}</span>
                        ${timerHeader}
                    </div>
                    <span class="ml-auto text-xs text-textMuted/50">${stepCount} ${window.I18n ? window.I18n.t('chat.steps', { count: stepCount }) : 'steps'}</span>
                </summary>
                <div class="process-content custom-scrollbar pl-6 border-l border-borderSubtle ml-2 mt-2 space-y-1">
                    ${stepsHtml}
                </div>
                ${timeInfo}
            </details>
        `;
    }

    // 渲染前先移除 LLM 殘留的行內 HTML(如 <sup>[3]</sup>),避免 markdown-it
    // (html:false) 把它們當字面文字顯示。stripInlineHtml 為 app.js 全域函式。
    const renderMd = (text) => {
        const cleaned = window.stripInlineHtml ? window.stripInlineHtml(text) : text;
        return md ? md.render(cleaned) : `<pre>${cleaned.replace(/</g, '&lt;')}</pre>`;
    };

    if (resultContent.trim()) {
        html += `<div class="result-container prose mt-4">${renderMd(resultContent)}</div>`;
    } else if (!hasProcessContent) {
        let timerHtml = '';
        if (isStreaming && elapsedTime) {
            timerHtml = `<div class="flex items-center gap-2 mb-2 text-xs text-textMuted/50 font-mono">
                            <i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i>
                            <span id="loading-timer">${elapsedTime}s</span>
                          </div>`;
        }
        html = timerHtml + renderMd(fullContent);
    }

    const proposalMatch = fullContent.match(
        /<!-- TRADE_PROPOSAL_START (.*?) TRADE_PROPOSAL_END -->/
    );
    if (proposalMatch) {
        try {
            const proposalJson = proposalMatch[1];
            const pData = JSON.parse(proposalJson);
            html = html.replace(proposalMatch[0], '');
            const infoHtml = `
                <div class="mt-6 p-5 bg-surface rounded-2xl border border-borderLight">
                    <h4 class="text-sm font-bold text-primary flex items-center gap-2">
                        <i data-lucide="lightbulb" class="w-4 h-4"></i>
                        ${window.I18n ? window.I18n.t('chat.AIAdvice') : 'AI Trading Advice'}
                    </h4>
                    <div class="mt-3 grid grid-cols-2 gap-3 text-xs">
                        <div class="bg-surfaceHighlight rounded-lg p-3">
                            <div class="text-textMuted">${window.I18n ? window.I18n.t('chat.symbol') : 'Symbol'}</div>
                            <div class="text-secondary font-bold font-mono">${pData.symbol}</div>
                        </div>
                        <div class="bg-surfaceHighlight rounded-lg p-3">
                            <div class="text-textMuted">${window.I18n ? window.I18n.t('chat.direction') : 'Direction'}</div>
                            <div class="font-bold ${pData.side === 'buy' || pData.side === 'long' ? 'text-success' : 'text-danger'}">${pData.side.toUpperCase()}</div>
                        </div>
                        ${pData.stop_loss ? `
                        <div class="bg-surfaceHighlight rounded-lg p-3">
                            <div class="text-textMuted">${window.I18n ? window.I18n.t('chat.stopLoss') : 'Suggested Stop Loss'}</div>
                            <div class="text-danger font-mono">${pData.stop_loss}</div>
                        </div>
                        ` : ''}
                        ${pData.take_profit ? `
                        <div class="bg-surfaceHighlight rounded-lg p-3">
                            <div class="text-textMuted">${window.I18n ? window.I18n.t('chat.takeProfit') : 'Suggested Take Profit'}</div>
                            <div class="text-success font-mono">${pData.take_profit}</div>
                        </div>
                        ` : ''}
                    </div>
                    <div class="mt-3 text-xs text-textMuted">
                        ⚠️ ${window.I18n ? window.I18n.t('chat.disclaimer') : 'This is AI analysis advice, not investment advice. Please assess risks yourself for actual trading.'}
                    </div>
                </div>
            `;
            html += infoHtml;
        } catch (e) {
            console.error('Error parsing proposal', e);
        }
    }

    // ⚠️ 2026-08-10: Swap 整體關閉(design 附錄) — 不再插入執行按鈕。
    // 平台完全退出交換鏈路;sentinel 清理保留在函式開頭(防舊訊息殘留)。

    // Wrap <table> elements for proper overflow + border styling
    if (html.includes('<table')) {
        const temp = document.createElement('div');
        temp.innerHTML = html;
        temp.querySelectorAll('table').forEach((table) => {
            if (!table.parentElement.classList.contains('table-wrapper')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-wrapper';
                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);
            }
        });
        html = temp.innerHTML;
    }

    if (!isStreaming) {
        var disclaimer = window.I18n ? window.I18n.t('chat.disclaimer') : '⚠️ 此為 AI 分析建議，不構成投資建議。實際交易請自行評估風險。';
        html += '<div class="mt-3 text-[11px] text-textMuted/60 border-t border-borderSubtle pt-2">' + disclaimer + '</div>';
    }

    return html;
}
window.renderStoredBotMessage = renderStoredBotMessage;

// 保存展開狀態的函數
function toggleProcessState(summaryElement) {
    // 獲取對應的 details 元素
    const detailsElement = summaryElement.parentElement;
    // 延遲執行以確保狀態已更新
    setTimeout(() => {
        // 更新狀態標記
        AppStore.set('lastProcessOpenState', detailsElement.open);
    }, 0);
}
window.toggleProcessState = toggleProcessState;

export {
    cleanupStaleButtons,
    renderResponseMetadata,
    sendMessage,
    stopAnalysis,
    resetChatUI,
    renderStoredBotMessage,
    toggleProcessState,
};
