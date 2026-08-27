// ========================================
// analysisSettings.js - Analysis Settings Panel Controller
//
// 只負責「自訂 System Prompt」(Premium)。工具的啟用 / 停用統一由
// Settings → 工具設定 (toolSettings.js → user_tool_preferences) 控制，
// 那才是 agent 實際讀取的來源 (get_allowed_tools)。此面板不再重複提供
// 工具開關，避免兩處設定打架。
// ========================================

let _analysisSettingsLoaded = false;
let _analysisSettingsTier = 'free';
let _analysisSystemPrompt = '';
let _saveDebounceTimer = null;
let _savedIndicatorTimer = null;

function _isPremium() {
    return _analysisSettingsTier === 'premium';
}

async function initAnalysisSettings() {
    if (_analysisSettingsLoaded) return;

    _analysisSettingsLoaded = true;

    try {
        // /api/user/tools 回傳 user_tier，用來判斷是否解鎖 System Prompt 編輯。
        // AppAPI.get 直接回傳 JSON body（非 {data} 包裝）。
        const toolsRes = await AppAPI.get('/api/user/tools');
        if (toolsRes) {
            _analysisSettingsTier = toolsRes.user_tier || 'free';
        }

        try {
            const prefRes = await AppAPI.get('/api/user/analysis-preferences');
            if (prefRes && prefRes.success) {
                const chatPref = prefRes.preferences?.find(p => p.agent_id === 'chat');
                if (chatPref) {
                    _analysisSystemPrompt = chatPref.system_prompt || '';
                }
            }
        } catch (prefErr) {
            console.warn('[analysisSettings] preferences load failed, using defaults:', prefErr);
        }

        _renderSystemPrompt();
    } catch (err) {
        console.warn('[analysisSettings] init error:', err);
        _analysisSettingsLoaded = false;
        _renderSystemPrompt();
    }
}

function _renderSystemPrompt() {
    const textarea = document.getElementById('system-prompt-input');
    const overlay = document.getElementById('system-prompt-premium-lock');
    const counter = document.getElementById('system-prompt-counter');

    if (!textarea) return;

    textarea.value = _analysisSystemPrompt;
    const len = _analysisSystemPrompt.length;
    if (counter) counter.textContent = `${len}/2000`;

    const isPremium = _isPremium();
    if (overlay) {
        if (isPremium) {
            overlay.classList.add('hidden');
            textarea.disabled = false;
        } else {
            overlay.classList.remove('hidden');
            textarea.disabled = true;
        }
    }
}

function onSystemPromptInput(textarea) {
    _analysisSystemPrompt = textarea.value;
    const counter = document.getElementById('system-prompt-counter');
    if (counter) counter.textContent = `${textarea.value.length}/2000`;

    if (_isPremium()) {
        _debouncedSave();
    }
}

function _debouncedSave() {
    clearTimeout(_saveDebounceTimer);
    _saveDebounceTimer = setTimeout(() => {
        _savePreferences();
    }, 300);
}

function onSystemPromptBlur(textarea) {
    _analysisSystemPrompt = textarea.value;
    if (_isPremium()) {
        clearTimeout(_saveDebounceTimer);
        _savePreferences();
    }
}

function _showSavedIndicator() {
    const saved = document.getElementById('system-prompt-saved');
    const error = document.getElementById('system-prompt-save-error');
    if (error) error.classList.add('hidden');
    if (!saved) return;
    saved.classList.remove('hidden');
    clearTimeout(_savedIndicatorTimer);
    _savedIndicatorTimer = setTimeout(() => {
        saved.classList.add('hidden');
    }, 1500);
}

function _showSaveError() {
    const saved = document.getElementById('system-prompt-saved');
    const error = document.getElementById('system-prompt-save-error');
    if (saved) saved.classList.add('hidden');
    if (!error) return;
    error.classList.remove('hidden');
    clearTimeout(_savedIndicatorTimer);
    _savedIndicatorTimer = setTimeout(() => {
        error.classList.add('hidden');
    }, 3000);
}

async function _savePreferences() {
    if (!_isPremium()) return;

    try {
        await AppAPI.put('/api/user/analysis-preferences', {
            agent_id: 'chat',
            system_prompt: _analysisSystemPrompt,
        });
        _showSavedIndicator();
    } catch (err) {
        if (err.status === 403) {
            const overlay = document.getElementById('system-prompt-premium-lock');
            if (overlay) overlay.classList.remove('hidden');
        } else {
            console.warn('[analysisSettings] save failed:', err);
            _showSaveError();
        }
    }
}

function getAnalysisPreferences() {
    return {
        system_prompt: _analysisSystemPrompt || null,
    };
}

window.initAnalysisSettings = initAnalysisSettings;
window.onSystemPromptInput = onSystemPromptInput;
window.onSystemPromptBlur = onSystemPromptBlur;
window.getAnalysisPreferences = getAnalysisPreferences;
