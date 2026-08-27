// ========================================
// legal.js - 法律與條款頁面 Modal 邏輯
// ========================================

const LEGAL_PAGE_MAP = {
    terms: 'terms-of-service.html',
    privacy: 'privacy-policy.html',
    guidelines: 'community-guidelines.html',
};

async function showLegalPage(type) {
    const filename = LEGAL_PAGE_MAP[type];
    if (!filename) return;

    const modal = document.getElementById('legal-modal');
    const contentArea = document.querySelector('#legal-content > div');
    const titleEl = document.getElementById('legal-title');
    const backEl = document.getElementById('legal-back-text');

    // Show modal with loading
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    contentArea.innerHTML =
        '<div class="flex items-center justify-center py-20"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div></div>';

    const lang = window.I18n ? window.I18n.getLanguage() : 'en';
    backEl.textContent = window.I18n ? window.I18n.t('legal.back') : (lang === 'zh-TW' ? 'Back' : 'Back');

    try {
        const res = await fetch(`/static/legal/${filename}`);
        const html = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        const zhDiv = doc.getElementById('content-zh');
        const enDiv = doc.getElementById('content-en');
        const singleContent = doc.getElementById('content');

        if (zhDiv && enDiv) {
            contentArea.innerHTML = '';
            const zhClone = zhDiv.cloneNode(true);
            const enClone = enDiv.cloneNode(true);
            zhClone.id = 'legal-content-zh';
            enClone.id = 'legal-content-en';
            contentArea.appendChild(zhClone);
            contentArea.appendChild(enClone);
            _updateLegalLanguage(lang);
        } else if (singleContent) {
            contentArea.innerHTML = '';
            const clone = singleContent.cloneNode(true);
            clone.id = 'legal-content-single';
            contentArea.appendChild(clone);
            _applyDataLang(contentArea, lang);
        } else {
            contentArea.innerHTML =
                '<p class="text-center text-textMuted py-20">Content not found.</p>';
            return;
        }

        const titles = {
            terms: { 'zh-TW': '服務條款', 'zh-CN': '服务条款', en: 'Terms of Service', ru: 'Условия обслуживания' },
            privacy: { 'zh-TW': '隱私權政策', 'zh-CN': '隐私政策', en: 'Privacy Policy', ru: 'Политика конфиденциальности' },
            guidelines: { 'zh-TW': '社群守則', 'zh-CN': '社群守则', en: 'Community Guidelines', ru: 'Правила сообщества' },
        };
        titleEl.textContent = (titles[type] && titles[type][lang]) || (doc.getElementById('nav-title')?.textContent || '');
        modal.dataset.type = type;
    } catch (e) {
        contentArea.innerHTML = `<p class="text-center text-danger py-20">Failed to load: ${window.SecurityUtils ? window.SecurityUtils.escapeHTML(e.message || '') : (e.message || '')}</p>`;
    }

    if (window.AppUtils) window.AppUtils.refreshIcons();
}

function _applyDataLang(container, lang) {
    if (!container) return;
    const attr = lang === 'zh-TW' ? 'data-zh' : 'data-en';
    container.querySelectorAll('[data-zh][data-en]').forEach((el) => {
        el.textContent = el.getAttribute(attr) || el.textContent;
    });
}

function _updateLegalLanguage(lang) {
    const zh = document.getElementById('legal-content-zh');
    const en = document.getElementById('legal-content-en');
    const single = document.getElementById('legal-content-single');

    if (single) {
        _applyDataLang(single.parentElement, lang);
    } else if (zh && en) {
        if (lang === 'zh-TW') {
            zh.classList.remove('hidden');
            en.classList.add('hidden');
        } else {
            zh.classList.add('hidden');
            en.classList.remove('hidden');
        }
    }

    const backEl = document.getElementById('legal-back-text');
    if (backEl) backEl.textContent = window.I18n ? window.I18n.t('legal.back') : (lang === 'zh-TW' ? 'Back' : 'Back');

    const titleEl = document.getElementById('legal-title');
    const modal = document.getElementById('legal-modal');
    const type = modal?.dataset?.type;
    if (titleEl && type) {
        const titles = {
            terms: { 'zh-TW': '服務條款', 'zh-CN': '服务条款', en: 'Terms of Service', ru: 'Условия обслуживания' },
            privacy: { 'zh-TW': '隱私權政策', 'zh-CN': '隐私政策', en: 'Privacy Policy', ru: 'Политика конфиденциальности' },
            guidelines: { 'zh-TW': '社群守則', 'zh-CN': '社群守则', en: 'Community Guidelines', ru: 'Правила сообщества' },
        };
        titleEl.textContent = (titles[type] && titles[type][lang]) || '';
    }
}

function closeLegalModal() {
    const modal = document.getElementById('legal-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    const contentArea = document.querySelector('#legal-content > div');
    if (contentArea) contentArea.innerHTML = '';
    delete modal.dataset.type;
}

// Re-render legal content on language change
window.addEventListener('languageChanged', e => {
    const modal = document.getElementById('legal-modal');
    if (modal && !modal.classList.contains('hidden')) {
        const lang = e.detail?.language || (window.I18n ? window.I18n.getLanguage() : 'en');
        _updateLegalLanguage(lang);
    }
});

window.showLegalPage = showLegalPage;
window.closeLegalModal = closeLegalModal;

export { LEGAL_PAGE_MAP, showLegalPage, closeLegalModal };
