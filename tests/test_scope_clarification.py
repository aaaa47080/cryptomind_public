"""Wrong-Scope Clarify (Phase E) 測試。

核心案例（截圖鐵證）：使用者問「台股是否值得投資」（範圍問題），中等模型
直接答「台積電（2330）…」（偷換成特定股）；或問「我想要投資」，模型被前文
context 帶偏調加密貨幣工具。should_clarify_wrong_scope 偵測這類「非空但答非所問」
的回應，回傳 clarify payload 讓前端跳釐清卡。

與既有 clarification 測試的分工：
- test_clarification.py：Phase C（查無）的 should_clarify
- 本檔：Phase E（答錯範圍）的 should_clarify_wrong_scope + 中文 ticker 偵測
"""
from __future__ import annotations

import pytest

from core.agents.clarification import (
    _extract_tickers_zh,
    _query_is_scope_question,
    should_clarify_wrong_scope,
)

# ============================================================================
# _extract_tickers_zh — 中文 ticker 偵測（補 _detect_query_ticker 的 gap）
# ============================================================================


def test_extract_chinese_alias():
    """中文公司名透過 alias 表 → 正確 symbol（台積電→2330）。"""
    assert "2330" in _extract_tickers_zh("台積電近期表現")


def test_extract_tw_number():
    """TW 4 位數代號（2330、2454）應被偵測。"""
    found = _extract_tickers_zh("2330 與 2454")
    assert "2330" in found
    assert "2454" in found


def test_extract_latin_ticker():
    """拉丁大寫 ticker（AAPL、NVDA）應被偵測。"""
    assert "AAPL" in _extract_tickers_zh("Apple (AAPL) is trading at $150")
    assert "NVDA" in _extract_tickers_zh("輝達 NVDA")


def test_extract_mixed_all_three():
    """三種格式同時出現：中文 + TW數字 + 拉丁。"""
    found = _extract_tickers_zh("台積電(2330)目前股價 TSMC")
    assert "2330" in found
    assert "TSMC" in found


def test_extract_no_ticker_for_broad_term():
    """純範圍詞（整體大盤）不該偵測出 ticker。"""
    assert _extract_tickers_zh("整體大盤") == set()


def test_extract_skip_known_crypto():
    """BTC/ETH 等已知 crypto 在 query 側（預設）不該被當成需要 clarify 的 ticker。"""
    assert _extract_tickers_zh("BTC and ETH") == set()


def test_extract_include_crypto_on_response_side():
    """Gap 1 修復：response 側用 include_crypto=True 保留 crypto ticker。

    query 裡的 BTC 是明確的（不需 clarify）；但 response 裡的 BTC/比特幣 是
    「模型被前文 context 帶偏，偷換標的」的證據——使用者問「我想要投資」無標的，
    模型調 crypto 工具，response 裡的 crypto 正是該攔的訊號。
    """
    assert "BTC" in _extract_tickers_zh("BTC is great", include_crypto=True)
    assert _extract_tickers_zh("BTC is great", include_crypto=True) != set()


def test_extract_empty_or_none():
    """空字串 / None → 空 set。"""
    assert _extract_tickers_zh("") == set()
    assert _extract_tickers_zh(None) == set()  # type: ignore[arg-type]


# ============================================================================
# _query_is_scope_question — 範圍問題判斷
# ============================================================================


def test_scope_question_with_market_term():
    """含市場命名空間詞 + 無 ticker → 是範圍問題。"""
    assert _query_is_scope_question("台股是否值得投資") is True
    assert _query_is_scope_question("美股適合買嗎") is True


def test_scope_question_intent_no_target():
    """無標的意圖詞（我想要投資）→ 是範圍問題。"""
    assert _query_is_scope_question("我想要投資") is True
    assert _query_is_scope_question("我想進場") is True


def test_not_scope_when_query_has_ticker():
    """query 已含具體 ticker（台積電/2330）→ 不是範圍問題。"""
    assert _query_is_scope_question("台積電值得買嗎") is False
    assert _query_is_scope_question("2330可以買嗎") is False


def test_not_scope_too_short():
    """太短/無範圍詞 → 不是範圍問題。"""
    assert _query_is_scope_question("你好") is False
    assert _query_is_scope_question("ab") is False


# ============================================================================
# should_clarify_wrong_scope — 主偵測函式（觸發案例）
# ============================================================================


@pytest.mark.asyncio
async def test_trigger_tw_stock_answered_tsmc():
    """台股問題 → 答台積電（截圖場景 1）→ 應觸發。"""
    payload = await should_clarify_wrong_scope(
        query="台股是否值得投資",
        response="台積電(2330)目前股價在700元附近，技術面RSI偏高...",
    )
    assert payload is not None
    assert payload["type"] == "clarify"
    assert payload.get("select_mode") == "single"
    assert len(payload.get("options", [])) == 4
    assert "台股是否值得投資" in payload["question"]


@pytest.mark.asyncio
async def test_trigger_us_stock_answered_apple():
    """美股問題 → 答 Apple（截圖場景的英文版）→ 應觸發。"""
    payload = await should_clarify_wrong_scope(
        query="美股適合買嗎",
        response="Apple (AAPL) is trading at $150 and looks bullish with strong fundamentals.",
        language="en",
    )
    assert payload is not None
    assert payload["type"] == "clarify"


@pytest.mark.asyncio
async def test_trigger_intent_no_target_answered_crypto():
    """「我想要投資」（無標的）→ 答加密貨幣（截圖場景 2）→ 應觸發。"""
    payload = await should_clarify_wrong_scope(
        query="我想要投資",
        response="比特幣(BTC)目前價格67000美元，是熱門的投資選擇。",
    )
    assert payload is not None
    assert payload["type"] == "clarify"


