# AGENTS.md — web/

> SPA frontend (Vanilla JS + Tailwind + TON Connect SDK). See root `AGENTS.md` for stack / theme common rules.

## BUILD (Vite at repo root, NOT inside `web/`)

- `vite.config.js`: `root: 'web'`, `base: '/static/'`, `outDir: '../dist/static'`, `sourcemap: true`
- `package.json` scripts: `build` (= `build:css` + `vite build`), `dev` (= `vite`), `preview`
- Manual chunks: `forum-app.js` → `forum`; `forum/{index,post,create,dashboard,report}.js` → `forum-*`
- Dev server proxies: `/api`, `/ws` (ws), `/static` → `http://localhost:8080`
- Tailwind: `npm run build:css` minifies `web/css/tailwind-src.css` → `web/css/tailwind-built.css`; `npm run watch:css` watches `web/css/main.css`
- `devDependencies`: vite ^8.0.8, tailwindcss ^3.4.19, @playwright/test ^1.58.2, vite-plugin-pwa ^1.3.0
- No `node_modules` inside `web/`; only at repo root. Raw `web/js/*.js` are Vite dev targets.

### CDN Dependencies (`index.html`)

`lucide@0.577.0`, `i18next@23.7.6`, `markdown-it@14.1.0`, Chart.js@4.4.1, TON Connect SDK. (TradingView Lightweight Charts IS loaded via CDN in `index.html` (`lightweight-charts@4.1.0`) — do not add a second copy.)

## DIRECTORY MAP (106 .js modules in js/)

| Path | Role |
|------|------|
| `index.html` | SPA shell, all tabs inline |
| `styles.css` (1476) | CSS variables for both light & dark themes (single source of color tokens; see THEME) |
| `js/main.js` | Entry; lazy code-splitting via dynamic `import()` per tab (see `spa.js` `_TAB_MODULES`) |
| `js/spa.js` | `switchTab()`, hash routing, `VALID_TABS`, `_TAB_MODULES` (per-tab lazy-import map) |
| `js/nav-config.js` | `NAV_ITEMS` nav definitions; per-user visible tabs MIN 3 / MAX 5 (localStorage prefs) |
| `js/store.js`, `js/api-client.js`, `js/utils.js` | `AppStore` (pub/sub), `AppAPI`, `AppUtils` |
| `js/i18n.js` + `js/i18n/{en,zh-TW}.json` | i18next |
| `js/market-ws.js`, `js/market-chart.js` | WS `/ws/klines`, Chart.js |
| `js/ton-auth.js`, `js/global-nav.js` | `window.safeTonLogin` (TON Connect), draggable nav |
| `js/components/` | Tab renderers (`tab-*.js`) + `core.js` `Components.inject()` |
| `css/` | Tailwind source + pre-built (`tailwind-src.css`, `main.css`, `tailwind-built.css`) |
| `forum/` (7), `scam-tracker/` (3), `governance/` (1), `legal/` (3) | Multi-page HTML |

## TAB SYSTEM (21 VALID_TABS; 21 NAV_ITEMS)

`VALID_TABS` in `spa.js`:
```
chat, crypto, twstock, usstock, commodity, forex,
hkstock, astock, jpstock, instock, krstock,
wallet, wallet-monitor, trust, friends, forum,
settings, admin, ai-studio, discover, studio
```
(`safety` tab 已於 2026-08-18 死代碼清理移除——`safetyTab.js`、`tab-safety.js`、
nav-config 項目、index.html 的 scam-tracker.js 直載一併刪除；詐騙檢測功能由
獨立頁 `web/scam-tracker/` 提供。)

Pattern: each tab has a `js/components/tab-*.js` mapped to a `#{tab}-tab` container, rendered into it.
Component structure: `CommodityTab`, `ForexTab`, `HKStockTab`, etc., all use the `Tab.showPicker()`, `Tab.refreshMarketWatch()`, `Tab.backToMarket()` three-method pattern.

## I18N
- 2 langs: `en`, `zh-TW` (i18next)
- `data-i18n="key"` attribute; switch fires `languageChanged` event
- Detection: `localStorage.selectedLanguage` → `navigator.language` → fallback `en`

## REAL-TIME

- WS `/ws/klines` (`market-ws.js`) — klineWebSocket, auto-reconnect max 10/3s
- SSE `/api/chat/stream` (`app.js` EventSource) — AI chat streaming
- WS — `messages.js`, `notification-service.js`, `friends.js`

## THEME (dual-theme: light + dark) — token source of truth in `docs/DESIGN_SYSTEM.md`

The app is **dual-theme (light is the default)**, not dark-only. Tokens are CSS-variable-backed via Tailwind `rgb(var(...) / <alpha-value>)`, defined as color channels in `tailwind.config.js`, with actual values provided by `web/styles.css` (`:root` = light, `html.dark` = dark).

- Toggle: `darkMode: 'class'` on `<html>`. `web/js/early-init.js` reads `localStorage.selectedTheme` on first paint to avoid FOUC; `web/js/components/ThemeSwitcher.js` offers Light / Dark / System.
- Default: **light**.

Token values (light | dark):
- `background`: `#F5F5F7` (warm gray, not pure white) | `#14161F`
- `surface`: `#FFFFFF` | `#1D202B`
- `surfaceHighlight`: `#EEEEF0` | `#292D38`
- `textMain`: `#17171C` (darkened for AA) | `#FFFDF9`
- `textMuted`: `#4A4C54` (deepened to AAA) | `#A7A9B2`
- `primary`: `#2563EB` (the only accent; shared by both themes, deepened so white-on-blue meets AA)
- `success`: `#16A34A` · `danger`: `#DC2626` (shared by both themes)

Semantic colors are used via low-opacity background + full-color text (e.g. `bg-success/10 text-success`), not solid fills. Solid `bg-primary` is reserved for the primary CTA only.

- **No `warning` / `info` token** — for warnings use Tailwind's built-in `amber-*`; for info use `text-primary`.
- Fonts: `Inter` (body) + `Inter Tight` (display headings) + monospace for code (top.co-style editorial typography; see `docs/DESIGN_SYSTEM.md`).

## KEY PATTERNS
- `AppStore` (pub/sub) · `AppUtils` · `AppAPI` — store/utils/api-client
- Class-based tabs: `CommodityTab`, `ForexTab`, `HKStockTab` unified pattern
- `Components.inject()` — async injection + `requestAnimationFrame` double-tap

## ANTI-PATTERNS

- `js/components/core.js`: `requestAnimationFrame` double-tap is a workaround — a MutationObserver or Web Components would be better
- Multiple `tab-*.js` files each redefine the same `showPicker`/`refreshMarketWatch` — should be extracted into a base class
- No TypeScript — lacks type safety, relies on runtime testing

## SEE ALSO
- Root `AGENTS.md` · `api/AGENTS.md` · `core/AGENTS.md`
