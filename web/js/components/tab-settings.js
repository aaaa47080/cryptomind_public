// Auto-generated from components.js split
// Tab: Settings - original lines 733-1100
window.Components = window.Components || {};
window.Components.settings = `
    <div class="max-w-2xl mx-auto px-1 sm:px-0">
             <h2 class="font-serif text-3xl text-secondary mb-8" data-i18n="settings.title">Settings</h2>

             <div class="space-y-10">
                <!-- User Profile Section -->
                <div id="settings-profile-card" class="${SECTION_CARD_PRIMARY}">
                    <div class="flex items-start justify-between gap-3 mb-6">
                        <div class="flex items-center gap-4 min-w-0">
                            <div class="w-16 h-16 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center text-background font-bold text-2xl shadow-lg shadow-primary/20 shrink-0" id="profile-avatar">
                                U
                            </div>
                            <div class="min-w-0">
                                <div class="flex items-center gap-2">
                                    <h3 class="text-xl font-serif text-secondary truncate" id="profile-username">User</h3>
                                    <button id="btn-edit-display-name" data-click="toggleEditDisplayName"
                                        class="text-textMuted/50 hover:text-primary transition shrink-0"
                                        title="Edit nickname">
                                        <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                                    </button>
                                </div>
                                <!-- 暱稱編輯列（預設隱藏，點鉛筆後顯示） -->
                                <div id="display-name-editor" class="hidden mt-2 flex items-center gap-2">
                                    <input type="text" id="display-name-input" maxlength="20"
                                        class="flex-1 min-w-0 bg-background border border-borderLight rounded-lg px-3 py-1.5 text-sm text-secondary focus:border-primary focus:outline-none"
                                        placeholder="Your nickname (1-20 chars)">
                                    <button id="btn-save-display-name" data-click="saveDisplayName"
                                        class="px-3 py-1.5 bg-primary text-background text-xs font-bold rounded-lg hover:opacity-90 transition shrink-0"
                                        data-i18n="settings.profile.save">Save</button>
                                </div>
                                <p id="display-name-cooldown" class="hidden mt-1 text-[10px] text-amber-600/80"></p>
                                <p class="text-xs text-textMuted font-mono break-all" id="profile-uid">UID: --</p>
                                <div class="mt-1 flex items-center gap-2">
                                    <span class="px-2 py-0.5 rounded-md bg-surfaceHighlight text-[10px] text-textMuted border border-borderSubtle uppercase" id="profile-method">PASSWORD</span>
                                </div>
                            </div>
                        </div>
                        <div id="premium-status-badge" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-surfaceHighlight text-textMuted shrink-0 whitespace-nowrap">
                            <i data-lucide="loader" class="w-3 h-3 animate-spin"></i>
                            <span data-i18n="settings.wallet.loading">Loading</span>
                        </div>
                    </div>

                    <!-- TEST MODE: Multi-User Switcher (預設隱藏，由 auth.js 根據 API 控制) -->
                    <div id="dev-user-switcher" class="mt-4 pt-4 border-t border-borderSubtle hidden">
                        <p class="text-[10px] text-textMuted uppercase tracking-wider mb-2 font-bold opacity-50" data-i18n="settings.profile.devSwitchUser">Dev: Switch User</p>
                        <div class="grid grid-cols-2 gap-2">
                            <button data-click="handleDevSwitchUser" data-click-arg="test-user-001" class="py-2 bg-surfaceHighlight hover:bg-primary/20 hover:text-primary rounded-lg text-xs font-mono transition border border-borderSubtle">
                                User 001
                            </button>
                            <button data-click="handleDevSwitchUser" data-click-arg="test-user-002" class="py-2 bg-surfaceHighlight hover:bg-accent/20 hover:text-accent rounded-lg text-xs font-mono transition border border-borderSubtle">
                                User 002
                            </button>
                            <button data-click="handleDevSwitchUser" data-click-arg="test-user-003" class="py-2 bg-surfaceHighlight hover:bg-success/20 hover:text-success rounded-lg text-xs font-mono transition border border-borderSubtle">
                                User 003 (PREMIUM)
                            </button>
                            <button data-click="handleDevSwitchUser" data-click-arg="test-user-004" class="py-2 bg-surfaceHighlight hover:bg-amber-500/20 hover:text-amber-600 rounded-lg text-xs font-mono transition border border-borderSubtle">
                                User 004 (PREMIUM)
                            </button>
                        </div>
                    </div>

                    <!-- TEST MODE: Tier Switcher (僅測試模式顯示) -->
                    <div id="test-tier-switcher" class="mt-4 pt-4 border-t border-borderSubtle hidden">
                        <div class="flex items-center justify-between mb-3">
                            <p class="text-[10px] text-primary uppercase tracking-wider font-bold" data-i18n="settings.testModeSwitchTier">TEST MODE: Switch Membership Tier</p>
                            <span id="current-test-tier" class="px-2 py-0.5 rounded-md bg-primary/20 text-primary text-[10px] font-mono font-bold">PREMIUM</span>
                        </div>
                        <p class="text-[10px] text-textMuted mb-3" data-i18n="settings.testModeTierDesc">Test different membership tier permissions (no charges)</p>
                        <div class="grid grid-cols-2 gap-2">
                            <button data-click="handleSwitchTestTier" data-click-arg="free" class="test-tier-btn py-2 bg-surfaceHighlight hover:bg-textMuted/10 rounded-lg text-xs font-mono transition border border-borderSubtle" data-tier="free">
                                FREE
                            </button>
                            <button data-click="handleSwitchTestTier" data-click-arg="premium" class="test-tier-btn py-2 bg-surfaceHighlight hover:bg-primary/20 hover:text-primary rounded-lg text-xs font-mono transition border border-primary/20 text-primary" data-tier="premium">
                                PREMIUM
                            </button>
                        </div>
                    </div>

                    <button data-click="handleLogout" class="w-full py-3 bg-surfaceHighlight hover:bg-danger/10 text-textMuted hover:text-danger border border-borderSubtle hover:border-danger/20 font-bold rounded-xl transition flex items-center justify-center gap-2 mt-4">
                        <i data-lucide="log-out" class="w-4 h-4"></i>
                        <span data-i18n="settings.profile.logout">Logout</span>
                    </button>
                </div>

                <!-- TON Wallet Section -->
                <div id="settings-wallet-card" class="${SECTION_CARD_PRIMARY}">
                    <div class="flex items-center justify-between mb-6">
                        <div class="${CARD_HEADER_ROW_CLASS}">
                            <div id="settings-wallet-icon" class="${HERO_ICON_BOX_CLASS} text-primary">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="w-5 h-5">
                                    <path d="M12 2L21 12L12 22L3 12L12 2Z" stroke-linejoin="round"/>
                                </svg>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-primary" data-i18n="settings.wallet.title">TON Wallet</h3>
                                <p class="text-xs text-textMuted" data-i18n="settings.wallet.description">Connect your TON wallet for transactions</p>
                            </div>
                        </div>
                        <div id="settings-wallet-status-badge" class="${STATUS_BADGE_MUTED_CLASS}">
                            <i data-lucide="loader" class="w-3 h-3 animate-spin"></i>
                            <span data-i18n="settings.wallet.loading">Loading</span>
                        </div>
                    </div>

                    <div id="settings-wallet-content" class="space-y-4">
                        <div id="wallet-not-linked" class="hidden">
                            <div class="${INFO_PANEL_CLASS}">
                                <div class="flex items-start gap-3">
                                    <i data-lucide="info" class="w-4 h-4 text-primary/60 mt-0.5 flex-shrink-0"></i>
                                    <div>
                                        <p class="text-sm text-textMuted leading-relaxed mb-1" data-i18n="settings.wallet.reloginHint">Your account is not yet linked to a TON wallet address. Please log in again to complete the link.</p>
                                        <p class="text-xs text-textMuted/60" data-i18n="settings.wallet.reloginDesc">After re-logging in, you can make payments, upgrade membership, and receive tips.</p>
                                    </div>
                                </div>
                                <button data-click="handleLogout" class="w-full mt-4 py-3 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 font-bold rounded-xl transition flex items-center justify-center gap-2">
                                    <i data-lucide="log-in" class="w-4 h-4"></i>
                                    <span data-i18n="settings.wallet.reloginButton">Re-login to Link Wallet</span>
                                </button>
                            </div>
                        </div>

                        <div id="wallet-linked" class="hidden">
                            <div class="bg-success/5 rounded-xl p-4 border border-success/10">
                                <div class="flex items-center gap-3">
                                    <div class="w-10 h-10 rounded-full bg-success/20 flex items-center justify-center">
                                        <i data-lucide="check-circle" class="w-5 h-5 text-success"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm font-bold text-success" data-i18n="settings.wallet.connected">TON Wallet Connected</p>
                                        <p id="settings-wallet-username" class="text-xs text-textMuted font-mono">@username</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                 <!-- LLM Configuration -->
                <div id="settings-llm-card" class="${SECTION_CARD_PRIMARY}">
                    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
                        <div class="${CARD_HEADER_ROW_CLASS}">
                            <div class="${HERO_ICON_BOX_CLASS}">
                                <i data-lucide="brain" class="w-5 h-5 text-primary"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-primary" data-i18n="settings.ai.title">AI Intelligence</h3>
                                <p class="text-xs text-textMuted" data-i18n="settings.ai.description">Configure your LLM provider</p>
                            </div>
                        </div>
                        <div id="llm-status-badge" class="${STATUS_BADGE_CLASS} self-start sm:self-auto">
                        </div>
                    </div>

                    <div class="space-y-5">
                        <!-- 已綁定模型清單：金鑰綁定一次後，在這裡一鍵切換要使用的模型（renderBoundModels() 動態渲染） -->
                        <div class="space-y-2">
                            <label class="block text-xs font-bold text-textMuted uppercase tracking-wider mb-2" data-i18n="settings.ai.boundModels">Bound Models</label>
                            <div id="llm-bound-models" class="space-y-2"></div>
                            <p class="text-xs leading-5 text-textMuted/75" data-i18n="settings.ai.boundModelsHint">Tap "Use" to switch models. Keys only need to be bound once.</p>
                        </div>

                        <div class="border-t border-borderSubtle pt-5">
                            <h4 class="text-sm font-bold text-secondary" data-i18n="settings.ai.addBinding">Add Model Binding</h4>
                        </div>

                        <div class="space-y-2">
                            <label class="block text-xs font-bold text-textMuted uppercase tracking-wider mb-2" data-i18n="settings.ai.provider">Provider</label>
                            <!-- 選項由 populateProviderSelect() 依 /api/model-config 動態填充；
                                 下面僅為初次渲染的 fallback。新增 provider 請改後端 MODEL_CONFIG。 -->
                            <select id="llm-provider-select" data-change-action="llmProviderChange" class="w-full bg-background border border-borderSubtle rounded-2xl px-4 py-3.5 text-secondary outline-none focus:border-primary/50 transition appearance-none">
                                <option value="openai">OpenAI</option>
                                <option value="google_gemini">Google Gemini</option>
                                <option value="openrouter">OpenRouter</option>
                            </select>
                            <p class="text-xs leading-5 text-textMuted/75" data-i18n="settings.ai.providerHint">Pick the AI provider you want to bind first, then choose the model to use.</p>
                        </div>

                        <div class="space-y-2">
                            <label class="block text-xs font-bold text-textMuted uppercase tracking-wider mb-2" data-i18n="settings.ai.model">Model</label>
                            <select id="llm-model-select" class="w-full bg-background border border-borderSubtle rounded-2xl px-4 py-3.5 text-secondary outline-none focus:border-primary/50 transition appearance-none" style="display: block;">
                            <!-- Models loaded dynamically via updateAvailableModels() -->
                            </select>
                            <input type="text" id="llm-model-input" class="w-full bg-background border border-borderSubtle rounded-2xl px-4 py-3.5 text-sm text-secondary outline-none focus:border-primary/50 transition mt-3"
                                   placeholder="e.g., openai/gpt-4o, anthropic/claude-3.5-sonnet" data-i18n="settings.ai.modelPlaceholder" data-i18n-attr="placeholder"
                                   style="display: none;" />
                            <p id="llm-model-hint" class="text-xs leading-5 text-textMuted/75" data-i18n="settings.ai.modelHint">Select a model first, then enter the corresponding API key for a smoother flow.</p>
                        </div>

                        <div class="space-y-2">
                            <label class="block text-xs font-bold text-textMuted uppercase tracking-wider mb-2" data-i18n="settings.ai.apiKey">API Key</label>
                            <div class="flex gap-2 items-stretch">
                                <input type="password" id="llm-api-key-input" class="flex-1 min-w-0 bg-background border border-borderSubtle rounded-2xl px-4 py-3 text-secondary outline-none focus:border-primary/50 font-mono text-sm disabled:cursor-not-allowed disabled:opacity-50" placeholder="sk-..." disabled>
                                <button id="test-llm-key-btn" data-click="testLLMKey" class="shrink-0 px-4 py-3 bg-surfaceHighlight hover:bg-surfaceHighlight text-secondary rounded-2xl transition font-bold text-xs whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed" disabled data-i18n="settings.ai.test">TEST</button>
                            </div>
                            <p id="llm-key-status" class="text-xs leading-5 text-textMuted/75" data-i18n="settings.ai.keyStatusHint">Please select a provider and model before entering the API key.</p>
                            <p id="llm-binding-status" class="text-xs leading-5 text-success hidden"></p>
                        </div>

                        <button id="save-llm-key-btn" data-click="saveLLMKey" class="w-full py-3.5 bg-primary text-background font-bold rounded-xl shadow-lg shadow-primary/10 opacity-50 cursor-not-allowed transition mt-2" disabled data-i18n="settings.ai.saveConfig">
                            Save AI Configuration
                        </button>
                    </div>
                </div>

                <!-- 我的 AI（AI Studio 入口；Memory/Skill/Tool 已搬入 AI Studio 統一管理） -->
                <div id="settings-my-ai-card" class="${SECTION_CARD_DEFAULT}">
                    <div class="flex items-center justify-between mb-3">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-xl flex items-center justify-center" style="background: rgba(59,130,246,0.1);">
                                <i data-lucide="bot" class="w-5 h-5" style="color: rgb(59,130,246);"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-secondary" data-i18n="settings.myAI.title">我的 AI</h3>
                                <p class="text-xs text-textMuted" data-i18n="settings.myAI.desc">Agents、Presets、Skills、Memory 與 Tools 的管理中心</p>
                            </div>
                        </div>
                        <button id="btn-open-ai-studio" class="text-xs px-4 py-2 rounded-lg bg-primary/20 text-primary hover:bg-primary/30 transition flex items-center gap-1.5">
                            <span data-i18n="settings.myAI.open">前往 AI Studio</span>
                            <i data-lucide="arrow-right" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
                        <div class="rounded-lg bg-background/50 px-2 py-2">
                            <p class="text-lg font-semibold text-secondary" id="myai-count-agents">–</p>
                            <p class="text-[10px] text-textMuted" data-i18n="settings.myAI.agentCount">官方 Agents</p>
                        </div>
                        <div class="rounded-lg bg-background/50 px-2 py-2">
                            <p class="text-lg font-semibold text-secondary" id="myai-count-presets">–</p>
                            <p class="text-[10px] text-textMuted" data-i18n="settings.myAI.presetCount">Presets</p>
                        </div>
                        <div class="rounded-lg bg-background/50 px-2 py-2">
                            <p class="text-lg font-semibold text-secondary" id="myai-count-skills">–</p>
                            <p class="text-[10px] text-textMuted" data-i18n="settings.myAI.skillCount">Skills</p>
                        </div>
                        <div class="rounded-lg bg-background/50 px-2 py-2">
                            <p class="text-lg font-semibold text-secondary" id="myai-count-memories">–</p>
                            <p class="text-[10px] text-textMuted" data-i18n="settings.myAI.memoryCount">Memories</p>
                        </div>
                    </div>
                </div>



                <!-- Telegram Integration -->
                <div id="settings-telegram-card" class="${SECTION_CARD_DEFAULT}">
                    <div class="flex items-center justify-between mb-6">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-xl flex items-center justify-center" style="background: rgba(0,152,234,0.1);">
                                <svg viewBox="0 0 24 24" fill="none" class="w-5 h-5">
                                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="#229ED9"/>
                                    <path d="M12 2c-2.5 0-5 2-5 5 0 1.5.5 2.5 1 3.5.5 1 1.5 2 2 2s1-.5 1.5-1c.5-.5 1-1 2-1s1.5.5 2 1c.5.5.5 1.5.5 2 0 1-.5 2-1 3-.5 1-2 2-3 2s-2-.5-3-1c-1-.5-2-1.5-3-3s-1-4 0-5 2-2 3-2 2 1 3 2c1 1 1.5 2 2 2" fill="white"/>
                                </svg>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-primary" data-i18n="telegram.title">Telegram</h3>
                                <p class="text-xs text-textMuted" data-i18n="telegram.not_bound_desc">Link your Telegram account for notifications</p>
                            </div>
                        </div>
                        <div id="telegram-status-badge" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-surfaceHighlight text-textMuted">
                            <i data-lucide="loader" class="w-3 h-3 animate-spin"></i>
                            <span>Loading</span>
                        </div>
                    </div>
                    <div id="telegram-link-content">
                        <!-- Dynamically rendered by TelegramLinkApp -->
                    </div>
                </div>

                <!-- Navigation Customization -->
                <div class="${SECTION_CARD_SECONDARY}">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <div class="${HERO_ICON_BOX_CLASS}">
                                <i data-lucide="layout-grid" class="w-5 h-5 text-primary"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-primary" data-i18n="settings.navigation.title">Navigation Customization</h3>
                                <p class="text-xs text-textMuted" data-i18n="settings.navigation.description">Customize your bottom navigation bar</p>
                            </div>
                        </div>
                        <button data-click="featureMenuOpen" class="px-4 py-2 bg-primary/10 hover:bg-primary/20 text-primary rounded-xl transition font-bold text-sm flex items-center gap-2">
                            <i data-lucide="settings-2" class="w-4 h-4"></i>
                            <span data-i18n="settings.navigation.customize">Customize</span>
                        </button>
                    </div>
                    <div class="mt-4 ${INFO_PANEL_CLASS}">
                        <p class="text-sm text-textMuted leading-relaxed">
                            <i data-lucide="info" class="w-4 h-4 inline-block mr-1 opacity-60"></i>
                            <span data-i18n="settings.navigation.info">Choose which features appear in your bottom navigation bar. At least 2 items must be enabled.</span>
                        </p>
                    </div>
                </div>


                <!-- Premium Membership -->
                <div class="${SECTION_CARD_DEFAULT}">
                    <div class="flex items-center gap-3 mb-6">
                        <div class="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                            <i data-lucide="star" class="w-5 h-5 text-background"></i>
                        </div>
                        <div>
                            <h3 class="text-lg font-serif text-primary" data-i18n="settings.premium.title">Premium Membership</h3>
                            <p class="text-xs text-textMuted" data-i18n="settings.premium.description">Unlock advanced features</p>
                        </div>
                    </div>

                    <div class="space-y-4">
                        <div class="${INFO_PANEL_CLASS}">
                            <p class="text-sm text-textMuted leading-relaxed">
                                <i data-lucide="crown" class="w-4 h-4 inline-block mr-1 text-yellow-400"></i>
                                <span data-i18n="settings.premium.benefits">Premium members enjoy:</span>
                            </p>
                            <ul class="text-xs text-textMuted mt-2 space-y-1 ml-5">
                                <li data-i18n="settings.premium.benefit1">Unlimited posting</li>
                                <li data-i18n="settings.premium.benefit2">Unlimited replies</li>
                                <li data-i18n="settings.premium.benefit3">Early access to new features</li>
                                <li data-i18n="settings.premium.benefit4">Exclusive premium badge</li>
                            </ul>
                        </div>

                        <button data-click="handleUpgradeToPremium" class="w-full py-3.5 bg-primary hover:bg-primary/90 text-background font-bold rounded-xl transition flex items-center justify-center gap-2 upgrade-premium-btn">
                            <i data-lucide="zap" class="w-4 h-4"></i>
                            <span><span data-i18n="settings.premium.upgradeButton">Upgrade to Premium -</span> <span data-price="premium"><i data-lucide="loader" class="w-3 h-3 animate-spin"></i></span></span>
                        </button>

                        <p class="text-[10px] text-textMuted/60 text-center" data-i18n="settings.premium.oneTimePayment">Monthly subscription. Renew to keep Premium access.</p>
                    </div>
                </div>

                <!-- Feedback -->
                <div class="${SECTION_CARD_SECONDARY}">
                    <div class="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                        <div class="${CARD_HEADER_ROW_CLASS}">
                            <div class="${HERO_ICON_BOX_CLASS}">
                                <i data-lucide="message-square-heart" class="w-5 h-5 text-primary"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-serif text-primary" data-i18n="settings.feedback.title">Feedback</h3>
                                <p class="text-xs text-textMuted" data-i18n="settings.feedback.description">Share your thoughts, suggestions, and product experience</p>
                            </div>
                        </div>
                        <button data-click="openFeedbackModal" class="px-4 py-3 bg-primary/10 hover:bg-primary/20 text-primary rounded-2xl transition font-bold text-sm flex items-center justify-center gap-2 sm:min-w-[180px]">
                            <i data-lucide="message-square-plus" class="w-4 h-4"></i>
                            <span data-i18n="settings.feedback.button">Open Feedback</span>
                        </button>
                    </div>
                    <div class="mt-4 ${INFO_PANEL_CLASS}">
                        <p class="text-sm text-textMuted leading-relaxed">
                            <i data-lucide="sparkles" class="w-4 h-4 inline-block mr-1 opacity-60"></i>
                            <span data-i18n="settings.feedback.hint">Tell us what is working well, what feels confusing, or what you want to see next.</span>
                        </p>
                    </div>
                </div>

                <!-- About & Legal -->
                <div class="${SECTION_CARD_SECONDARY}">
                    <div class="${CARD_HEADER_ROW_CLASS} mb-6">
                        <div class="${HERO_ICON_BOX_CLASS}">
                            <i data-lucide="info" class="w-5 h-5 text-primary"></i>
                        </div>
                        <div>
                            <h3 class="text-lg font-serif text-primary" data-i18n="settings.legal.title">About & Legal</h3>
                            <p class="text-xs text-textMuted" data-i18n="settings.legal.description">Terms, Privacy, and Community Guidelines</p>
                        </div>
                    </div>

                    <div class="space-y-3">
                        <a href="javascript:void(0)" data-click="showLegalPage" data-click-arg="terms" class="block w-full p-4 bg-background/50 hover:bg-background rounded-xl border border-borderSubtle hover:border-primary/20 transition group cursor-pointer">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-3">
                                    <i data-lucide="file-text" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                                    <div>
                                        <p class="text-sm font-medium text-secondary" data-i18n="settings.legal.termsTitle">Terms of Service</p>
                                        <p class="text-xs text-textMuted" data-i18n="settings.legal.termsDesc">Usage rules and policies</p>
                                    </div>
                                </div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                            </div>
                        </a>

                        <a href="javascript:void(0)" data-click="showLegalPage" data-click-arg="privacy" class="block w-full p-4 bg-background/50 hover:bg-background rounded-xl border border-borderSubtle hover:border-primary/20 transition group cursor-pointer">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-3">
                                    <i data-lucide="shield" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                                    <div>
                                        <p class="text-sm font-medium text-secondary" data-i18n="settings.legal.privacyTitle">Privacy Policy</p>
                                        <p class="text-xs text-textMuted" data-i18n="settings.legal.privacyDesc">Data protection and privacy</p>
                                    </div>
                                </div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                            </div>
                        </a>

                        <a href="javascript:void(0)" data-click="showLegalPage" data-click-arg="guidelines" class="block w-full p-4 bg-background/50 hover:bg-background rounded-xl border border-borderSubtle hover:border-primary/20 transition group cursor-pointer">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-3">
                                    <i data-lucide="users" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                                    <div>
                                        <p class="text-sm font-medium text-secondary" data-i18n="settings.legal.guidelinesTitle">Community Guidelines</p>
                                        <p class="text-xs text-textMuted" data-i18n="settings.legal.guidelinesDesc">Governance and moderation rules</p>
                                    </div>
                                </div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-textMuted group-hover:text-primary transition"></i>
                            </div>
                        </a>
                    </div>
                </div>

                <div class="text-center pt-8 opacity-20 text-[10px] font-mono tracking-widest uppercase">
                    CryptoMind v2.0.0-TON
                </div>
             </div>
        </div>
    `;

// Side-effect module — assigns to window.Components
export {};
