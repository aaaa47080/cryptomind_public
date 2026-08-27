"""
Numeric Verification — 數字一致性檢查（學 outcome grading + post-hoc verification）。

防止「2.22% 跌幅被幻覺成 660 點盤中波動」這類幻覺：
response 中出現的金融關鍵數字（價格、點數、百分比），必須能在 tool 輸出中
找到對應來源。若找不到 → 標記為可疑幻覺。

設計原則
--------
- **保守**：只檢查「金融關鍵數字」（帶貨幣符號 / 帶 % / 帶「點」單位），
  不檢查一般數字（如「3 個建議」「Step 1」），避免假陽性
- **容許簡單推論**：若數字是 tool 輸出中其他數字的簡單四則運算結果（如
  13.50 - 13.20 = 0.30），不算幻覺
- **只觸發 1 次**：可疑時 nudge LLM 重跑一次，不無限迴圈
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 從文字中抽取金融關鍵數字
# ============================================================================

# 金融關鍵數字模式：
# - 貨幣：$64,000 / $13.20 / NT$2,290 / ¥150
# - 百分比：+1.62% / -2.22% / 0.96%
# - 點數：660 點 / 660點 / 3000 points
# - 市值/TVL：1.28 兆 / 4.55 億 / 222B / 1.28T
_FINANCIAL_NUMBER_PATTERNS = [
    # 貨幣符號 + 數字（含千分位逗號）
    re.compile(
        r"(?:US\$|NT\$|HK\$|¥|€|£|\$)\s*[\d,]+\.?\d*", re.IGNORECASE
    ),
    # 百分比
    re.compile(r"[+-]?[\d,]+\.?\d*\s*%"),
    # 「N 點」/ 「N points」（移除 \b，因為中文「點」後面接「的」「波動」等
    # 不會構成英文 word boundary，會導致「660 點的波動」匹配失敗）
    re.compile(r"[\d,]+\.?\d*\s*(?:點|points?)", re.IGNORECASE),
    # 市值單位
    re.compile(
        r"[\d,]+\.?\d*\s*(?:兆|億|萬|B\b|M\b|T\b|K\b)", re.IGNORECASE
    ),
]

# 一般數字（不含金融 context）— 用來容許「Step 1」「3 個建議」等
_GENERIC_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass
class ExtractedNumber:
    """從文字中抽出的數字。"""

    raw: str  # 原始匹配字串（如 "$64,000" / "660 點" / "+1.62%"）
    value: float  # 純數值（如 64000.0 / 660.0 / 1.62）
    context: str = ""  # 前 20 字元 context（除錯用）


def extract_financial_numbers(text: str) -> List[ExtractedNumber]:
    """從文字中抽出金融關鍵數字。

    只抽「有金融 context 的」數字（貨幣、百分比、點數、市值），
    不抽一般數字（如「3 個建議」），降低假陽性。

    Args:
        text: LLM 回應或 tool 輸出文字。

    Returns:
        抽出的金融數字清單。
    """
    results: list[ExtractedNumber] = []
    if not text or not isinstance(text, str):
        return results

    seen_positions: set[int] = set()  # 避免重複匹配同一位置

    for pattern in _FINANCIAL_NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            # 避免跟前面 pattern 重疊
            if any(
                match.start() <= pos <= match.end() for pos in seen_positions
            ):
                continue

            raw = match.group()
            # 從 raw 抽純數值
            num_str = re.sub(r"[^\d.+-]", "", raw.replace(",", ""))
            try:
                value = float(num_str)
            except ValueError:
                continue

            context_start = max(0, match.start() - 20)
            context = text[context_start : match.end()]

            results.append(
                ExtractedNumber(raw=raw, value=value, context=context)
            )
            seen_positions.add(match.start())

    return results


def extract_all_numbers(text: str) -> List[float]:
    """抽出所有數字（含一般數字），用來做「簡單推論」容許檢查。"""
    if not text:
        return []
    return [
        float(m.group())
        for m in _GENERIC_NUMBER_RE.finditer(text)
        if m.group().replace(".", "", 1).isdigit()
    ]


# ============================================================================
# 2. 數字一致性比對
# ============================================================================


def _is_simple_derivation(
    target: float, source_numbers: list[float], tolerance: float = 0.02
) -> bool:
    """檢查 target 是否為 source_numbers 的簡單四則運算結果。

    容許模式（tolerance 2%）：
    - 直接出現在 source（精確匹配）
    - A - B（如 13.50 - 13.20 = 0.30）
    - A + B
    - A / B（如 64000 / 100 = 640）
    - A * ratio（常見比例：1/2, 1/3, 1/4, 2x, 3x）
    - 百分比換算（A * B / 100）

    Args:
        target: 要驗證的數字。
        source_numbers: tool 輸出中的所有數字。
        tolerance: 容許誤差（預設 2%）。

    Returns:
        True 若 target 是 source 的簡單推論。
    """
    if not source_numbers:
        return False

    # 直接匹配（含容許誤差）
    for s in source_numbers:
        if abs(target - s) <= max(abs(s) * tolerance, 0.01):
            return True

    # 兩數運算
    for i, a in enumerate(source_numbers):
        for j, b in enumerate(source_numbers):
            if i == j:
                continue
            try:
                if abs(target - (a - b)) <= max(abs(target) * tolerance, 0.01):
                    return True
                if abs(target - (a + b)) <= max(abs(target) * tolerance, 0.01):
                    return True
                if b != 0 and abs(target - (a / b)) <= max(
                    abs(target) * tolerance, 0.01
                ):
                    return True
                if abs(target - (a * b)) <= max(abs(target) * tolerance, 0.01):
                    return True
            except (OverflowError, ValueError):
                continue

    # 百分換算（如 13.5 * 2.22 / 100 = 0.2997 ≈ 0.30）。
    # 只容許「target 本身 < 100」（百分比換算結果通常是小數，如 0.30），
    # 且其中一個 source 是百分比（0~100）。避免兩個大數字乘除湊出大目標。
    if target >= 100:
        pass  # target 太大，跳過百分換算
    else:
        for s in source_numbers:
            if s <= 0 or s > 100:
                continue  # s 必須是百分比（0 < s <= 100）
            for s2 in source_numbers:
                if s2 == 0:
                    continue
                pct_result = s * s2 / 100
                if abs(target - pct_result) <= max(abs(target) * tolerance, 0.01):
                    return True

    return False


@dataclass
class VerificationResult:
    """數字一致性檢查結果。"""

    passed: bool  # True = 無可疑幻覺
    suspicious_numbers: list[ExtractedNumber] = field(default_factory=list)
    total_checked: int = 0
    total_suspicious: int = 0

    @property
    def has_hallucination_risk(self) -> bool:
        """是否有幻覺風險（可疑數字 > 0）。"""
        return len(self.suspicious_numbers) > 0


def verify_numeric_consistency(
    response: str,
    tool_outputs: list[str],
    skip_small_numbers: bool = True,
) -> VerificationResult:
    """檢查 response 中的金融數字是否都能在 tool_outputs 中找到來源。

    Args:
        response: LLM 的最終回應。
        tool_outputs: 本次執行所有 tool 輸出的文字清單（ToolMessage.content）。
        skip_small_numbers: 跳過 < 1 的數字（如 RSI 0.5、機率 0.95），
            這些通常不是金融價格/點數。預設 True。

    Returns:
        VerificationResult：通過 / 可疑數字清單。

    Examples:
        >>> result = verify_numeric_consistency(
        ...     "BTC $64000，盤中波動 660 點",
        ...     ["price: 64000, change: -0.30"],
        ... )
        >>> result.has_hallucination_risk
        True  # 660 在 tool 輸出中找不到
    """
    response_numbers = extract_financial_numbers(response)

    if not response_numbers:
        return VerificationResult(passed=True, total_checked=0)

    # 合併所有 tool 輸出的數字（金融 + 一般）
    tool_all_numbers: list[float] = []
    for out in tool_outputs:
        if isinstance(out, str):
            for num in extract_all_numbers(out):
                tool_all_numbers.append(num)
            for fin_num in extract_financial_numbers(out):
                tool_all_numbers.append(fin_num.value)

    if not tool_all_numbers:
        # tool 沒回任何數字，但 LLM 回應有金融數字 → 全部可疑
        return VerificationResult(
            passed=False,
            suspicious_numbers=response_numbers,
            total_checked=len(response_numbers),
            total_suspicious=len(response_numbers),
        )

    suspicious: list[ExtractedNumber] = []
    for num in response_numbers:
        if skip_small_numbers and num.value < 1:
            continue

        if not _is_simple_derivation(num.value, tool_all_numbers):
            suspicious.append(num)

    return VerificationResult(
        passed=len(suspicious) == 0,
        suspicious_numbers=suspicious,
        total_checked=len(response_numbers),
        total_suspicious=len(suspicious),
    )


# ============================================================================
# 3. 從 messages 中抽取 tool outputs
# ============================================================================


def extract_tool_outputs_from_messages(messages: list) -> list[str]:
    """從 LangGraph messages 中抽出所有 ToolMessage 的 content。

    Args:
        messages: LangGraph state 中的 messages list。

    Returns:
        ToolMessage content 字串清單（供 verify_numeric_consistency 用）。
    """
    outputs: list[str] = []
    if not messages:
        return outputs

    from langchain_core.messages import ToolMessage

    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str):
                outputs.append(content)
            elif isinstance(content, list):
                # 部分 provider 用 list of dict
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content") or ""
                        if isinstance(text, str):
                            outputs.append(text)
                    elif isinstance(part, str):
                        outputs.append(part)
            elif isinstance(content, dict):
                # dict 形式（如 JSON tool output）
                import json

                try:
                    outputs.append(json.dumps(content, ensure_ascii=False))
                except (TypeError, ValueError):
                    outputs.append(str(content))
    return outputs


__all__ = [
    "ExtractedNumber",
    "VerificationResult",
    "extract_financial_numbers",
    "extract_all_numbers",
    "verify_numeric_consistency",
    "extract_tool_outputs_from_messages",
]
