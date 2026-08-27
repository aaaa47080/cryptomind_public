// ========================================
// notification-service.js - 通知服務
// ========================================

const NotificationService = {
    // 通知列表
    notifications: [],

    // 未读计数
    unreadCount: 0,

    // WebSocket 连接
    ws: null,

    // 重连定时器
    reconnectTimer: null,

    // 重连尝试次数（防止无限重连）
    reconnectAttempts: 0,
    MAX_RECONNECT_ATTEMPTS: 5,

    // 是否已登录
    isLoggedIn: false,

    // 避免重複初始化 / 重複 WebSocket
    _initialized: false,
    _initializedUserId: null,

    // 模拟数据（Phase 1 使用，作为后备）
    mockNotifications: [
        {
            id: 'notif_001',
            type: 'friend_request',
            title: window.I18n ? window.I18n.t('notification.friendRequest') : 'Friend Request',
            body: window.I18n ? window.I18n.t('notification.friendRequestBody') : 'Alice wants to add you as a friend',
            data: { from_user_id: 'user_123', from_username: 'Alice' },
            is_read: false,
            created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        },
        {
            id: 'notif_002',
            type: 'system_update',
            title: window.I18n ? window.I18n.t('notification.systemUpdate') : 'System Update',
            body: window.I18n ? window.I18n.t('notification.systemUpdateBody') : 'A new version is available. Updating is recommended.',
            data: { version: '2.1.0' },
            is_read: false,
            created_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        },
        {
            id: 'notif_003',
            type: 'message',
            title: window.I18n ? window.I18n.t('notification.newMessage') : 'New Message',
            body: window.I18n ? window.I18n.t('notification.newMessageBody') : 'Bob: Hi, how are you?',
            data: { from_user_id: 'user_456', from_username: 'Bob', conversation_id: 'conv_001' },
            is_read: true,
            created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
        },
        {
            id: 'notif_004',
            type: 'post_interaction',
            title: window.I18n ? window.I18n.t('notification.postInteraction') : 'Post Interaction',
            body: window.I18n ? window.I18n.t('notification.postInteractionBody') : 'Carol liked your post "Market Analysis"',
            data: { post_id: 'post_001', interaction_type: 'like', from_username: 'Carol' },
            is_read: true,
            created_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        },
    ],

    /**
     * 初始化通知服务
     */
    async init() {
        const { userId } = this._getCredentials();
        this._initialized = true;

        // Same logged-in user with an active socket does not need full re-init.
        if (
            this.isLoggedIn &&
            userId &&
            this._initializedUserId === userId &&
            this.ws &&
            (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
        ) {
            return;
        }

        // 檢查是否登录
        this.isLoggedIn = window.AuthManager && window.AuthManager.isLoggedIn();

        if (this.isLoggedIn) {
            this._initializedUserId = userId;
            // 已登录：从 API 获取真实数据
            await this.fetchNotifications();

            // 连接 WebSocket
            this.connectWebSocket();
        } else {
            this._initializedUserId = null;
            this.disconnectWebSocket();
            // 未登录：顯示空列表
            this.notifications = [];
            this.unreadCount = 0;
            this.notifyUpdate();
            console.log('[NotificationService] Not logged in, empty notifications');
        }
    },

    /**
     * 獲取用戶憑證
     */
    _getCredentials() {
        if (typeof AuthManager !== 'undefined' && AuthManager.currentUser) {
            const userId = AuthManager.currentUser.user_id || AuthManager.currentUser.uid;
            const hasSessionUser = !!(
                AuthManager.currentUser.user_id ||
                AuthManager.currentUser.uid
            );

            return { userId, hasSessionUser };
        }
        return { userId: null, hasSessionUser: false };
    },

    /**
     * 檢查 token 是否過期，     */
    _isTokenExpired() {
        if (typeof AuthManager !== 'undefined' && AuthManager.shouldDeferExpiredSessionCleanup?.()) {
            return false;
        }

        const { userId, hasSessionUser } = this._getCredentials();

        if (!userId || !hasSessionUser) {
            return true;
        }

        // 檢查 AuthManager 是否有過期檢查方法
        if (typeof AuthManager.isTokenExpired === 'function') {
            return AuthManager.isTokenExpired();
        }

        // 備用檢查：檢查 accessTokenExpiry
        const expiry = AuthManager.currentUser?.accessTokenExpiry;
        if (!expiry) {
            // 沒有過期時間≠已過期（session restore 中／舊格式 session）。
            // 2026-08-22 修：此處原判 true → fetchNotifications 直接
            // clearExpiredToken 會把使用者登出（無 silent refresh 的真兇）。
            return false;
        }

        return Date.now() > expiry;
    },

    /**
     * 从 API 获取通知
     */
    async fetchNotifications() {
        try {
            if (typeof AuthManager !== 'undefined' && AuthManager.shouldDeferExpiredSessionCleanup?.()) {
                return;
            }

            // 檢查 token 是否過期
            if (this._isTokenExpired()) {
                // 2026-08-22 修：原本直接呼叫全域登出（clearExpiredToken）——
                // 通知輪詢不該有全域登出權。改為背景觸發單飛 refresh
                // （AppAPI 的 401→refresh→retry 鏈是權威），本輪跳過。
                console.warn('[NotificationService] Token expired, triggering silent refresh');
                if (
                    typeof AuthManager !== 'undefined' &&
                    typeof AuthManager.backendTokenRefresh === 'function'
                ) {
                    AuthManager.backendTokenRefresh().catch(() => {});
                }
                return;
            }

            const { userId, hasSessionUser } = this._getCredentials();

            if (!userId || !hasSessionUser) {
                if (window.DEBUG_MODE)
                    console.log('[NotificationService] No credentials, empty notifications');
                this.notifications = [];
                this.unreadCount = 0;
                this.notifyUpdate();
                return;
            }

            const data = await AppAPI.get(`/api/notifications?user_id=${userId}&limit=50`);
            this.notifications = data.notifications || [];
            this.unreadCount = data.unread_count || 0;
            this.notifyUpdate();
            console.log(
                '[NotificationService] Loaded from API:',
                this.notifications.length,
                'notifications'
            );
        } catch (error) {
            // 401: AppAPI 的 401→refresh→retry 鏈已嘗試過仍丟上來＝refresh 暫時
            // 失敗（429/網路）或真失效。2026-08-22 修：不再由通知服務登出全域
            // session——真正的失效由 switchTab 守門／使用者互動時的權威鏈處理。
            if (error.status === 401) {
                console.warn('[NotificationService] 401 loading notifications (refresh likely failed); skipping this poll');
            } else {
                console.error('[NotificationService] Fetch error:', error);
            }
            this.notifications = [];
            this.unreadCount = 0;
            this.notifyUpdate();
        }
    },

    /**
     * 获取所有通知
     */
    getNotifications() {
        return this.notifications;
    },

    /**
     * 获取未读数量
     */
    getUnreadCount() {
        return this.unreadCount;
    },

    /**
     * 更新未读计数
     */
    updateUnreadCount() {
        this.unreadCount = this.notifications.filter((n) => !n.is_read).length;
    },

    /**
     * 标记通知为已读
     */
    async markAsRead(notificationId) {
        const notification = this.notifications.find((n) => n.id === notificationId);
        if (notification && !notification.is_read) {
            notification.is_read = true;
            this.updateUnreadCount();
            this.notifyUpdate();

            // 同步到服务器
            if (this.isLoggedIn) {
                try {
                    const { userId } = this._getCredentials();
                    if (userId) {
                        await AppAPI.post(
                            `/api/notifications/${notificationId}/read?user_id=${userId}`,
                        );
                    }
                } catch (error) {
                    console.error('[NotificationService] Mark as read error:', error);
                }
            }
        }
    },

    /**
     * 标记所有通知为已读
     */
    async markAllAsRead() {
        this.notifications.forEach((n) => (n.is_read = true));
        this.updateUnreadCount();
        this.notifyUpdate();

        // 同步到服务器
        if (this.isLoggedIn) {
            try {
                const { userId } = this._getCredentials();
                if (userId) {
                    await AppAPI.post(`/api/notifications/read-all?user_id=${userId}`);
                }
            } catch (error) {
                console.error('[NotificationService] Mark all read error:', error);
            }
        }
    },

    /**
     * 添加新通知
     */
    addNotification(notification) {
        this.notifications.unshift(notification);
        this.updateUnreadCount();
        this.notifyUpdate();

        // 显示 toast
        if (typeof showToast === 'function') {
            showToast(notification.body, 'info');
        }
    },

    /**
     * 通知 UI 更新
     */
    notifyUpdate() {
        window.dispatchEvent(
            new CustomEvent('notificationsUpdated', {
                detail: {
                    notifications: this.notifications,
                    unreadCount: this.unreadCount,
                },
            }),
        );
    },

    /**
     * 连接 WebSocket (Phase 2)
     * NOTE: WebSocket connections are NOT converted to AppAPI (different protocol)
     */
    connectWebSocket() {
        const { userId } = this._getCredentials();

        if (!userId) {
            if (window.DEBUG_MODE)
                console.log('[NotificationService] No credentials for WebSocket');
            return;
        }

        if (
            this.ws &&
            (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
        ) {
            return;
        }

        this.disconnectWebSocket(false);

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/notifications`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('[NotificationService] WebSocket connected');
                // 重置重连计数器
                this.reconnectAttempts = 0;
                // The backend authenticates this same-origin socket via httpOnly cookie.
                this.ws.send(JSON.stringify({ type: 'auth', user_id: userId }));
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'notification') {
                    this.addNotification(data.data);
                }
            };

            this.ws.onclose = () => {
                console.log('[NotificationService] WebSocket disconnected');
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('[NotificationService] WebSocket error:', error);
            };
        } catch (error) {
            console.error('[NotificationService] Failed to connect WebSocket:', error);
        }
    },

    /**
     * 安排重连（带最大重试次数和指数退避）
     */
    scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        // 检查是否超过最大重试次数
        if (this.reconnectAttempts >= this.MAX_RECONNECT_ATTEMPTS) {
            console.warn('[NotificationService] Max reconnect attempts reached, stopping');
            return;
        }

        // 指数退避：5s, 10s, 20s, 40s, 80s
        const delay = Math.min(5000 * Math.pow(2, this.reconnectAttempts), 60000);
        this.reconnectAttempts++;

        console.log(
            `[NotificationService] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.MAX_RECONNECT_ATTEMPTS})`,
        );

        this.reconnectTimer = setTimeout(() => {
            this.connectWebSocket();
        }, delay);
    },

    disconnectWebSocket(resetReconnect = true) {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.ws) {
            try {
                this.ws.onopen = null;
                this.ws.onmessage = null;
                this.ws.onclose = null;
                this.ws.onerror = null;
                if (
                    this.ws.readyState === WebSocket.OPEN ||
                    this.ws.readyState === WebSocket.CONNECTING
                ) {
                    this.ws.close();
                }
            } catch (error) {
                console.warn('[NotificationService] Failed to close WebSocket cleanly', error);
            }
            this.ws = null;
        }

        if (resetReconnect) {
            this.reconnectAttempts = 0;
        }
    },

    /**
     * 格式化时间
     */
    formatTime(dateString) {
        if (!dateString) return '';
        // PostgreSQL returns "2026-02-28 18:02:54.123" (space) — Android/mobile browsers
        // requires ISO 8601 "2026-02-28T18:02:54" (T) for reliable parsing
        const normalized =
            typeof dateString === 'string'
                ? dateString.replace(' ', 'T').replace(/(\.\d+)$/, '') // strip microseconds
                : dateString;
        const date = new Date(normalized);
        if (isNaN(date.getTime())) return '';

        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        const _t = (k, o) => (window.I18n ? window.I18n.t(k, o) : k);
        if (minutes < 1) return _t('time.justNow');
        if (minutes < 60) return _t('time.minutesAgo', { count: minutes });
        if (hours < 24) return _t('time.hoursAgo', { count: hours });
        if (days < 7) return _t('time.daysAgo', { count: days });

        return date.toLocaleDateString((window.I18n?.getLanguage?.() || 'zh-TW') === 'en' ? 'en-US' : 'zh-TW');
    },
};

function _deferredInit() {
    if (typeof AuthManager !== 'undefined' && AuthManager.currentUser) {
        NotificationService.init();
    } else {
        window.addEventListener('auth:ready', () => NotificationService.init(), { once: true });
    }
}

window.NotificationService = NotificationService;
window._initNotificationService = _deferredInit;

// Only init notifications after user is authenticated (deferred via auth:ready)
window.addEventListener('auth:ready', () => {
    if (!NotificationService._initialized) {
        NotificationService.init();
    }
}, { once: true });

window.addEventListener('auth:initialized', () => {
    NotificationService.init().catch((error) =>
        console.error('[NotificationService] auth:initialized sync failed:', error)
    );
});

export { NotificationService };
