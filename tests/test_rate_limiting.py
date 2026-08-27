"""Tests for per-route rate limiting configuration.

Verifies that sensitive endpoints have @limiter.limit decorators
with appropriate rate limits applied via SlowAPI's internal registry.
"""

import pytest

RATE_LIMITED_ENDPOINTS = {
    # Admin
    "api.routers.admin.config.admin_update_config": "20 per 1 minute",
    "api.routers.admin.forum.admin_resolve_report": "30 per 1 minute",
    "api.routers.admin.forum.admin_toggle_comment_visibility": "30 per 1 minute",
    "api.routers.admin.forum.admin_toggle_post_pin": "30 per 1 minute",
    "api.routers.admin.forum.admin_toggle_post_visibility": "30 per 1 minute",
    "api.routers.admin.notifications.broadcast_notification": "5 per 1 minute",
    "api.routers.admin.stats.admin_stats_forum": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_overview": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_revenue": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_users": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_visitors_list": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_visitors_summary": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_visitors_trend": "30 per 1 minute",
    "api.routers.admin.stats.admin_stats_wallet_monitor": "10 per 1 minute",
    "api.routers.admin.users.bootstrap_admin": "5 per 1 minute",
    "api.routers.admin.users.set_user_membership": "20 per 1 minute",
    "api.routers.admin.users.set_user_role": "20 per 1 minute",
    "api.routers.admin.users.set_user_status": "20 per 1 minute",
    # Auth / user
    "api.routers.user.dev_login": "5 per 1 minute",
    "api.routers.guest.guest_analyze": "5 per 1 minute",  # 訪客模式（2026-08-19）
    "api.routers.guest.guest_quota": "30 per 1 minute",  # 訪客 banner 額度查詢（唯讀、不扣額）
    "api.routers.memory.verify_fact": "20 per 1 minute",  # c031 記憶治理
    "api.routers.memory.fact_history": "20 per 1 minute",  # c031 記憶治理
    "api.routers.journal.list_entries": "30 per 1 minute",  # c033 統一帳本
    "api.routers.journal.create_entry": "20 per 1 minute",
    "api.routers.journal.delete_entry": "20 per 1 minute",
    "api.routers.journal.update_entry": "20 per 1 minute",
    "api.routers.journal.get_summary": "30 per 1 minute",
    "api.routers.journal.list_revisions": "30 per 1 minute",  # c037 版本史
    "api.routers.journal.restore_entry": "20 per 1 minute",
    "api.routers.journal.list_deleted": "30 per 1 minute",
    "api.routers.journal.list_positions": "30 per 1 minute",  # UX 第二輪投資視圖
    "api.routers.journal.get_base_currency": "30 per 1 minute",  # c039 報表基準幣
    # 切換基準幣會整批搬移換算值——限流較嚴
    "api.routers.journal.set_base_currency": "6 per 1 minute",
    # 以下 4 個為既有端點（先前 PR 加的），全 app import 時註冊，補齊預期清單
    "api.routers.discover.discover_opportunities": "30 per 1 minute",
    "api.routers.scam_tracker.reports.address_checkup": "30 per 1 minute",
    "api.routers.studio.add_reference": "20 per 1 minute",
    "api.routers.studio.remove_reference": "20 per 1 minute",
    "api.routers.user.ton_login": "10 per 1 minute",
    "api.routers.user.ton_proof_payload": "30 per 1 minute",
    "api.routers.user.refresh_access_token": "30 per 1 minute",
    "api.routers.user.save_user_api_key_endpoint": "10 per 1 minute",
    "api.routers.user.delete_user_api_key_endpoint": "10 per 1 minute",
    "api.routers.user.save_user_model_endpoint": "10 per 1 minute",
    "api.routers.user.add_watchlist": "20 per 1 minute",
    "api.routers.user.remove_watchlist": "20 per 1 minute",
    "api.routers.user.logout": "30 per 1 minute",
    "api.routers.user.upsert_analysis_preference": "20 per 1 minute",
    "api.routers.user.delete_analysis_preference": "20 per 1 minute",
    "api.routers.user.set_user_display_name_pref": "5 per 1 minute",
    "api.routers.user.set_user_llm_provider_pref": "30 per 1 minute",  # #356 LLM provider 同步
    # Premium
    "api.routers.premium.upgrade_to_premium": "10 per 1 minute",
    "api.routers.premium.create_ton_payment_order": "20 per 1 minute",
    # Forum
    "api.routers.forum.posts.create_new_post": "20 per 1 minute",
    "api.routers.forum.posts.create_post_ton_order": "20 per 1 minute",
    "api.routers.forum.posts.update_post_content": "10 per 1 minute",
    "api.routers.forum.posts.delete_post_by_id": "10 per 1 minute",
    "api.routers.forum.comments.add_new_comment": "30 per 1 minute",
    "api.routers.forum.comments.push_post": "30 per 1 minute",
    "api.routers.forum.comments.boo_post": "30 per 1 minute",
    "api.routers.forum.tips.create_tip_ton_order": "20 per 1 minute",
    "api.routers.forum.tips.tip_post": "10 per 1 minute",
    # Messages
    "api.routers.messages.send_message_endpoint": "30 per 1 minute",
    "api.routers.messages.send_greeting_endpoint": "5 per 1 minute",
    "api.routers.messages.mark_read_endpoint": "30 per 1 minute",
    "api.routers.messages.delete_message_endpoint": "20 per 1 minute",
    "api.routers.messages.hide_message_endpoint": "20 per 1 minute",
    "api.routers.messages.delete_conversation_endpoint": "10 per 1 minute",
    # Friends
    "api.routers.friends.send_request": "10 per 1 minute",
    "api.routers.friends.accept_request": "10 per 1 minute",
    "api.routers.friends.reject_request": "10 per 1 minute",
    "api.routers.friends.cancel_request": "10 per 1 minute",
    "api.routers.friends.remove_friend_endpoint": "10 per 1 minute",
    "api.routers.friends.block_user_endpoint": "10 per 1 minute",
    "api.routers.friends.unblock_user_endpoint": "10 per 1 minute",
    # Notifications
    "api.routers.notifications.mark_as_read_endpoint": "30 per 1 minute",
    "api.routers.notifications.mark_all_as_read_endpoint": "10 per 1 minute",
    "api.routers.notifications.delete_notification_endpoint": "20 per 1 minute",
    # Governance
    "api.routers.governance.submit_report": "10 per 1 hour",
    "api.routers.governance.vote_on_pending_report": "30 per 1 hour",
    "api.routers.governance.finalize_report_decision": "10 per 1 minute",
    # Analysis
    "api.routers.analysis.analyze_crypto": "10 per 1 minute",
    "api.routers.analysis.get_chat_greeting": "10 per 1 minute",
    "api.routers.analysis.clear_chat_history_endpoint": "5 per 1 minute",
    "api.routers.analysis.delete_user_session": "20 per 1 minute",
    "api.routers.analysis.create_user_session": "20 per 1 minute",
    "api.routers.analysis.pin_user_session": "30 per 1 minute",
    "api.routers.analysis.submit_feedback": "20 per 1 minute",
    "api.routers.analysis.confirm_scam_verdict": "20 per 1 minute",
    # Swap（Omniston M3）— 碰錢更嚴
    # Memory（Hermes 主動記憶 #355）
    "api.routers.memory.list_facts": "30 per 1 minute",
    "api.routers.memory.create_fact": "20 per 1 minute",
    "api.routers.memory.update_fact": "20 per 1 minute",
    "api.routers.memory.delete_fact": "20 per 1 minute",
    # Agent Presets（Agent platform Phase 2）
    "api.routers.agent_presets.list_agent_profiles": "30 per 1 minute",
    "api.routers.agent_presets.list_agent_presets": "30 per 1 minute",
    "api.routers.agent_presets.create_agent_preset": "20 per 1 minute",
    "api.routers.agent_presets.update_agent_preset": "20 per 1 minute",
    "api.routers.agent_presets.delete_agent_preset": "20 per 1 minute",
    "api.routers.agent_presets.activate_agent_preset": "20 per 1 minute",
    "api.routers.agent_presets.get_resolved_capabilities": "30 per 1 minute",
    # Discover（People & Projects 探索，Phase 3）
    "api.routers.discover.get_discover_config": "30 per 1 minute",
    "api.routers.discover.discover_search": "30 per 1 minute",
    "api.routers.discover.discover_project_detail": "30 per 1 minute",
    "api.routers.discover.discover_project_comments": "30 per 1 minute",
    "api.routers.discover.list_favorites": "30 per 1 minute",
    "api.routers.discover.add_favorite": "20 per 1 minute",
    "api.routers.discover.remove_favorite": "20 per 1 minute",
    "api.routers.discover.discover_recommend": "20 per 1 minute",
    "api.routers.discover.discover_ai_review": "10 per 1 minute",
    "api.routers.studio.list_drafts": "30 per 1 minute",
    "api.routers.studio.create_draft": "20 per 1 minute",
    "api.routers.studio.get_draft": "30 per 1 minute",
    "api.routers.studio.update_draft": "20 per 1 minute",
    "api.routers.studio.delete_draft": "20 per 1 minute",
    "api.routers.studio.add_version": "20 per 1 minute",
    "api.routers.studio.list_versions": "30 per 1 minute",
    "api.routers.studio.get_version": "30 per 1 minute",
    "api.routers.studio.diff_versions": "30 per 1 minute",
    "api.routers.studio.export_draft": "10 per 1 minute",
    "api.routers.studio.coach_draft": "6 per 1 minute",
    "api.routers.studio.share_draft": "10 per 1 minute",
    "api.routers.studio.unshare_draft": "10 per 1 minute",
    "api.routers.studio.get_shared_draft": "30 per 1 minute",
    "api.routers.studio.record_outcome": "30 per 1 minute",
    "api.routers.studio.list_exchanges": "30 per 1 minute",
    "api.routers.discover.discover_project_ask": "10 per 1 minute",
    "api.routers.discover.admin_prospect_logs": "10 per 1 minute",
    "api.routers.admin.stats.admin_stats_feature_usage": "30 per 1 minute",
    # Skills（使用者自訂 skill）
    "api.routers.skills.list_skills": "30 per 1 minute",
    "api.routers.skills.toggle_official_skill": "20 per 1 minute",
    "api.routers.skills.create_custom_skill": "10 per 1 minute",
    "api.routers.skills.update_custom_skill": "20 per 1 minute",
    "api.routers.skills.delete_custom_skill": "20 per 1 minute",
    # Market
    "api.routers.market.rest.run_screener": "10 per 1 minute",
    "api.routers.market.rest.get_klines_data": "60 per 1 minute",
    # System
    "api.routers.system.update_user_settings": "10 per 1 minute",
    "api.routers.system.validate_key": "10 per 1 minute",
    "api.routers.system.switch_test_tier": "5 per 1 minute",
    # Tools
    "api.routers.tools.set_tool_preference": "20 per 1 minute",
    "api.routers.tools.set_user_tool_preference": "20 per 1 minute",
    # Scam Tracker
    "api.routers.scam_tracker.votes.vote_on_report": "20 per 1 minute",
    "api.routers.scam_tracker.reports.create_new_scam_report": "5 per 1 minute",
    "api.routers.scam_tracker.comments.add_comment_to_report": "10 per 1 minute",
    # Alerts
    "api.routers.alerts.create_alert_endpoint": "10 per 1 minute",
    "api.routers.alerts.delete_alert_endpoint": "30 per 1 minute",
    # User — additional endpoints
    "api.routers.user.client_log": "30 per 1 minute",
    "api.routers.user.submit_user_feedback": "10 per 1 minute",
    "api.routers.user.set_user_language_pref": "10 per 1 minute",
    "api.routers.user.test_user_api_key_endpoint": "5 per 1 minute",
    "api.routers.user.telegram_login": "10 per 1 minute",
    # Analysis — additional
    "api.routers.analysis.set_current_session_endpoint": "20 per 1 minute",
    # Market — additional
    "api.routers.market.rest.api_refresh_all_market_pulse": "5 per 1 minute",
    # System — additional
    "api.routers.system.discover_models": "10 per 1 minute",
    # Telegram Link
    "api.routers.telegram_link.create_link_token": "5 per 1 minute",
    "api.routers.telegram_link.unlink_telegram": "5 per 1 minute",
    "api.routers.telegram_link.verify_link": "10 per 1 minute",
    "api.routers.telegram_link.bot_chat": "10 per 1 minute",
    "api.routers.telegram_link.bot_list_sessions": "20 per 1 minute",
    "api.routers.telegram_link.bot_use_session": "20 per 1 minute",
    # Trust（信任等級 + EVM 綁定）
    "api.routers.trust.get_my_trust_score": "30 per 1 minute",
    "api.routers.trust.get_user_trust_badge": "60 per 1 minute",
    "api.routers.trust.trigger_recompute": "5 per 1 minute",
    "api.routers.trust.get_evm_bind_nonce": "10 per 1 minute",
    "api.routers.trust.bind_evm_address": "5 per 1 minute",
    "api.routers.trust.unbind_evm_address": "5 per 1 minute",
    # Wallet Monitor（錢包監測）
    "api.routers.wallet_monitor.wallet_overview": "30 per 1 minute",
    "api.routers.wallet_monitor.wallet_events": "30 per 1 minute",
    "api.routers.wallet_monitor.get_settings": "30 per 1 minute",
    "api.routers.wallet_monitor.update_settings": "20 per 1 minute",
    "api.routers.wallet_monitor.add_wallet": "10 per 1 minute",
    "api.routers.wallet_monitor.remove_wallet": "10 per 1 minute",
    "api.routers.wallet_monitor.wallet_detail": "30 per 1 minute",  # PR #418 錢包明細
    # External Agent Guard API / management
    "api.routers.guard_management.create_guard_client": "10 per 1 hour",
    "api.routers.guard_management.create_guard_api_key": "10 per 1 hour",
    "api.routers.guard_management.revoke_guard_api_key": "20 per 1 hour",
    "api.routers.guard_management.create_guard_policy": "20 per 1 hour",
    "api.routers.guard_management.get_guard_client_dashboard": "60 per 1 minute",
    "api.routers.guard_management.list_guard_client_decisions": "60 per 1 minute",
    "api.routers.guard_management.list_guard_client_receipts": "60 per 1 minute",
    "api.routers.guard_management.list_my_guard_receipts": "60 per 1 minute",
    "api.routers.guard_v1.evaluate_external_action": "120 per 1 minute",
    "api.routers.guard_v1.get_external_decision": "240 per 1 minute",
    "api.routers.guard_v1.record_external_approval": "60 per 1 minute",
    "api.routers.guard_v1.record_external_outcome": "120 per 1 minute",
    "api.routers.guard_v1.verify_external_receipt": "240 per 1 minute",
    # 2026-08-23 速率限制審計補齊（高成本 GET＋messages＋chat history）
    "api.routers.analysis.get_history": "30 per 1 minute",
    "api.routers.analysis.revoke_analysis_run": "10 per 1 minute",
    "api.routers.messages.get_conversations_endpoint": "30 per 1 minute",
    "api.routers.messages.get_messages_endpoint": "30 per 1 minute",
    "api.routers.messages.get_conversation_with_user_endpoint": "30 per 1 minute",
    "api.routers.messages.search_messages_endpoint": "30 per 1 minute",
    "api.routers.messages.get_unread_count_endpoint": "60 per 1 minute",
    "api.routers.messages.get_message_limits_endpoint": "30 per 1 minute",
    # 2026-08-23 Error Boundary
    "api.routers.frontend_errors.report_frontend_errors": "10 per 1 minute",
    "api.routers.frontend_errors.list_frontend_errors": "30 per 1 minute",
    # 2026-08-23 Skill 版本歷史
    "api.routers.skills.get_skill_history": "20 per 1 minute",
    "api.routers.skills.rollback_skill": "10 per 1 minute",
    # 2026-08-23 股市行情限流（pulse 20/m、klines 30/m，9 個市場模組）。
    # 當時漏登記本清單——單跑測試（fixture 未 import 股市 router）僥倖通過，
    # 全套（conftest 載入 api_server）即爆「unexpected endpoints」。
    "api.routers.astock.get_a_pulse": "20 per 1 minute",
    "api.routers.astock.get_a_klines": "30 per 1 minute",
    "api.routers.twstock.get_tw_pulse": "20 per 1 minute",
    "api.routers.twstock.get_tw_klines": "30 per 1 minute",
    "api.routers.usstock.get_us_pulse": "20 per 1 minute",
    "api.routers.usstock.get_us_klines": "30 per 1 minute",
    "api.routers.hkstock.get_hk_pulse": "20 per 1 minute",
    "api.routers.hkstock.get_hk_klines": "30 per 1 minute",
    "api.routers.jpstock.get_jp_pulse": "20 per 1 minute",
    "api.routers.jpstock.get_jp_klines": "30 per 1 minute",
    "api.routers.krstock.get_kr_pulse": "20 per 1 minute",
    "api.routers.krstock.get_kr_klines": "30 per 1 minute",
    "api.routers.instock.get_in_pulse": "20 per 1 minute",
    "api.routers.instock.get_in_klines": "30 per 1 minute",
    "api.routers.commodity.get_commodity_pulse": "20 per 1 minute",
    "api.routers.commodity.get_commodity_klines": "30 per 1 minute",
    "api.routers.forex.get_forex_pulse": "20 per 1 minute",
    "api.routers.forex.get_forex_klines": "30 per 1 minute",
}