# ============================================================================
# Gap 1 — Crypto context contamination（審計確認的真實洞）
# ============================================================================


@pytest.mark.asyncio
async def test_trigger_crypto_specific_ticker_in_response():
    """Gap 1：response 出現具體 crypto ticker（BTC/比特幣）且 query 無 crypto 意圖 → 觸發。

    修復前盲點：_extract_tickers_zh 把 BTC/ETH 等 18 個排除，response 裡的 BTC
    對它隱形 → new_tickers 空 → Phase E 不觸發。修復：response 側用
    include_crypto=True 保留 crypto ticker（query 側仍排除）。
    """
    assert (
        await should_clarify_wrong_scope(
            query="我想要投資",
            response="比特幣(BTC)目前價格67000美元，是熱門選擇。",
        )
        is not None
    )


@pytest.mark.asyncio
async def test_trigger_crypto_generic_talk_no_ticker():
    """Gap 1 子情境：response 是泛 crypto 言論但無具體 ticker → 仍觸發。

    場景：使用者問「我想要投資」，模型答「加密貨幣整體來說不錯」——抓不到 BTC
    這種 ticker，但仍是偷換標的（crypto context 污染）。
    """
    payload = await should_clarify_wrong_scope(
        query="我想要投資",
        response="加密貨幣整體來說是不錯的投資選擇，風險與報酬並存。",
    )
    assert payload is not None
    assert payload["type"] == "clarify"


@pytest.mark.asyncio
async def test_trigger_crypto_english_response():
    """Gap 1 英文版：response 用 Bitcoin/ethereum 等英文 crypto 詞 → 觸發。"""
    assert (
        await should_clarify_wrong_scope(
            query="我想要投資",
            response="Bitcoin is a popular investment, ethereum too.",
        )
        is not None
    )


@pytest.mark.asyncio
async def test_no_trigger_when_query_genuinely_asks_crypto():
    """Gap 1 防誤觸發：query 真的問 crypto（加密貨幣值得投資嗎）→ 不觸發。

    即使 response 答 crypto 也是正確範圍，因為使用者本來就問 crypto。
    """
    assert (
        await should_clarify_wrong_scope(
            query="加密貨幣值得投資嗎",
            response="比特幣(BTC)是主流的加密投資選擇。",
        )
        is None
    )


# ============================================================================
# should_clarify_wrong_scope — 不該觸發（防誤觸發）
# ============================================================================


@pytest.mark.asyncio
async def test_no_trigger_query_has_ticker():
    """query 已指名特定股（台積電值得買嗎）→ 不是範圍問題，不觸發。"""
    assert (
        await should_clarify_wrong_scope(
            query="台積電值得買嗎",
            response="台積電近期表現不錯，技術面偏多。",
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_trigger_response_has_breadth_words():
    """response 含廣度詞（整體/大盤）→ 視為正確範圍答案，不觸發。

    場景：使用者問「台股」，response 說「整體台股大盤偏多，權值股如台積電帶動」
    ——這是正確的範圍答案（台積電只是舉例），不該被攔。
    """
    assert (
        await should_clarify_wrong_scope(
            query="台股值得投資嗎",
            response="整體台股大盤偏多，權值股如台積電(2330)帶動上漲，加權指數創高。",
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_trigger_empty_response():
    """空回應歸 Phase D（should_clarify_vague_query），不歸 Phase E。"""
    assert (
        await should_clarify_wrong_scope(
            query="台股值得投資嗎",
            response="",
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_trigger_already_clarified():
    """已 clarify 過 → 不再觸發（防無限迴圈）。"""
    assert (
        await should_clarify_wrong_scope(
            query="台股是否值得投資",
            response="台積電(2330)目前股價...",
            already_clarified=True,
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_trigger_response_no_new_ticker():
    """response 沒提 query 以外的 ticker → 不是偷換主題，不觸發。

    場景：query「台股」response「台股整體偏多」（雖然 query 是範圍問題，
    但 response 沒跳到特定 ticker，是合理的範圍答案）。
    """
    assert (
        await should_clarify_wrong_scope(
            query="台股值得投資嗎",
            response="目前看來是值得的，不過投資有風險。",
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_trigger_query_not_scope_question():
    """query 既無範圍詞也無 ticker（純閒聊）→ 不觸發。"""
    assert (
        await should_clarify_wrong_scope(
            query="你好請幫我",
            response="台積電(2330)是熱門股票。",
        )
        is None
    )


# ============================================================================
# payload shape（前端零改動驗證 — 必須與 Phase D 相容）
# ============================================================================


@pytest.mark.asyncio
async def test_payload_shape_matches_phase_d():
    """Phase E payload shape 必須與 Phase D（should_clarify_vague_query）一致，
    讓前端 chat-hitl.js 既有 inline clarify 氣泡直接渲染（PR #316）。"""
    payload = await should_clarify_wrong_scope(
        query="台股值得投資嗎",
        response="台積電(2330)股價700元，技術面偏多。",
    )
    assert payload is not None
    # 必要欄位
    assert "type" in payload and payload["type"] == "clarify"
    assert "question" in payload and isinstance(payload["question"], str)
    # options 每項是 {label, hint}（支援前端可點選按鈕）
    options = payload.get("options", [])
    assert len(options) == 4
    for opt in options:
        assert "label" in opt
        assert "hint" in opt
    assert payload.get("select_mode") == "single"
