/* site-sidebar.js — 獨立頁共用側欄（forum 7 頁 / scam-tracker 3 頁 / governance）
   設計：docs/plans/2026-08-24-site-sidebar-unification.md（DANNY Approved 2026-08-24）

   與 SPA 側欄（index.html 內建 + global-nav.js）同款體驗：品牌 / 新對話 /
   「對話歷史 | 功能選單」雙分頁 / 用戶卡。桌機 fixed 常駐 + body padding 讓位；
   手機抽屜 + 遮罩 + 漢堡（注入各頁 <nav>；無 nav 的頁 fallback 浮動漢堡）。

   為何 classic script：governance / scam-tracker 不在 Vite 多頁 build input，
   module 引用會在 prod 404；classic + Dockerfile 白名單與 click-delegator 同模式。
   版面全 inline style + design token（governance 頁沒載 tailwind-built.css），
   顏色缺 token 時有 fallback，不依賴任何 utility class。 */
(function () {
    'use strict';

    if (document.getElementById('chat-sidebar')) return; // SPA 有自己的側欄
    if (window.__siteSidebarInit) return;
    window.__siteSidebarInit = true;

    var DESKTOP_MIN = 768;
    var WIDTH = 288;
    var mq = window.matchMedia('(min-width: ' + DESKTOP_MIN + 'px)');

    var els = {}; // sidebar / backdrop / hamburger / 區塊容器
    var state = { tab: 'history', user: null, userChecked: false };

    /* ---------- 小工具 ---------- */

    function t(key, fallback) {
        if (window.I18n && typeof window.I18n.t === 'function') {
            var s = window.I18n.t(key);
            if (s && s !== key) return s;
        }
        return fallback;
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // 直接 fetch（不依賴 AppAPI——classic 頁有、forum 頁也有，但保持零依賴最穩）
    function api(method, path, body) {
        return fetch(path, {
            method: method,
            credentials: 'include',
            headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body: body ? JSON.stringify(body) : undefined,
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.status === 204 ? null : r.json();
        });
    }

    function isGuestAllowed(item) {
        return item.id === 'chat';
    }

    function isGuest() {
        return !state.user;
    }

    /* 2026-08-24 review 修復：此前讀的 token 名（--surface/--primary/--textMuted…）
       在設計系統中不存在——實際 token 是 --color-* 色頻三聯組（"37 99 235"），
       getComputedStyle 讀不到 → 全部靜默 fallback 成硬編碼深色值，獨立頁側欄
       不跟隨主題、accent 也不是品牌藍（DESIGN_SYSTEM: #2563EB）。
       改為內嵌 var() 運算式：token 存在 → 跟隨主題；不存在 → 原 fallback 值。
       色頻 token 的半透明變體用 tokenAlpha()（rgb(channels / a)），不可串接 hex alpha。 */
    var _TOKEN_EXPR = {
        '--surface': 'var(--surface-color, rgba(20,24,33,0.96))',
        '--borderSubtle': 'var(--border-subtle-color, rgba(128,128,128,0.18))',
        '--primary': 'var(--primary-color, #0098ea)',
        '--background': 'var(--bg-color, #0d1017)',
        '--secondary': 'var(--secondary-color, #e8ecf3)',
        '--textMain': 'rgb(var(--color-text-primary, 213 218 226))',
        '--textMuted': 'rgb(var(--color-text-muted, 139 147 163))',
        // 無獨立 token：以 muted 色頻 12% 疊加呈現 highlight（=原 fallback 語意）
        '--surfaceHighlight': 'rgb(var(--color-text-muted, 128 128 128) / 0.12)',
    };

    function cssVar(name, fallback) {
        return _TOKEN_EXPR[name] || fallback;
    }

    function tokenAlpha(channelsVar, fallbackChannels, alpha) {
        return 'rgb(var(' + channelsVar + ', ' + fallbackChannels + ') / ' + alpha + ')';
    }

    /* ---------- 骨架（parse 期立即建，避免內容閃現後才讓位） ---------- */

    function buildSkeleton() {
        var aside = document.createElement('aside');
        aside.id = 'site-sidebar';
        aside.setAttribute('aria-label', 'Sidebar');
        aside.setAttribute('style', [
            'position:fixed', 'top:0', 'bottom:0', 'left:0',
            'width:' + WIDTH + 'px', 'z-index:60',
            'display:flex', 'flex-direction:column',
            'background:' + cssVarSafe('--surface', 'rgba(20,24,33,0.96)'),
            'border-right:1px solid ' + cssVarSafe('--borderSubtle', 'rgba(128,128,128,0.18)'),
            '-webkit-backdrop-filter:blur(14px)', 'backdrop-filter:blur(14px)',
            'transform:translateX(-100%)', 'transition:transform .3s ease',
            'overscroll-behavior:contain',
        ].join(';'));
        document.body.appendChild(aside);
        els.sidebar = aside;

        var backdrop = document.createElement('div');
        backdrop.id = 'site-sidebar-backdrop';
        backdrop.setAttribute('style', [
            'position:fixed', 'inset:0', 'z-index:55',
            'background:rgba(0,0,0,0.5)', '-webkit-backdrop-filter:blur(2px)',
            'backdrop-filter:blur(2px)', 'opacity:0', 'pointer-events:none',
            'transition:opacity .3s ease',
        ].join(';'));
        backdrop.addEventListener('click', closeDrawer);
        document.body.appendChild(backdrop);
        els.backdrop = backdrop;

        // 漢堡：優先注入頁面 <nav> 開頭（與既有頂欄並排）；無 nav（governance）
        // fallback 固定左上浮動鈕。
        var nav = document.querySelector('nav');
        var burger = document.createElement('button');
        burger.id = 'site-sidebar-burger';
        burger.type = 'button';
        burger.setAttribute('aria-label', t('sidebar.open', 'Menu'));
        burger.setAttribute('style', [
            'display:inline-flex', 'align-items:center', 'justify-content:center',
            'width:2.25rem', 'height:2.25rem', 'border-radius:9999px',
            'border:none', 'cursor:pointer', 'flex-shrink:0',
            'background:transparent', 'color:inherit',
        ].join(';'));
        burger.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
            'stroke-linejoin="round"><line x1="4" y1="7" x2="20" y2="7"/>' +
            '<line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>';
        burger.addEventListener('click', function () {
            if (mq.matches) return; // 桌機側欄常駐，漢堡隱藏（updateLayout 控制）
            toggleDrawer();
        });
        if (nav && nav.firstElementChild) {
            nav.insertBefore(burger, nav.firstElementChild);
        } else {
            burger.setAttribute('style', burger.getAttribute('style') +
                ';position:fixed;top:0.75rem;left:0.75rem;z-index:54;' +
                'background:' + cssVarSafe('--surface', 'rgba(20,24,33,0.9)') +
                ';border:1px solid rgba(128,128,128,0.25)');
            document.body.appendChild(burger);
        }
        els.burger = burger;

        renderContent();
        updateLayout();
        mq.addEventListener('change', updateLayout);
        window.addEventListener('resize', updateLayout);
    }

    function cssVarSafe(name, fallback) {
        try {
            var v = cssVar(name, fallback);
            return v;
        } catch (_e) {
            return fallback;
        }
    }

    /* ---------- 內容渲染 ---------- */

    function renderContent() {
        var sb = els.sidebar;
        sb.innerHTML = '';

        // 1. 品牌列
        var brand = document.createElement('div');
        brand.setAttribute('style', 'display:flex;align-items:center;justify-content:' +
            'space-between;padding:1rem 1rem 0.75rem;border-bottom:1px solid ' +
            cssVarSafe('--borderSubtle', 'rgba(128,128,128,0.18)'));
        brand.innerHTML =
            '<a href="/static/index.html" style="display:flex;align-items:center;gap:0.5rem;' +
            'text-decoration:none;color:' + cssVarSafe('--primary', '#0098ea') +
            ';letter-spacing:0.01em">' +
            '<img src="/static/img/title_icon.png" alt="CryptoMind Logo" ' +
            'style="width:1.75rem;height:1.75rem;border-radius:0.5rem;object-fit:cover">' +
            '<span style="font-weight:700;font-size:1.05rem">CryptoMind</span></a>';
        // 手機關閉鈕（桌機隱藏由 updateLayout 處理 display）
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.setAttribute('style', 'display:none;border:none;background:transparent;' +
            'color:inherit;cursor:pointer;padding:0.375rem;border-radius:9999px;font-size:1rem;line-height:1');
        closeBtn.textContent = '✕';
        closeBtn.addEventListener('click', closeDrawer);
        els.closeBtn = closeBtn;
        brand.appendChild(closeBtn);
        sb.appendChild(brand);

        // 2. 新對話
        var newWrap = document.createElement('div');
        newWrap.setAttribute('style', 'padding:1rem');
        var newBtn = document.createElement('button');
        newBtn.type = 'button';
        newBtn.textContent = '＋ ' + t('sidebar.newChat', 'New Chat');
        newBtn.setAttribute('style', [
            'width:100%', 'padding:0.7rem 0', 'border-radius:0.75rem', 'cursor:pointer',
            'font-weight:700', 'font-size:0.85rem',
            'background:' + tokenAlpha('--color-primary', '0 152 234', 0.1),
            'border:1px solid ' + tokenAlpha('--color-primary', '0 152 234', 0.2),
            'color:' + cssVarSafe('--primary', '#0098ea'),
        ].join(';'));
        newBtn.addEventListener('click', function () {
            // 跨頁「新對話」：以 sessionStorage 旗標通知 SPA 起始即歡迎畫面
            // （cmStartNewChat）。不可用 POST current-session null——API 的
            // ownership 檢查會 403、指標清不掉，SPA 會從伺服器指標還原舊對話。
            try { sessionStorage.setItem('cmStartNewChat', '1'); } catch (_e) {}
            try { localStorage.removeItem('chat_last_session_id'); } catch (_e) {}
            window.location.href = '/static/index.html#chat';
        });
        newWrap.appendChild(newBtn);
        sb.appendChild(newWrap);

        // 3. 雙分頁 tab（與 SPA 同一個 localStorage key，跨頁一致）
        var tabBar = document.createElement('div');
        tabBar.setAttribute('style', 'padding:0 1rem 0.75rem');
        tabBar.setAttribute('role', 'tablist');
        var tabRow = document.createElement('div');
        tabRow.setAttribute('style', 'display:grid;grid-template-columns:1fr 1fr;gap:0.25rem;' +
            'padding:0.25rem;border-radius:0.75rem;background:' +
            cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.12)'));
        var tabHist = makeTabBtn('history', 'history', t('sidebar.tabHistory', 'History'));
        var tabMenu = makeTabBtn('menu', 'grid', t('sidebar.tabMenu', 'Menu'));
        tabRow.appendChild(tabHist);
        tabRow.appendChild(tabMenu);
        tabBar.appendChild(tabRow);
        sb.appendChild(tabBar);
        els.tabHist = tabHist;
        els.tabMenu = tabMenu;

        // 4. 分頁內容區（兩個 panel，同一個 flex-1 容器輪替）
        var panel = document.createElement('div');
        panel.setAttribute('style', 'flex:1;min-height:0;display:flex;flex-direction:column;');
        var histPanel = document.createElement('div');
        histPanel.id = 'site-sidebar-history';
        var menuPanel = document.createElement('div');
        menuPanel.id = 'site-sidebar-menu';
        menuPanel.setAttribute('style', 'flex:1;min-height:0;overflow-y:auto;padding:0 0.5rem 0.75rem');
        panel.appendChild(histPanel);
        panel.appendChild(menuPanel);
        sb.appendChild(panel);
        els.histPanel = histPanel;
        els.menuPanel = menuPanel;

        // 5. footer 用戶卡
        renderFooter(sb);

        applyTab(state.tab, false);
    }

    function makeTabBtn(name, icon, label) {
        var b = document.createElement('button');
        b.type = 'button';
        b.setAttribute('role', 'tab');
        b.dataset.tabName = name;
        b.setAttribute('style', [
            'display:flex', 'align-items:center', 'justify-content:center', 'gap:0.375rem',
            'padding:0.5rem 0', 'border-radius:0.5rem', 'border:none', 'cursor:pointer',
            'font-weight:700', 'font-size:0.72rem', 'transition:all .2s',
            'font-family:inherit',
        ].join(';'));
        b.textContent = (icon === 'history' ? '🕘 ' : '▦ ') + label;
        b.addEventListener('click', function () { applyTab(name, true); });
        return b;
    }

    function styleTabBtn(btn, active) {
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
        btn.style.background = active ? cssVarSafe('--background', '#0d1017') : 'transparent';
        btn.style.color = active ? cssVarSafe('--secondary', '#e8ecf3') : cssVarSafe('--textMuted', '#8b93a3');
        btn.style.boxShadow = active ? '0 1px 3px rgba(0,0,0,0.25)' : 'none';
    }

    function applyTab(name, userAction) {
        state.tab = name === 'menu' ? 'menu' : 'history';
        if (userAction) {
            try { localStorage.setItem('sidebarActiveTab', state.tab); } catch (_e) {}
        }
        styleTabBtn(els.tabHist, state.tab === 'history');
        styleTabBtn(els.tabMenu, state.tab === 'menu');
        els.histPanel.style.display = state.tab === 'history' ? 'flex' : 'none';
        els.menuPanel.style.display = state.tab === 'menu' ? 'block' : 'none';
        if (state.tab === 'history') renderHistory();
        else renderMenu();
    }

    /* ---------- 對話歷史 ---------- */

    function renderHistory() {
        var p = els.histPanel;
        p.setAttribute('style', 'flex:1;min-height:0;overflow-y:auto;padding:0 0.5rem 0.75rem;display:flex');
        p.innerHTML = '<div style="padding:1rem 0.5rem;color:' +
            cssVarSafe('--textMuted', '#8b93a3') + ';font-size:0.78rem;opacity:0.7">' +
            esc(t('common.loading', 'Loading...')) + '</div>';

        ensureUser().then(function () {
            if (!state.user) {
                renderGuestCta(p, 'sidebar.loginToUnlock', 'Connect wallet to unlock everything');
                return;
            }
            var uid = state.user.user_id || state.user.uid || state.user.id;
            if (!uid) { renderEmpty(p); return; }
            api('GET', '/api/chat/sessions?user_id=' + encodeURIComponent(uid))
                .then(function (data) {
                    var sessions = (data && data.sessions) || [];
                    if (!sessions.length) { renderEmpty(p); return; }
                    p.innerHTML = '';
                    sessions.slice(0, 30).forEach(function (s) {
                        var item = document.createElement('button');
                        item.type = 'button';
                        item.setAttribute('style', [
                            'display:block', 'width:100%', 'text-align:left', 'cursor:pointer',
                            'padding:0.55rem 0.6rem', 'border-radius:0.75rem', 'border:none',
                            'background:transparent', 'font-family:inherit',
                            'color:' + cssVarSafe('--textMain', '#d5dae2'),
                        ].join(';'));
                        item.onmouseenter = function () {
                            item.style.background = cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.12)');
                        };
                        item.onmouseleave = function () { item.style.background = 'transparent'; };
                        var when = (s.updated_at || s.created_at || '').slice(0, 10);
                        item.innerHTML =
                            '<div style="font-size:0.8rem;font-weight:600;overflow:hidden;' +
                            'text-overflow:ellipsis;white-space:nowrap">' +
                            esc(s.title || s.name || t('sidebar.noHistory', 'Chat')) + '</div>' +
                            (when ? '<div style="font-size:0.68rem;opacity:0.55;margin-top:0.15rem">' +
                                esc(when) + '</div>' : '');
                        item.addEventListener('click', function () {
                            // 與 SPA switchSession 同款持久化路徑，chat-init 會還原
                            try { localStorage.setItem('chat_last_session_id', s.id); } catch (_e) {}
                            api('POST', '/api/chat/current-session', { session_id: s.id }).catch(function () {});
                            window.location.href = '/static/index.html#chat';
                        });
                        p.appendChild(item);
                    });
                })
                .catch(function () { renderEmpty(p); });
        });
    }

    function renderEmpty(p) {
        p.innerHTML = '<div style="padding:1rem 0.5rem;color:' +
            cssVarSafe('--textMuted', '#8b93a3') + ';font-size:0.78rem;opacity:0.6">' +
            esc(t('sidebar.noHistory', 'No history')) + '</div>';
    }

    function renderGuestCta(p, key, fallback) {
        p.innerHTML = '';
        var a = document.createElement('a');
        a.href = '/static/index.html';
        a.setAttribute('style', [
            'display:flex', 'align-items:center', 'justify-content:center', 'gap:0.4rem',
            'margin:0.5rem 0.25rem', 'padding:0.6rem', 'border-radius:0.75rem',
            'text-decoration:none', 'font-size:0.75rem', 'font-weight:700', 'cursor:pointer',
            'background:' + tokenAlpha('--color-primary', '0 152 234', 0.1),
            'border:1px solid ' + tokenAlpha('--color-primary', '0 152 234', 0.25),
            'color:' + cssVarSafe('--primary', '#0098ea'),
        ].join(';'));
        a.textContent = t(key, fallback);
        p.appendChild(a);
    }

    /* ---------- 功能選單 ---------- */

    function renderMenu() {
        var p = els.menuPanel;
        var items = (window.NavPreferences && NavPreferences.getEnabledItems
            ? NavPreferences.getEnabledItems()
            : (window.NAV_ITEMS || []).filter(function (i) { return i.defaultEnabled; })
        ).slice(0, 5);
        if (!items.length) {
            p.innerHTML = '<div style="padding:1rem 0.5rem;opacity:0.6;font-size:0.78rem;color:' +
                cssVarSafe('--textMuted', '#8b93a3') + '">' +
                esc(t('sidebar.noHistory', 'No items')) + '</div>';
            return;
        }
        p.innerHTML = '';

        var head = document.createElement('div');
        head.setAttribute('style', 'padding:0.35rem 0.6rem 0.5rem;font-size:0.62rem;' +
            'font-weight:800;letter-spacing:0.08em;text-transform:uppercase;opacity:0.45;color:' +
            cssVarSafe('--textMuted', '#8b93a3'));
        head.textContent = t('sidebar.navigation', 'Navigation');
        p.appendChild(head);

        var guest = isGuest();
        items.forEach(function (item) {
            if (item.adminOnly && (!state.user || state.user.role !== 'admin')) return;
            var locked = guest && !isGuestAllowed(item);
            var label = (item.i18nKey && t(item.i18nKey, item.label)) || item.label || item.id;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.setAttribute('style', [
                'display:flex', 'align-items:center', 'gap:0.7rem', 'width:100%',
                'padding:0.6rem 0.65rem', 'border-radius:0.75rem', 'border:none',
                'cursor:pointer', 'font-family:inherit', 'font-size:0.82rem', 'font-weight:500',
                'text-align:left', 'transition:background .2s',
                'color:' + (locked
                    ? tokenAlpha('--color-text-muted', '139 147 163', 0.6)
                    : cssVarSafe('--textMuted', '#8b93a3')),
                'background:transparent',
            ].join(';'));
            btn.onmouseenter = function () {
                btn.style.background = cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.12)');
            };
            btn.onmouseleave = function () { btn.style.background = 'transparent'; };
            btn.innerHTML = '<span style="width:1rem;text-align:center;flex-shrink:0;opacity:0.85">' +
                (item.icon === 'zap' ? '⚡' : item.icon === 'chart-candlestick' ? '🕯' : '•') +
                '</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
                esc(label) + '</span>' + (locked ? '<span style="opacity:0.7">🔒</span>' : '');
            btn.addEventListener('click', function () {
                if (item.id === 'forum') window.location.href = '/static/forum/index.html';
                else window.location.href = '/static/index.html#' + item.id;
                closeDrawer();
            });
            p.appendChild(btn);
        });

        // 「更多分頁」不在子頁做 popover——導向 SPA 設定（偏好編輯的家）
        var more = document.createElement('button');
        more.type = 'button';
        more.setAttribute('style', [
            'display:flex', 'align-items:center', 'gap:0.7rem', 'width:100%',
            'padding:0.6rem 0.65rem', 'border-radius:0.75rem', 'border:none',
            'cursor:pointer', 'font-family:inherit', 'font-size:0.82rem', 'font-weight:500',
            'text-align:left', 'background:transparent',
            'color:' + cssVarSafe('--textMuted', '#8b93a3'),
        ].join(';'));
        more.onmouseenter = function () {
            more.style.background = cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.12)');
        };
        more.onmouseleave = function () { more.style.background = 'transparent'; };
        more.innerHTML = '<span style="width:1rem;text-align:center;flex-shrink:0">▦</span>' +
            '<span style="flex:1">' + esc(t('sidebar.moreTabs', 'More tabs')) + '</span>';
        more.addEventListener('click', function () {
            window.location.href = '/static/index.html#settings';
            closeDrawer();
        });
        p.appendChild(more);
    }

    /* ---------- footer 用戶卡 ---------- */

    function renderFooter(sb) {
        var foot = document.createElement('div');
        foot.setAttribute('style', 'padding:0.9rem 1rem calc(0.9rem + env(safe-area-inset-bottom,0px));' +
            'border-top:1px solid ' + cssVarSafe('--borderSubtle', 'rgba(128,128,128,0.18)'));
        var card = document.createElement('a');
        card.href = '/static/index.html#settings';
        card.setAttribute('style', 'display:flex;align-items:center;gap:0.7rem;' +
            'padding:0.55rem;border-radius:0.75rem;text-decoration:none;color:inherit');
        card.onmouseenter = function () {
            card.style.background = cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.12)');
        };
        card.onmouseleave = function () { card.style.background = 'transparent'; };
        els.userCard = card;
        foot.appendChild(card);
        sb.appendChild(foot);
        renderUserCard();
    }

    function renderUserCard() {
        var card = els.userCard;
        if (!card) return;
        var name = state.user
            ? (state.user.display_name || state.user.username || state.user.user_id || 'User')
            : t('sidebar.loginToUnlock', 'Connect wallet to unlock everything');
        card.innerHTML =
            '<span style="width:2rem;height:2rem;border-radius:9999px;flex-shrink:0;display:flex;' +
            'align-items:center;justify-content:center;font-size:0.7rem;font-weight:800;' +
            'background:' + cssVarSafe('--surfaceHighlight', 'rgba(128,128,128,0.15)') + ';color:' +
            cssVarSafe('--textMuted', '#8b93a3') + '">👤</span>' +
            '<span style="flex:1;min-width:0"><span style="display:block;font-size:0.8rem;' +
            'font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:' +
            cssVarSafe('--textMain', '#d5dae2') + '">' + esc(name) + '</span>' +
            '<span style="display:block;font-size:0.65rem;opacity:0.55">' +
            esc(t('sidebar.settings', 'Settings')) + '</span></span>';
    }

    /* ---------- 使用者判定（AuthManager 優先，否則 /api/user/me） ---------- */

    function ensureUser() {
        if (state.userChecked) return Promise.resolve(state.user);
        state.userChecked = true;
        var am = window.AuthManager;
        if (am && typeof am.isLoggedIn === 'function' && am.isLoggedIn() && am.currentUser) {
            state.user = am.currentUser;
            return Promise.resolve(state.user);
        }
        return api('GET', '/api/user/me')
            .then(function (data) {
                state.user = (data && (data.user || data)) || null;
                if (!state.user || (!state.user.user_id && !state.user.uid && !state.user.id)) {
                    state.user = null; // 401/形狀不對 → 訪客
                }
                renderUserCard();
                return state.user;
            })
            .catch(function () {
                state.user = null;
                renderUserCard();
                return null;
            });
    }

    /* ---------- 桌機讓位 / 手機抽屜 ---------- */

    function updateLayout() {
        var desktop = mq.matches;
        if (desktop) {
            els.sidebar.style.transform = 'translateX(0)';
            els.backdrop.style.opacity = '0';
            els.backdrop.style.pointerEvents = 'none';
            els.burger.style.display = 'none';
            if (els.closeBtn) els.closeBtn.style.display = 'none';
            document.body.style.paddingLeft = WIDTH + 'px';
        } else {
            document.body.style.paddingLeft = '';
            els.burger.style.display = 'inline-flex';
            if (els.closeBtn) els.closeBtn.style.display = 'block';
            closeDrawer();
        }
    }

    function drawerOpen() {
        return els.sidebar.style.transform === 'translateX(0)' && !mq.matches;
    }

    function toggleDrawer() {
        if (drawerOpen()) closeDrawer();
        else openDrawer();
    }

    function openDrawer() {
        if (mq.matches) return;
        els.sidebar.style.transform = 'translateX(0)';
        els.backdrop.style.opacity = '1';
        els.backdrop.style.pointerEvents = 'auto';
        // 抽屜打開時刷新當前分頁（session 清單可能已變）
        applyTab(state.tab, false);
    }

    function closeDrawer() {
        if (mq.matches) return;
        els.sidebar.style.transform = 'translateX(-100%)';
        els.backdrop.style.opacity = '0';
        els.backdrop.style.pointerEvents = 'none';
    }

    /* ---------- 啟動 ---------- */

    function boot() {
        try {
            state.tab = localStorage.getItem('sidebarActiveTab') === 'menu' ? 'menu' : 'history';
        } catch (_e) { /* 預設 history */ }
        buildSkeleton();

        // i18n / auth 為 module（deferred）：DOMContentLoaded 後才就緒；初始化完成
        // 會發 languageChanged / auth:initialized，屆時重渲染文字與使用者態。
        window.addEventListener('languageChanged', function () {
            renderContent();
            updateLayout();
        });
        window.addEventListener('auth:initialized', function () {
            state.userChecked = false;
            state.user = null;
            ensureUser().then(function () { renderContent(); });
        });
        window.addEventListener('auth-success', function () {
            state.userChecked = false;
            state.user = null;
            ensureUser().then(function () { renderContent(); });
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeDrawer();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