@pytest.fixture(scope="module")
def route_limits():
    # Import router modules for side effects (rate limit registration)
    import api.routers.admin.config  # noqa: F401
    import api.routers.admin.forum  # noqa: F401
    import api.routers.admin.notifications  # noqa: F401
    import api.routers.admin.stats  # noqa: F401
    import api.routers.admin.users  # noqa: F401
    import api.routers.agent_presets  # noqa: F401
    import api.routers.alerts  # noqa: F401
    import api.routers.analysis  # noqa: F401

    # 股市行情 router（pulse/klines 限流）——與上面 RATE_LIMITED_ENDPOINTS 對齊
    import api.routers.astock  # noqa: F401
    import api.routers.commodity  # noqa: F401
    import api.routers.discover  # noqa: F401
    import api.routers.forex  # noqa: F401
    import api.routers.forum.comments  # noqa: F401
    import api.routers.forum.posts  # noqa: F401
    import api.routers.forum.tips  # noqa: F401
    import api.routers.friends  # noqa: F401
    import api.routers.frontend_errors  # noqa: F401
    import api.routers.governance  # noqa: F401
    import api.routers.guard_management  # noqa: F401
    import api.routers.guard_v1  # noqa: F401
    import api.routers.guest  # noqa: F401
    import api.routers.hkstock  # noqa: F401
    import api.routers.instock  # noqa: F401
    import api.routers.journal  # noqa: F401
    import api.routers.jpstock  # noqa: F401
    import api.routers.krstock  # noqa: F401
    import api.routers.market.rest  # noqa: F401
    import api.routers.memory  # noqa: F401
    import api.routers.messages  # noqa: F401
    import api.routers.notifications  # noqa: F401
    import api.routers.premium  # noqa: F401
    import api.routers.scam_tracker.comments  # noqa: F401
    import api.routers.scam_tracker.reports  # noqa: F401
    import api.routers.scam_tracker.votes  # noqa: F401
    import api.routers.skills  # noqa: F401
    import api.routers.studio  # noqa: F401
    import api.routers.system  # noqa: F401
    import api.routers.telegram_link  # noqa: F401
    import api.routers.tools  # noqa: F401
    import api.routers.trust  # noqa: F401
    import api.routers.twstock  # noqa: F401
    import api.routers.user  # noqa: F401
    import api.routers.usstock  # noqa: F401
    import api.routers.wallet_monitor  # noqa: F401
    from api.middleware.rate_limit import limiter

    return limiter._route_limits


