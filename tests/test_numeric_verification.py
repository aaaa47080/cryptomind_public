"""
Numeric Verification 測試 — 防止金融數字幻覺。

核心案例：SNXX 對話中「2.22% 跌幅」被幻覺成「660 點盤中波動」，
後續整段分析建立在幻覺上。
"""
from __future__ import annotations

from core.agents.verification import (
    _is_simple_derivation,
    extract_financial_numbers,
    verify_numeric_consistency,
)

# ============================================================================
# 1. extract_financial_numbers
# ============================================================================


def test_extract_currency():
    nums = extract_financial_numbers("BTC 現價 $64,000.50")
    assert len(nums) == 1
    assert nums[0].value == 64000.50


def test_extract_percentage():
    nums = extract_financial_numbers("24h 漲跌 +1.62%")
    assert len(nums) == 1
    assert abs(nums[0].value - 1.62) < 0.01


def test_extract_negative_percentage():
    nums = extract_financial_numbers("下跌 -2.22%")
    assert len(nums) == 1
    assert abs(nums[0].value - (-2.22)) < 0.01


def test_extract_points():
    nums = extract_financial_numbers("盤中波動 660 點")
    assert len(nums) == 1
    assert nums[0].value == 660


def test_extract_nt_dollar():
    nums = extract_financial_numbers("台積電 NT$2,290")
    assert len(nums) == 1
    assert nums[0].value == 2290


def test_extract_market_cap():
    nums = extract_financial_numbers("市值約 1.28 兆美元")
    assert len(nums) == 1
    assert abs(nums[0].value - 1.28) < 0.01


def test_extract_multiple_numbers():
    nums = extract_financial_numbers("BTC $64000，ETH $1845，漲跌 +1.62%")
    assert len(nums) == 3


def test_extract_empty_text():
    assert extract_financial_numbers("") == []
    assert extract_financial_numbers(None) == []  # type: ignore


def test_no_generic_numbers_extracted():
    """一般數字（如「3 個建議」「Step 1」）不該被當金融數字。"""
    nums = extract_financial_numbers("以下 3 個建議，Step 1 是買入")
    assert len(nums) == 0


# ============================================================================
# 2. _is_simple_derivation
# ============================================================================


def test_direct_match_passes():
    assert _is_simple_derivation(64000.0, [64000, 1300, 51]) is True


def test_subtraction_passes():
    """13.50 - 13.20 = 0.30 是合法推論。"""
    assert _is_simple_derivation(0.30, [13.50, 13.20]) is True


def test_addition_passes():
    assert _is_simple_derivation(26.70, [13.50, 13.20]) is True


def test_division_passes():
    assert _is_simple_derivation(50.0, [100, 2]) is True


def test_percentage_derivation_passes():
    """13.5 * 2.22 / 100 = 0.2997 ≈ 0.30（百分比換算）。"""
    assert _is_simple_derivation(0.2997, [13.5, 2.22]) is True


def test_no_match_fails():
    """660 在 [64000, 1300, 51] 中找不到來源。"""
    assert _is_simple_derivation(660.0, [64000, 1300, 51]) is False


def test_empty_source_fails():
    assert _is_simple_derivation(660.0, []) is False


# ============================================================================
# 3. verify_numeric_consistency — 核心案例
# ============================================================================


def test_snxx_660_hallucination_detected():
    """SNXX 660 點幻覺的核心回歸測試。

    背景：nemotron 把「2.22% 跌幅」幻覺成「660 點盤中波動」，
    後續整段分析建立在幻覺上。
    """
    response = (
        "SNXX 目前價格為 $13.20（-2.22%），盤中曾出現超過 660 點的波動。"
    )
    tool_outputs = [
        "price: 13.20, prev_close: 13.50, change_pct: -2.22, RSI: 29.6"
    ]
    result = verify_numeric_consistency(response, tool_outputs)
    assert result.has_hallucination_risk
    suspicious_values = [n.value for n in result.suspicious_numbers]
    assert 660 in suspicious_values, f"660 應被標記可疑，實際: {suspicious_values}"


def test_all_numbers_sourced_passes():
    response = "BTC $64000，漲跌 +1.62%"
    tool_outputs = ["price: 64000, change: 1.62%"]
    result = verify_numeric_consistency(response, tool_outputs)
    assert result.passed is True
    assert result.has_hallucination_risk is False


def test_no_numbers_in_response_passes():
    result = verify_numeric_consistency("你好", ["any output"])
    assert result.passed is True


def test_no_tool_output_all_suspicious():
    """tool 沒回任何數字，但 LLM 回應有金融數字 → 全部可疑。"""
    response = "BTC $64000，漲跌 +1.62%"
    result = verify_numeric_consistency(response, ["no data"])
    assert result.has_hallucination_risk
    assert len(result.suspicious_numbers) == 2


def test_small_numbers_skipped():
    """< 1 的數字（如 RSI 0.5）預設跳過。"""
    response = "RSI 為 0.45，MACD 0.02"
    tool_outputs = ["RSI: 0.55"]
    result = verify_numeric_consistency(response, tool_outputs)
    # 小數字被跳過，不標記可疑
    assert result.passed is True


def test_derivation_from_tool_numbers_passes():
    """LLM 從 tool 數字做簡單換算 → 合法。"""
    response = "跌了 $0.30"
    tool_outputs = ["prev: 13.50, current: 13.20"]
    result = verify_numeric_consistency(response, tool_outputs)
    assert result.passed is True  # 0.30 = 13.50 - 13.20


def test_multiple_tool_outputs_merged():
    """多個 tool 輸出的數字合併檢查。"""
    response = "BTC $64000，ETH $1845"
    tool_outputs = [
        "BTC price: 64000",
        "ETH price: 1845",
    ]
    result = verify_numeric_consistency(response, tool_outputs)
    assert result.passed is True


def test_mixed_real_and_hallucinated():
    """部分真實 + 部分幻覺。"""
    response = "BTC $64000（真實），但盤中波動 9999 點（幻覺）"
    tool_outputs = ["price: 64000"]
    result = verify_numeric_consistency(response, tool_outputs)
    assert result.has_hallucination_risk
    suspicious_values = [n.value for n in result.suspicious_numbers]
    assert 9999 in suspicious_values
    # 64000 不在可疑清單
    assert 64000 not in suspicious_values
