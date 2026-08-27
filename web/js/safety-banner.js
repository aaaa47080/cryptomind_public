// ========================================
// safety-banner.js — chat 的地址健診 banner
// 2026-08-24 DANNY 回報：這條 banner 常駐在聊天最上方又沒有關閉鈕，
// 使用者只能一直看著它。加一個叉叉 + localStorage 記住選擇。
// 訪客也看得到 banner，所以用 localStorage（不綁使用者）。
// ========================================

(function () {
    'use strict';

    var STORAGE_KEY = 'safetyBannerDismissed';
    var BANNER_ID = 'safety-chat-banner';

    function isDismissed() {
        try {
            return localStorage.getItem(STORAGE_KEY) === '1';
        } catch (_e) {
            // 無痕模式 / storage 被封鎖 → 當作沒關過，banner 照顯示
            return false;
        }
    }

    function remember() {
        try {
            localStorage.setItem(STORAGE_KEY, '1');
        } catch (_e) {
            // 記不住就算了，至少這次關得掉
        }
    }

    function hide(banner) {
        banner.classList.add('hidden');
        banner.setAttribute('aria-hidden', 'true');
    }

    function init() {
        var banner = document.getElementById(BANNER_ID);
        if (!banner) return;

        if (isDismissed()) {
            hide(banner);
            return;
        }

        var closeBtn = banner.querySelector('[data-safety-banner-close]');
        if (!closeBtn) return;
        closeBtn.addEventListener('click', function (e) {
            e.preventDefault();
            remember();
            hide(banner);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