class TestAuthRateLimits:
    def test_dev_login_5_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.user.dev_login", [])
        assert len(limits) >= 1
        assert "5 per 1 minute" in [str(r.limit) for r in limits]

    def test_ton_login_10_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.user.ton_login", [])
        assert len(limits) >= 1
        assert "10 per 1 minute" in [str(r.limit) for r in limits]

    def test_refresh_access_token_30_per_minute(self, route_limits):
        # 2026-08-14：10→30/min。access token 過期時 limiter key 退化為 IP，
        # 前端多路徑主動刷新（已加 60s 冷卻）實測仍可能序列觸發 >10 次。
        limits = route_limits.get("api.routers.user.refresh_access_token", [])
        assert len(limits) >= 1
        assert "30 per 1 minute" in [str(r.limit) for r in limits]


class TestPaymentRateLimits:
    def test_premium_upgrade_10_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.premium.upgrade_to_premium", [])
        assert len(limits) >= 1
        assert "10 per 1 minute" in [str(r.limit) for r in limits]

    def test_tip_post_10_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.forum.tips.tip_post", [])
        assert len(limits) >= 1
        assert "10 per 1 minute" in [str(r.limit) for r in limits]


class TestMessageRateLimits:
    def test_send_message_30_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.messages.send_message_endpoint", [])
        assert len(limits) >= 1
        assert "30 per 1 minute" in [str(r.limit) for r in limits]

    def test_greeting_5_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.messages.send_greeting_endpoint", [])
        assert len(limits) >= 1
        assert "5 per 1 minute" in [str(r.limit) for r in limits]


