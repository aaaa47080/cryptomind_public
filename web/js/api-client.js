/**
 * Centralized API Client
 *
 * Single source of truth for all API communication.
 * Provides auth headers, error handling, timeout, and retry.
 *
 * Usage:
 *   const data = await AppAPI.get('/api/forum/boards');
 *   const result = await AppAPI.post('/api/forum/posts', { title: '...' });
 *   const result = await AppAPI.delete('/api/alerts/123');
 */
var DEFAULT_TIMEOUT = 15000;
var MAX_RETRIES = 3;
var RETRY_DELAY = 1000;

function buildHeaders(customHeaders) {
    var headers = {
        'Content-Type': 'application/json',
    };
    if (customHeaders) {
        Object.keys(customHeaders).forEach(function (key) {
            headers[key] = customHeaders[key];
        });
    }
    return headers;
}

// JWT lives in an httpOnly cookie; the frontend can only know whether a
// session user exists, not read the token itself.
function hasSession() {
    if (typeof AuthManager !== 'undefined' && AuthManager.currentUser) {
        var user = AuthManager.currentUser;
        return !!(user.user_id || user.uid);
    }
    return false;
}

function sleep(ms) {
    return new Promise(function (resolve) {
        setTimeout(resolve, ms);
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth gate — 根治「refresh 成功還 401」的時序競態
//
// 問題：AuthManager.init() 是 async（需 network round-trip restore/refresh），
// 但頁面上的業務請求（如 /api/user/api-keys）常在 DOMContentLoaded /
// setTimeout 搶跑，帶著舊的/過期的 cookie 出門 → 401。即使 AppAPI 有
// 401→refresh→retry 鏈，那支搶跑的請求會在 refresh 完成前就送出。
//
// 根治：在 request() 最前面 ensureAuthReady()，等待 init() 完成才放行。
// init 是冪等的（_initPromise 去重），所有走 AppAPI 的請求自動繼承此保證，
// 不需每個模組記得 await auth:ready。
//
// opt-out（避免死鎖）：init 鏈上的 API 呼叫（/api/user/me、/api/config、
// /api/user/dev-login）必須傳 _skipAuthGate: true；refresh endpoint 自動 skip。
// ─────────────────────────────────────────────────────────────────────────────
async function ensureAuthReady(options, url) {
    // opt-out：明確 skip flag（init 內部呼叫用）
    if (options && options._skipAuthGate) return;
    // opt-out：refresh endpoint 本身（backendTokenRefresh 打它，自動 skip 避免死鎖）
    if (url && url.indexOf('/api/user/refresh') !== -1) return;
    if (typeof AuthManager !== 'undefined' && typeof AuthManager.init === 'function') {
        try {
            await AuthManager.init();
        } catch (e) {
            // init 失敗不擋請求，讓既有的 401→refresh→retry 鏈處理
        }
    }
}

function parseErrorResponse(response) {
    return response.text().then(function (text) {
        try {
            var json = JSON.parse(text);
            if (typeof json.detail === 'string') {
                return json.detail;
            }
            if (Array.isArray(json.detail)) {
                return json.detail
                    .map(function (e) {
                        return (e.loc ? e.loc.join('.') + ': ' : '') + e.msg;
                    })
                    .join('\n');
            }
            if (json.message) {
                return json.message;
            }
            return JSON.stringify(json);
        } catch (e) {
            return 'Status ' + response.status + ': ' + response.statusText;
        }
    });
}

async function request(method, url, options) {
    options = options || {};
    var timeout = options.timeout || DEFAULT_TIMEOUT;
    var retries = options.retries !== undefined ? options.retries : MAX_RETRIES;
    var isIdempotent = method === 'GET' || method === 'HEAD' || method === 'OPTIONS';
    if (!isIdempotent) retries = 0;
    var body = options.body;
    var customHeaders = options.headers;
    var noContentType = options.noContentType || false;
    var lastError = null;

    var headers = buildHeaders(
        noContentType ? customHeaders : customHeaders
    );
    if (noContentType) {
        delete headers['Content-Type'];
    }

    // Auth gate：確保 auth 初始化完成後才送出請求（根治時序競態 401）
    await ensureAuthReady(options, url);

    for (var attempt = 0; attempt <= retries; attempt++) {
        try {
            var controller = new AbortController();
            var timer = setTimeout(function () {
                controller.abort();
            }, timeout);

            var fetchOptions = {
                method: method,
                headers: headers,
                signal: controller.signal,
                credentials: 'include',
            };
            if (body !== undefined && body !== null) {
                fetchOptions.body = typeof body === 'string' ? body : JSON.stringify(body);
            }

            var response = await fetch(url, fetchOptions);
            clearTimeout(timer);

            if (!response.ok) {
                var errorMsg = await parseErrorResponse(response);
                lastError = new Error(errorMsg);
                lastError.status = response.status;

                // Auto-refresh on 401: skip for /api/user/refresh itself to avoid deadlock
                if (response.status === 401 && !options._authRetried && !url.includes('/api/user/refresh')) {
                    if (typeof AuthManager !== 'undefined' && typeof AuthManager.backendTokenRefresh === 'function') {
                        try {
                            var refreshResult = await AuthManager.backendTokenRefresh();
                            if (refreshResult && refreshResult.success) {
                                var retryOptions = Object.assign({}, options, {
                                    _authRetried: true,
                                    _skipAuthGate: true,
                                });
                                return await request(method, url, retryOptions);
                            }
                        } catch (_refreshErr) {}
                    }
                    if (
                        !options._testModeRecovered &&
                        typeof AuthManager !== 'undefined' &&
                        typeof AuthManager.recoverTestModeSession === 'function'
                    ) {
                        try {
                            var recoveryResult = await AuthManager.recoverTestModeSession();
                            if (recoveryResult && recoveryResult.success) {
                                var recoveredRetryOptions = Object.assign({}, options, {
                                    _authRetried: true,
                                    _testModeRecovered: true,
                                    _skipAuthGate: true,
                                });
                                return await request(method, url, recoveredRetryOptions);
                            }
                        } catch (_recoveryErr) {}
                    }
                    // Refresh failed — make error friendlier
                    lastError = new Error(window.I18n ? window.I18n.t('auth.tokenExpired') : 'Login expired, please refresh the page');
                    lastError.status = 401;
                    throw lastError;
                }

                if (
                    response.status === 401 ||
                    response.status === 403 ||
                    response.status === 422
                ) {
                    throw lastError;
                }

                if (attempt < retries) {
                    await sleep(RETRY_DELAY * (attempt + 1));
                    continue;
                }
                throw lastError;
            }

            var contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                return await response.json();
            }
            return await response.text();
        } catch (err) {
            lastError = err;
            if (err.name === 'AbortError') {
                lastError = new Error('Request timeout (' + timeout + 'ms)');
                lastError.status = 0;
            }
            if (
                err.status === 401 ||
                err.status === 403 ||
                err.status === 422
            ) {
                throw err;
            }
            if (attempt < retries) {
                await sleep(RETRY_DELAY * (attempt + 1));
                continue;
            }
        }
    }
    throw lastError;
}

const AppAPI = {
    get: function (url, options) {
        return request('GET', url, options);
    },
    post: function (url, body, options) {
        options = options || {};
        options.body = body;
        return request('POST', url, options);
    },
    put: function (url, body, options) {
        options = options || {};
        options.body = body;
        return request('PUT', url, options);
    },
    patch: function (url, body, options) {
        options = options || {};
        options.body = body;
        return request('PATCH', url, options);
    },
    delete: function (url, options) {
        return request('DELETE', url, options);
    },
    hasSession: hasSession,
    buildHeaders: buildHeaders,
};

// ─────────────────────────────────────────────────────────────────────────────
// 共用 config 快取 — 解決首頁載入時 /api/config 被多個模組重複呼叫的效能問題。
// 多個呼叫者共享同一支 in-flight request（不論呼叫順序都只打一次網路）；
// TTL 內重複呼叫直接回快取。force=true 強制重取（設定面板儲存後用）。
// ─────────────────────────────────────────────────────────────────────────────
var _appConfigCache = { ts: 0, payload: null };
var _appConfigInFlight = null;
var _APP_CONFIG_TTL_MS = 30000;

function getAppConfig(force) {
    var now = Date.now();
    if (!force && _appConfigCache.payload && now - _appConfigCache.ts < _APP_CONFIG_TTL_MS) {
        return Promise.resolve(_appConfigCache.payload);
    }
    if (!force && _appConfigInFlight) {
        return _appConfigInFlight;
    }
    _appConfigInFlight = AppAPI.get('/api/config', { _skipAuthGate: true })
        .then(function (cfg) {
            _appConfigCache = { ts: Date.now(), payload: cfg };
            return cfg;
        })
        .finally(function () {
            _appConfigInFlight = null;
        });
    return _appConfigInFlight;
}

var _modelConfigCache = { ts: 0, payload: null };
var _modelConfigInFlight = null;

function getModelConfig(force) {
    var now = Date.now();
    if (!force && _modelConfigCache.payload && now - _modelConfigCache.ts < _APP_CONFIG_TTL_MS) {
        return Promise.resolve(_modelConfigCache.payload);
    }
    if (!force && _modelConfigInFlight) {
        return _modelConfigInFlight;
    }
    _modelConfigInFlight = AppAPI.get('/api/model-config', { _skipAuthGate: true })
        .then(function (data) {
            var cfg = data?.model_config || data;
            _modelConfigCache = { ts: Date.now(), payload: cfg };
            return cfg;
        })
        .finally(function () {
            _modelConfigInFlight = null;
        });
    return _modelConfigInFlight;
}

AppAPI.getAppConfig = getAppConfig;
AppAPI.getModelConfig = getModelConfig;

window.AppAPI = AppAPI;
export { AppAPI };