class TestForumRateLimits:
    def test_create_post_20_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.forum.posts.create_new_post", [])
        assert len(limits) >= 1
        assert "20 per 1 minute" in [str(r.limit) for r in limits]

    def test_add_comment_30_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.forum.comments.add_new_comment", [])
        assert len(limits) >= 1
        assert "30 per 1 minute" in [str(r.limit) for r in limits]

    def test_push_post_30_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.forum.comments.push_post", [])
        assert len(limits) >= 1
        assert "30 per 1 minute" in [str(r.limit) for r in limits]

    def test_boo_post_30_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.forum.comments.boo_post", [])
        assert len(limits) >= 1
        assert "30 per 1 minute" in [str(r.limit) for r in limits]


class TestGovernanceRateLimits:
    def test_report_10_per_hour(self, route_limits):
        limits = route_limits.get("api.routers.governance.submit_report", [])
        assert len(limits) >= 1
        assert "10 per 1 hour" in [str(r.limit) for r in limits]

    def test_vote_30_per_hour(self, route_limits):
        limits = route_limits.get("api.routers.governance.vote_on_pending_report", [])
        assert len(limits) >= 1
        assert "30 per 1 hour" in [str(r.limit) for r in limits]


class TestAnalysisRateLimit:
    def test_analyze_10_per_minute(self, route_limits):
        limits = route_limits.get("api.routers.analysis.analyze_crypto", [])
        assert len(limits) >= 1
        assert "10 per 1 minute" in [str(r.limit) for r in limits]


class TestTotalRateLimitedEndpoints:
    def test_all_expected_endpoints_are_limited(self, route_limits):
        expected = set(RATE_LIMITED_ENDPOINTS.keys())
        actual = set(route_limits.keys())
        missing = expected - actual
        assert not missing, f"Missing rate limits for: {missing}"

    def test_no_unexpected_endpoints(self, route_limits):
        expected = set(RATE_LIMITED_ENDPOINTS.keys())
        actual = set(route_limits.keys())
        extra = actual - expected
        assert not extra, f"Unexpected rate-limited endpoints: {extra}"
